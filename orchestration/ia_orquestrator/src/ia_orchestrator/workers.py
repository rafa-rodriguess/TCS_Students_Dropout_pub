"""Workers da orquestradora e da executora (polling)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ia_orchestrator.alerts import notify as alert_notify, phase_for_envelope_type
from ia_orchestrator.adapters.executor import ExecutorAdapter, ExecutorInput, SimulatedExecutorAdapter, SubprocessExecutorAdapter
from ia_orchestrator.adapters.model import ModelAdapter, SimulatedModelAdapter, build_model_adapter
from ia_orchestrator.config import ProjectConfig, data_dir
from ia_orchestrator.context import build_context_package, detect_revision_divergence
from ia_orchestrator.errors import LockError, PolicyError, ProtocolError
from ia_orchestrator.issue_status import (
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_RUNNING,
    STATUS_WAITING_ORCHESTRATOR,
)
from ia_orchestrator.locks import WorkerLock, WorkspaceLock
from ia_orchestrator.persistence import Store
from ia_orchestrator.policy import (
    assert_project_match,
    authorize_sender,
    can_dispatch,
    check_limits,
    reject_unauthorized_mutations,
)
from ia_orchestrator.protocol import (
    RECOVERY_CONTROL_TYPES,
    Envelope,
    MessageType,
    NO_MODEL_TYPES,
    QUARANTINE_NOTICE_MARKER,
    build_envelope,
    comment_hash,
    format_quarantine_notice,
    new_id,
    parse_comment,
    quarantine_notice_matches,
    render_executor_capabilities,
    render_message,
    utc_now,
)
from ia_orchestrator.state import (
    ExecutionState,
    RequestState,
    TaskState,
    apply_transition,
    blocks_new_work,
    decision_block,
)
from ia_orchestrator.transport import MemoryTransport, Transport, overlap_since


def _stable_id(kind: str, idem: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ia-orchestrator:{kind}:{idem}"))


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Engine:
    def __init__(
        self,
        cfg: ProjectConfig,
        store: Store,
        transport: Transport,
        role: str,
        *,
        model: ModelAdapter | None = None,
        executor: ExecutorAdapter | None = None,
        dry_run: bool = False,
        home: Path | None = None,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        if role not in {"orchestrator", "executor", "agent"}:
            raise PolicyError("role deve ser orchestrator, executor ou agent")
        self.cfg = cfg
        self.store = store
        self.transport = transport
        self.role = role
        self.dry_run = dry_run
        self.home = home
        self.clock = clock
        self.ns = cfg.namespace
        self.sender_id = {"orchestrator": cfg.orchestrator.worker_id, "executor": cfg.executor.worker_id, "agent": cfg.agent.worker_id}[role]
        self.model = model
        self.executor = executor
        self._interrupt = False

    def _alert(self, phase: str, **fields: Any) -> None:
        alert_notify(self.cfg, phase, **fields)

    def _record_quarantine(
        self,
        reason: str,
        *,
        github_comment_id: int | None = None,
        message_id: str | None = None,
        issue: int | None = None,
        detail: str | None = None,
        raw_body: str | None = None,
    ) -> bool:
        """Persiste quarentena, alerta Discord uma vez e comenta a issue (diagnóstico visível)."""
        first = self.store.quarantine(
            self.ns,
            reason,
            github_comment_id=github_comment_id,
            message_id=message_id,
            detail=detail,
            raw_body=raw_body,
        )
        if first:
            self._alert(
                "quarantine",
                reason=reason,
                message_id=message_id,
                issue=issue,
            )
            self._post_quarantine_notice(
                reason,
                github_comment_id=github_comment_id,
                message_id=message_id,
                issue=issue,
            )
        return first

    def _existing_quarantine_notice(
        self,
        issue: int,
        *,
        github_comment_id: int | None = None,
        message_id: str | None = None,
    ) -> bool:
        for comment in self.transport.list_issue_comments(int(issue)):
            if quarantine_notice_matches(
                comment.body,
                github_comment_id=github_comment_id,
                message_id=message_id,
            ):
                return True
        return False

    def _post_quarantine_notice(
        self,
        reason: str,
        *,
        github_comment_id: int | None = None,
        message_id: str | None = None,
        issue: int | None = None,
    ) -> None:
        if self.dry_run or not issue:
            return
        try:
            if self._existing_quarantine_notice(
                int(issue),
                github_comment_id=github_comment_id,
                message_id=message_id,
            ):
                return
            body = format_quarantine_notice(
                reason=reason,
                role=self.role,
                github_comment_id=github_comment_id,
                message_id=message_id,
                project_id=self.cfg.project_id,
            )
            comment = self.transport.create_comment(int(issue), body)
            self.store.audit(
                self.ns,
                "quarantine_notice_posted",
                None,
                {
                    "issue": int(issue),
                    "reason": reason,
                    "github_comment_id": github_comment_id,
                    "message_id": message_id,
                    "notice_comment_id": getattr(comment, "id", None),
                },
            )
        except Exception as exc:  # noqa: BLE001 — aviso na issue não desfaz a quarentena
            self.store.audit(
                self.ns,
                "quarantine_notice_failed",
                None,
                {"issue": int(issue), "reason": reason, "error": str(exc)},
            )

    def interrupt(self) -> None:
        self._interrupt = True
        if isinstance(self.executor, SubprocessExecutorAdapter):
            self.executor.interrupt()

    def cursor_chat_mode(self) -> bool:
        if self.role == "agent":
            return True  # agent only reads discussions; never executes jobs
        if self.role == "executor":
            return self.cfg.executor.mode == "cursor_chat"
        return self.cfg.orchestrator.mode == "cursor_chat"

    def tick(self) -> dict[str, Any]:
        stats = {"synced": 0, "processed": 0, "published": 0, "quarantine": 0}
        stats["synced"] = self.sync()
        if self.cursor_chat_mode():
            stats["processed"] = 0
        else:
            stats["processed"] = self.process_inbox()
        stats["published"] = 0 if self.role == "agent" else self.flush_outbox()
        stats["quarantine"] = len(self.store.list_quarantine(self.ns))
        return stats

    def sync(self) -> int:
        cursor = self.store.get_cursor(self.ns)
        since = overlap_since(cursor["since"] if cursor else None, self.cfg.polling.overlap_seconds)
        comments = self.transport.list_repo_comments(since=since)
        try:
            for issue in self.transport.list_issues(labels=["ia-orchestrator"], state="all"):
                self._ingest_issue_body(issue)
        except Exception as exc:  # noqa: BLE001
            self.store.audit(self.ns, "list_issues_failed", None, {"error": str(exc)})
        count = 0
        max_updated = cursor["since"] if cursor else None
        max_id = cursor["last_comment_id"] if cursor else None
        for comment in comments:
            payload = {
                "id": comment.id,
                "issue_number": comment.issue_number,
                "body": comment.body,
                "user": {"login": comment.user_login},
                "created_at": comment.created_at,
                "updated_at": comment.updated_at,
            }
            inserted = self.store.persist_event(self.ns, payload)
            self._ingest_comment(comment)
            count += 1 if inserted else 0
            if not max_updated or comment.updated_at >= max_updated:
                max_updated = comment.updated_at
            if max_id is None or comment.id >= int(max_id):
                max_id = comment.id
        if max_updated or max_id:
            self.store.set_cursor(self.ns, max_updated, max_id, self.cfg.polling.overlap_seconds)
        if self.role != "agent":
            self._reconcile_issues()  # the agent must not reconcile lifecycle state
        return count

    def _ingest_issue_body(self, issue: Any) -> None:
        if not getattr(issue, "body", None):
            return
        parsed = parse_comment(issue.body)
        if parsed.kind != "envelope" or not parsed.envelope:
            return
        env = parsed.envelope
        if env.project_id != self.cfg.project_id:
            return
        if self.store.get_message_by_id(self.ns, env.message_id):
            return
        self.store.upsert_message(
            self.ns,
            message_id=env.message_id,
            task_id=env.task_id,
            github_comment_id=None,
            issue_number=issue.number,
            envelope=env,
            body=parsed.body,
            raw=issue.body,
            observed_hash=comment_hash(issue.body),
            kind="envelope",
            github_login=getattr(issue, "user_login", None),
        )
        phase = phase_for_envelope_type(env.type)
        if phase:
            self._alert(
                phase,
                type=env.type,
                task_id=env.task_id,
                request_id=env.request_id,
                message_id=env.message_id,
                issue=issue.number,
            )
        self.store.upsert_task(
            self.ns,
            env.task_id,
            issue_number=issue.number,
            github_issue_id=getattr(issue, "id", None),
            title=getattr(issue, "title", None),
            objective=parsed.body,
            context_revision=env.context_revision,
            github_state=getattr(issue, "state", "open"),
        )

    def _reconcile_issues(self) -> None:
        for task in self.store.active_tasks(self.ns):
            number = task.get("issue_number")
            if not number:
                continue
            try:
                issue = self.transport.get_issue(int(number))
            except Exception as exc:  # noqa: BLE001
                self.store.audit(self.ns, "reconcile_issue_failed", task["task_id"], {"error": str(exc)})
                continue
            self._ingest_issue_body(issue)
            if issue.state == "closed" and task["github_state"] != "closed":
                self.store.set_task_state(
                    self.ns,
                    task["task_id"],
                    TaskState.CANCELLED.value if task["state"] not in {TaskState.COMPLETED.value, TaskState.FAILED.value} else task["state"],
                    previous=task["state"],
                    github_state="closed",
                    closed_at=utc_now(),
                )
                self.store.audit(self.ns, "issue_closed_manually", task["task_id"], {"issue": number})
            for comment in self.transport.list_issue_comments(int(number)):
                self.store.persist_event(
                    self.ns,
                    {
                        "id": comment.id,
                        "issue_number": comment.issue_number,
                        "body": comment.body,
                        "user": {"login": comment.user_login},
                        "created_at": comment.created_at,
                        "updated_at": comment.updated_at,
                    },
                )
                self._ingest_comment(comment)

    def _ingest_comment(self, comment: Any) -> None:
        if QUARANTINE_NOTICE_MARKER in (comment.body or ""):
            digest = comment_hash(comment.body)
            existing = self.store.get_message_by_github(self.ns, comment.id)
            if existing:
                return
            self.store.upsert_message(
                self.ns,
                message_id=f"obs-{comment.id}",
                task_id=None,
                github_comment_id=comment.id,
                issue_number=comment.issue_number,
                envelope=None,
                body=comment.body,
                raw=comment.body,
                observed_hash=digest,
                kind="observation",
                github_login=comment.user_login,
            )
            self.store.mark_processed(self.ns, f"obs-{comment.id}")
            return
        parsed = parse_comment(comment.body)
        digest = comment_hash(comment.body)
        existing = self.store.get_message_by_github(self.ns, comment.id)
        if existing and existing["observed_hash"] != digest:
            self.store.upsert_message(
                self.ns,
                message_id=existing["message_id"],
                task_id=existing.get("task_id"),
                github_comment_id=comment.id,
                issue_number=comment.issue_number,
                envelope=None,
                body=existing.get("body_text") or "",
                raw=comment.body,
                observed_hash=digest,
                kind=existing["kind"],
                github_login=comment.user_login,
            )
            self.store.audit(self.ns, "message_edited", existing.get("task_id"), {"github_comment_id": comment.id})
            return
        if existing:
            return
        if parsed.kind == "observation":
            self.store.upsert_message(
                self.ns,
                message_id=f"obs-{comment.id}",
                task_id=None,
                github_comment_id=comment.id,
                issue_number=comment.issue_number,
                envelope=None,
                body=parsed.body,
                raw=comment.body,
                observed_hash=digest,
                kind="observation",
                github_login=comment.user_login,
            )
            self.store.mark_processed(self.ns, f"obs-{comment.id}")
            return
        if parsed.kind == "quarantine" or parsed.envelope is None:
            mid = parsed.envelope.message_id if parsed.envelope else f"q-{comment.id}"
            self.store.upsert_message(
                self.ns,
                message_id=mid,
                task_id=parsed.envelope.task_id if parsed.envelope else None,
                github_comment_id=comment.id,
                issue_number=comment.issue_number,
                envelope=parsed.envelope,
                body=parsed.body,
                raw=comment.body,
                observed_hash=digest,
                kind="quarantine",
                github_login=comment.user_login,
                quarantine_reason=parsed.error,
            )
            self._record_quarantine(
                parsed.error or "envelope inválido",
                github_comment_id=comment.id,
                message_id=mid,
                issue=comment.issue_number,
                detail="incompatible" if parsed.incompatible else None,
                raw_body=comment.body,
            )
            self.store.mark_processed(self.ns, mid)
            return
        env = parsed.envelope
        if env.project_id != self.cfg.project_id:
            # outro projecto no mesmo repositório: ignorar sem contaminar
            return
        if env.repository.lower() != self.cfg.github.repository.lower():
            self._record_quarantine(
                "repositório divergente",
                github_comment_id=comment.id,
                issue=comment.issue_number,
                raw_body=comment.body,
            )
            return
        is_new = self.store.get_message_by_id(self.ns, env.message_id) is None
        self.store.upsert_message(
            self.ns,
            message_id=env.message_id,
            task_id=env.task_id,
            github_comment_id=comment.id,
            issue_number=comment.issue_number,
            envelope=env,
            body=parsed.body,
            raw=comment.body,
            observed_hash=digest,
            kind="envelope",
            github_login=comment.user_login,
        )
        if is_new:
            phase = phase_for_envelope_type(env.type)
            if phase:
                self._alert(
                    phase,
                    type=env.type,
                    task_id=env.task_id,
                    request_id=env.request_id,
                    message_id=env.message_id,
                    issue=comment.issue_number,
                )

    def process_inbox(self) -> int:
        if self.role == "agent":
            return 0  # this role never drains the primary task inbox
        processed = 0
        for row in self.store.unprocessed_messages(self.ns):
            if row["kind"] != "envelope":
                self.store.mark_processed(self.ns, row["message_id"])
                continue
            if row.get("hash_diverged"):
                self._record_quarantine(
                    "mensagem editada após observação; não executar o texto alterado",
                    github_comment_id=row.get("github_comment_id"),
                    message_id=row["message_id"],
                    issue=row.get("issue_number"),
                )
                self.store.mark_processed(self.ns, row["message_id"])
                processed += 1
                continue
            env = Envelope.model_validate(json.loads(row["envelope_json"]))
            # Discussion is claimed by the agent's chat-only queue, not by either
            # primary worker. Keep it pending until a corresponding answer exists.
            if env.type == MessageType.DISCUSS.value:
                continue
            if env.type == MessageType.ANALYSIS.value or (
                env.sender_role == "agent" and env.type == MessageType.QUESTION.value
            ):
                if self.role != "orchestrator":
                    continue
            if env.in_reply_to and not self.store.get_message_by_id(self.ns, env.in_reply_to):
                self.store.add_pending_ref(self.ns, env.message_id, env.in_reply_to)
                continue
            try:
                assert_project_match(self.cfg, env)
                authorize_sender(self.cfg, env, row.get("github_login"))
            except PolicyError as exc:
                self._record_quarantine(
                    str(exc),
                    github_comment_id=row.get("github_comment_id"),
                    message_id=env.message_id,
                    issue=row.get("issue_number"),
                )
                self.store.mark_processed(self.ns, env.message_id)
                processed += 1
                continue
            self._ensure_task_from_envelope(env, row)
            try:
                self._apply_state(env, row)
                if self.role == "orchestrator":
                    self._orchestrator_act(env, row)
                elif self.role == "executor":
                    self._executor_act(env, row)
            except (PolicyError, ProtocolError) as exc:
                self._record_quarantine(
                    str(exc),
                    message_id=env.message_id,
                    issue=row.get("issue_number"),
                )
            self.store.mark_processed(self.ns, env.message_id)
            processed += 1
        return processed

    def _ensure_task_from_envelope(self, env: Envelope, row: dict[str, Any]) -> None:
        task = self.store.get_task(self.ns, env.task_id)
        if not task:
            self.store.upsert_task(
                self.ns,
                env.task_id,
                issue_number=row.get("issue_number"),
                title=env.type,
                objective=row.get("body_text"),
                context_revision=env.context_revision,
            )

    def _apply_state(self, env: Envelope, row: dict[str, Any]) -> None:
        # Discussion is side-band. It never changes the primary executor state,
        # request counters, issue labels, or execution lock.
        if env.type in {MessageType.DISCUSS.value, MessageType.ANALYSIS.value} or (
            env.sender_role == "agent" and env.type == MessageType.QUESTION.value
        ):
            return
        task = self.store.get_task(self.ns, env.task_id)
        assert task is not None
        current = TaskState(task["state"])
        if current in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED} and env.type in {
            MessageType.RESULT.value,
            MessageType.ACK.value,
            MessageType.PROGRESS.value,
            MessageType.ERROR.value,
            MessageType.REQUEST.value,
            MessageType.SEND_FILE.value,
            MessageType.SEND_FILE_READY.value,
            MessageType.GET_FILE.value,
        }:
            self.store.audit(self.ns, "late_message", env.task_id, {"type": env.type, "message_id": env.message_id})
            return
        try:
            new_state = apply_transition(
                current,
                env.type,
                previous=TaskState(task["previous_state"]) if task.get("previous_state") else None,
                answer_resumes_to=TaskState(task["resume_state"]) if task.get("resume_state") else None,
            )
        except ProtocolError:
            if current in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                self.store.audit(self.ns, "late_message", env.task_id, {"type": env.type, "message_id": env.message_id})
                return
            raise
        if new_state is None:
            return
        resume = task.get("resume_state")
        if env.type == MessageType.PAUSE.value:
            resume = current.value
        if env.type == MessageType.QUESTION.value:
            resume = current.value
            if env.request_id:
                self.store.set_request_blocked(self.ns, env.request_id, env.message_id)
        if env.type == MessageType.ANSWER.value and env.request_id:
            self.store.set_request_blocked(self.ns, env.request_id, None)
        if env.type in {MessageType.REQUEST.value, MessageType.SEND_FILE.value, MessageType.GET_FILE.value} or env.type in RECOVERY_CONTROL_TYPES:
            self.store.upsert_request(
                self.ns,
                env.request_id or env.message_id,
                env.task_id,
                message_id=env.message_id,
                attempt=env.attempt,
                status=RequestState.OPEN.value,
            )
        closed = utc_now() if new_state in {TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED} else None
        self.store.set_task_state(
            self.ns,
            env.task_id,
            new_state.value,
            previous=current.value,
            resume_state=resume,
            closed_at=closed,
            active_request_id=env.request_id if env.type in {MessageType.REQUEST.value, MessageType.SEND_FILE.value, MessageType.GET_FILE.value} else None,
            bump_round=env.type in {MessageType.REQUEST.value, MessageType.SEND_FILE.value, MessageType.GET_FILE.value},
            bump_revision=env.type == MessageType.REVIEW.value,
        )
        if env.type == MessageType.CANCEL.value:
            self._interrupt = True

    def _orchestrator_act(self, env: Envelope, row: dict[str, Any]) -> None:
        if env.type in NO_MODEL_TYPES:
            return
        task = self.store.get_task(self.ns, env.task_id)
        assert task is not None
        if blocks_new_work(TaskState(task["state"])) and env.type not in {MessageType.COMPLETE.value, MessageType.CANCEL.value}:
            return
        skip_model = self.cfg.orchestrator.mode in {"manual", "cursor_chat"}
        if env.type == MessageType.TASK_OPEN.value and not skip_model:
            self._decide_and_apply(task, trigger=env)
        elif env.type in {MessageType.RESULT.value, MessageType.CONTROL_RESULT.value} and not skip_model:
            reject_unauthorized_mutations(row.get("body_text") or "", self.cfg)
            self._decide_and_apply(task, trigger=env, result_body=row.get("body_text"))
        elif env.type == MessageType.ERROR.value and not skip_model:
            self._decide_and_apply(task, trigger=env)
        elif env.type == MessageType.QUESTION.value and env.sender_role == "executor" and self.cfg.orchestrator.mode == "api":
            self._decide_and_apply(task, trigger=env)

    def _decide_and_apply(self, task: dict[str, Any], trigger: Envelope, result_body: str | None = None) -> None:
        reason = check_limits(
            self.cfg,
            rounds=task["round_count"],
            revisions=task["revision_count"],
            usage=self.store.task_usage(self.ns, task["task_id"]),
        )
        if reason:
            self._publish(
                task,
                MessageType.PAUSE.value,
                f"## Pausa automática\n{reason}\n",
                recipient="broadcast",
            )
            return
        messages = self.store.messages_for_task(self.ns, task["task_id"])
        result = None
        if result_body:
            result = {"raw": result_body}
            last_exec = self.store.get_execution_by_request(self.ns, trigger.request_id or "", trigger.attempt)
            if last_exec and last_exec.get("output_json"):
                result = json.loads(last_exec["output_json"])
            else:
                parsed_body = result_body
                try:
                    # corpo de result pode começar com JSON
                    start = parsed_body.find("{")
                    if start >= 0:
                        result = json.loads(parsed_body[start : parsed_body.rfind("}") + 1])
                except json.JSONDecodeError:
                    result = {"summary": result_body, "status": "unknown"}
        package = build_context_package(self.cfg, task=task, messages=messages, result=result)
        if detect_revision_divergence(task.get("context_revision"), package["context_revision"]):
            self._publish(
                task,
                MessageType.QUESTION.value,
                "## Divergência de revisão de contexto\nO contexto mudou desde a solicitação. Confirme se deve reavaliar antes de continuar.\n",
                recipient="human",
                request_id=trigger.request_id,
                in_reply_to=trigger.message_id,
            )
            return
        if self.dry_run:
            self.store.audit(self.ns, "dry_run_model_skipped", task["task_id"], {})
            return
        adapter = self.model or build_model_adapter(self.cfg)
        result_model = adapter.complete(package, dry_run=self.dry_run)
        self.store.record_model_call(
            self.ns,
            task_id=task["task_id"],
            request_id=trigger.request_id,
            provider=self.cfg.orchestrator.provider,
            model=self.cfg.orchestrator.model,
            prompt_tokens=result_model.prompt_tokens,
            completion_tokens=result_model.completion_tokens,
            cost_usd=result_model.cost_usd,
            cost_known=result_model.cost_known,
            decision=result_model.decision.model_dump() if result_model.decision else None,
            error=result_model.error,
        )
        if result_model.error or not result_model.decision:
            self._publish(
                task,
                MessageType.PAUSE.value,
                f"## Saída inválida do modelo\n{result_model.error}\n",
                recipient="broadcast",
            )
            return
        decision = result_model.decision
        if decision.decision == "dispatch" or decision.decision == "revise":
            if not can_dispatch(task["state"]) and TaskState(task["state"]) not in {TaskState.NEW, TaskState.WAITING_ORCHESTRATOR}:
                return
            nxt = decision.next_request or {}
            body = nxt.get("body") or decision.rationale
            criteria = nxt.get("acceptance_criteria") or []
            crit = "\n".join(f"- {c}" for c in criteria)
            request_id = new_id()
            text = f"## Objetivo\n{body}\n\n## Critérios de aceitação\n{crit or '- Critérios observáveis'}\n"
            if decision.decision == "revise":
                self._publish(task, MessageType.REVIEW.value, f"## Revisão\n{decision.rationale}\n", recipient="executor", request_id=trigger.request_id, in_reply_to=trigger.message_id)
                task = self.store.get_task(self.ns, task["task_id"]) or task
            self._publish(
                task,
                MessageType.REQUEST.value,
                text,
                recipient="executor",
                request_id=request_id,
                in_reply_to=trigger.message_id,
            )
        elif decision.decision == "complete":
            self._publish(
                task,
                MessageType.COMPLETE.value,
                f"## Aceite final\n{decision.rationale}\n\nEvidências: {decision.evidence}\n",
                recipient="broadcast",
                request_id=trigger.request_id,
                in_reply_to=trigger.message_id,
            )
        elif decision.decision == "ask_human":
            self._publish(
                task,
                MessageType.QUESTION.value,
                f"## Pergunta à humana\n{decision.question or decision.rationale}\n",
                recipient="human",
                request_id=trigger.request_id,
                in_reply_to=trigger.message_id,
            )
        elif decision.decision == "ask_executor":
            self._publish(
                task,
                MessageType.QUESTION.value,
                f"## Pergunta à executora\n{decision.question or decision.rationale}\n",
                recipient="executor",
                request_id=trigger.request_id,
                in_reply_to=trigger.message_id,
            )
        elif decision.decision == "pause":
            self._publish(task, MessageType.PAUSE.value, f"## Pausa\n{decision.rationale}\n", recipient="broadcast")
        elif decision.decision == "fail":
            self._publish(task, MessageType.ERROR.value, f"## Falha\n{decision.rationale}\n", recipient="broadcast")

    def _executor_act(self, env: Envelope, row: dict[str, Any]) -> None:
        if env.type == MessageType.ANSWER.value:
            task = self.store.get_task(self.ns, env.task_id)
            if task and env.request_id:
                req = self.store.get_request(self.ns, env.request_id)
                if req and req.get("status") == RequestState.DONE.value:
                    return
                original = self.store.get_message_by_id(self.ns, (req or {}).get("message_id") or env.in_reply_to or "")
                if original and original.get("envelope_json"):
                    self._run_request(
                        Envelope.model_validate(json.loads(original["envelope_json"])),
                        original,
                        resume=True,
                    )
            return
        if env.type == MessageType.SEND_FILE.value:
            if self.cfg.executor.mode == "subprocess":
                from ia_orchestrator.send_file import perform_executor_send_file

                perform_executor_send_file(self, self.home, env, row.get("body_text") or "")
            else:
                self.store.audit(
                    self.ns,
                    f"{self.cfg.executor.mode}_send_file_pending",
                    env.task_id,
                    {"request_id": env.request_id},
                )
            return
        if env.type == MessageType.GET_FILE.value:
            if self.cfg.executor.mode == "subprocess":
                from ia_orchestrator.get_file import perform_executor_get_file

                perform_executor_get_file(self, self.home, env, row.get("body_text") or "")
            else:
                self.store.audit(
                    self.ns,
                    f"{self.cfg.executor.mode}_get_file_pending",
                    env.task_id,
                    {"request_id": env.request_id},
                )
            return
        if env.type == MessageType.REQUEST.value or env.type in RECOVERY_CONTROL_TYPES:
            self._run_request(env, row)

    def _run_request(self, env: Envelope, row: dict[str, Any], *, resume: bool = False) -> None:
        task = self.store.get_task(self.ns, env.task_id)
        assert task is not None
        if blocks_new_work(TaskState(task["state"])):
            self.store.audit(self.ns, "skip_request_terminal", env.task_id, {"request_id": env.request_id})
            return
        if self.cfg.executor.mode in {"manual", "cursor_chat"}:
            self.store.audit(self.ns, f"{self.cfg.executor.mode}_pending", env.task_id, {"request_id": env.request_id})
            return
        request_id = env.request_id or env.message_id
        attempt = env.attempt
        idem = f"{self.ns}:{request_id}:{attempt}" + (":resume" if resume else "")
        existing = self.store.get_execution(self.ns, idem)
        if existing and existing["status"] in {ExecutionState.STARTING.value, ExecutionState.RUNNING.value}:
            self.store.finish_execution(
                self.ns,
                idem,
                ExecutionState.UNKNOWN.value,
                error="crash com execução em estado desconhecido; não repetir efeitos",
            )
            existing = self.store.get_execution(self.ns, idem)
        if existing and existing["status"] in {ExecutionState.SUCCEEDED.value, ExecutionState.FAILED.value}:
            published = self.store.get_outbox(self.ns, _stable_id("result", idem))
            if existing.get("output_json") and (not published or published["status"] != "PUBLISHED"):
                self._publish_executor_output(task, env, json.loads(existing["output_json"]), idem)
            return
        if existing and existing["status"] == ExecutionState.BLOCKED.value and not resume:
            return
        if existing and existing["status"] == ExecutionState.UNKNOWN.value:
            self._publish(
                task,
                MessageType.QUESTION.value,
                "## Execução em estado desconhecido após crash\nNão vou repetir efeitos cegamente. Confirme checkpoint ou indique nova tentativa.\n",
                recipient="orchestrator",
                request_id=request_id,
                in_reply_to=env.message_id,
            )
            self._finish_handback(task, request_id)
            return
        workspace = self.cfg.workspace_root()
        wlock = WorkspaceLock(self.store, workspace, self.ns, env.task_id, self.sender_id)
        wlock.acquire()
        try:
            self._check_workspace_dirty(workspace)
            if self.dry_run:
                self.store.audit(self.ns, "dry_run_executor_skipped", env.task_id, {})
                return
            messages = self.store.messages_for_task(self.ns, env.task_id)
            package = build_context_package(self.cfg, task=task, messages=messages)
            payload = ExecutorInput(
                project_id=self.cfg.project_id,
                repository=self.cfg.github.repository,
                task_id=env.task_id,
                request_id=request_id,
                attempt=attempt,
                prompt=row.get("body_text") or "",
                context=package,
                context_revision=package["context_revision"],
                cwd=str(workspace),
                acceptance_criteria=[],
                limits=self.cfg.limits.model_dump(),
                idempotency_key=idem,
            )
            # persistir início ANTES do adaptador
            execution = self.store.start_execution(
                self.ns,
                idempotency_key=idem,
                request_id=request_id,
                task_id=env.task_id,
                attempt=attempt,
                input_json=payload.model_dump(),
            )
            if execution["status"] == ExecutionState.STARTING.value:
                self.store.finish_execution(self.ns, idem, ExecutionState.RUNNING.value)
            self.announce_request_claimed(
                task,
                request_id=request_id,
                in_reply_to=env.message_id,
                issue=task.get("issue_number"),
                discord=True,
            )
            self.announce_execution_started(
                task,
                request_id=request_id,
                in_reply_to=env.message_id,
                issue=task.get("issue_number"),
            )
            self.flush_outbox()
            adapter = self.executor or self._build_executor(workspace)
            try:
                output = adapter.run(payload, dry_run=self.dry_run)
            except Exception as exc:  # noqa: BLE001
                self.store.finish_execution(self.ns, idem, ExecutionState.UNKNOWN.value, error=str(exc))
                self._publish(
                    task,
                    MessageType.ERROR.value,
                    f"## Erro de execução\n{exc}\nEstado: unknown. Não repetir cegamente.\n",
                    recipient="orchestrator",
                    request_id=request_id,
                    in_reply_to=env.message_id,
                )
                self._finish_handback(task, request_id)
                return
            status_map = {
                "success": ExecutionState.SUCCEEDED.value,
                "failed": ExecutionState.FAILED.value,
                "blocked": ExecutionState.BLOCKED.value,
                "unknown": ExecutionState.UNKNOWN.value,
            }
            self.store.finish_execution(
                self.ns,
                idem,
                status_map.get(output.status, ExecutionState.UNKNOWN.value),
                output=output.model_dump(),
                checkpoint=output.checkpoint,
            )
            self._publish_executor_output(task, env, output.model_dump(), idem)
        finally:
            wlock.release()

    def _publish_executor_output(self, task: dict[str, Any], env: Envelope, output: dict[str, Any], idem: str) -> None:
        request_id = env.request_id or env.message_id
        if env.type in RECOVERY_CONTROL_TYPES:
            body = (
                f"## Resultado de controle — {env.type}\n{output.get('summary','')}\n\n"
                f"```json\n{json.dumps(output, indent=2, ensure_ascii=False)}\n```\n"
            )
            self._publish(
                task,
                MessageType.CONTROL_RESULT.value,
                body,
                recipient="orchestrator",
                request_id=request_id,
                in_reply_to=env.message_id,
                message_id=_stable_id("control_result", idem),
            )
            # Side-band controls must not move the primary issue to
            # waiting-orchestrator. The primary execution keeps its own state.
            return
        if decision_block(output):
            body = (
                f"## Resultado\n{output.get('summary','')}\n\n"
                f"```json\n{json.dumps(output, indent=2, ensure_ascii=False)}\n```\n"
            )
            self._publish(
                task,
                MessageType.RESULT.value,
                body,
                recipient="orchestrator",
                request_id=request_id,
                in_reply_to=env.message_id,
                message_id=_stable_id("result", idem),
            )
            self.store.release_request(self.ns, request_id)
            self._finish_handback(task, request_id)
            return
        if output.get("questions") or output.get("status") == "blocked":
            qs = "\n".join(f"- {q}" for q in output.get("questions") or ["esclarecimento necessário"])
            self._publish(
                task,
                MessageType.QUESTION.value,
                f"## Esclarecimento\n{qs}\n",
                recipient="orchestrator",
                request_id=request_id,
                in_reply_to=env.message_id,
            )
            self._finish_handback(task, request_id)
            return
        artifacts = output.get("shared_artifacts") or []
        if artifacts:
            missing = [a for a in artifacts if isinstance(a, dict) and not (a.get("commit") or a.get("sha256"))]
            if missing:
                self.store.audit(self.ns, "artifact_missing_shared_ref", task.get("task_id"), {"missing": missing})
        body = (
            f"## Resultado\n{output.get('summary','')}\n\n"
            f"```json\n{json.dumps(output, indent=2, ensure_ascii=False)}\n```\n"
        )
        self._publish(
            task,
            MessageType.RESULT.value,
            body,
            recipient="orchestrator",
            request_id=request_id,
            in_reply_to=env.message_id,
            message_id=_stable_id("result", idem),
        )
        self._finish_handback(task, request_id)
        if output.get("status") == "success":
            self._publish_commits()

    def _build_executor(self, workspace: Path) -> ExecutorAdapter:
        if self.cfg.executor.mode == "simulated":
            return SimulatedExecutorAdapter()
        return SubprocessExecutorAdapter(
            self.cfg.executor.command,
            cwd=workspace,
            timeout=int(self.cfg.executor.timeout_seconds or self.cfg.limits.executor_timeout_seconds),
        )

    def _check_workspace_dirty(self, workspace: Path) -> None:
        git = workspace / ".git"
        if not git.exists():
            return
        # não descartar alterações do utilizador
        import subprocess

        diff = subprocess.run(  # noqa: S603
            ["git", "-C", str(workspace), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if diff.returncode == 0 and diff.stdout.strip():
            self.store.audit(self.ns, "workspace_dirty", None, {"status": diff.stdout[-1000:]})

    def _finish_handback(self, task: dict[str, Any], request_id: str) -> None:
        """Arquiva o running e tira o label running. A issue permanece aberta."""
        self.set_issue_status(task.get("issue_number"), STATUS_WAITING_ORCHESTRATOR)
        self._release_local_claim(request_id)

    def _publish_commits(self) -> None:
        from ia_orchestrator.publish import publish_authorized_commits

        report = publish_authorized_commits(self.cfg.workspace_root(), allow_push=self.cfg.policy.allow_push)
        self.store.audit(self.ns, "authorized_push", None, report)

    def _release_local_claim(self, request_id: str) -> None:
        """Arquiva running/ desta request. Não fecha a issue nem a tarefa."""
        if not self.home or not request_id:
            return
        from ia_orchestrator.loop import complete_local_claim

        complete_local_claim(self.cfg, self.store, self.home, request_id)

    def set_issue_status(self, issue_number: int | None, status: str) -> None:
        if not issue_number or self.dry_run:
            return
        try:
            self.transport.set_issue_status_label(int(issue_number), status)
            self.store.audit(self.ns, "issue_status_label", None, {"issue": int(issue_number), "status": status})
        except Exception as exc:  # noqa: BLE001 — label não bloqueia o protocolo
            self.store.audit(self.ns, "issue_status_label_failed", None, {"issue": int(issue_number), "error": str(exc)})

    def announce_request_claimed(
        self,
        task: dict[str, Any],
        *,
        request_id: str,
        in_reply_to: str | None,
        issue: int | None = None,
        discord: bool = True,
    ) -> None:
        """Publica ack + label status:claimed. Discord opcional (o loop.claim já alerta)."""
        if not task.get("issue_number"):
            return
        idem = f"{self.ns}:{request_id}:claim"
        mid = _stable_id("ack", idem)
        first = not self.store.get_outbox(self.ns, mid)
        if first:
            self._publish(
                task,
                MessageType.ACK.value,
                "## ACK\nPedido puxado (claim) nesta issue. A execução ainda não começou.\n\n" + render_executor_capabilities() + "\n",
                recipient="orchestrator",
                request_id=request_id,
                in_reply_to=in_reply_to,
                message_id=mid,
            )
            if discord:
                self._alert(
                    "request_claimed",
                    role=self.role,
                    type="ack",
                    status=STATUS_CLAIMED,
                    task_id=task.get("task_id"),
                    request_id=request_id,
                    issue=issue or task.get("issue_number"),
                )
        self.set_issue_status(issue or task.get("issue_number"), STATUS_CLAIMED)

    def announce_execution_started(
        self,
        task: dict[str, Any],
        *,
        request_id: str,
        in_reply_to: str | None,
        issue: int | None = None,
        role: str | None = None,
    ) -> None:
        if not task.get("issue_number"):
            return
        idem = f"{self.ns}:{request_id}:1"
        mid = _stable_id("progress", idem)
        first = not self.store.get_outbox(self.ns, mid)
        if first:
            self._publish(
                task,
                MessageType.PROGRESS.value,
                "## Execução começou\nA executora iniciou o trabalho desta `request` nesta issue.\n\n" + render_executor_capabilities() + "\n",
                recipient="orchestrator",
                request_id=request_id,
                in_reply_to=in_reply_to,
                message_id=mid,
            )
        self.set_issue_status(issue or task.get("issue_number"), STATUS_RUNNING)
        if first:
            self._alert(
                "execution_started",
                role=role or self.role,
                type="progress",
                status=STATUS_RUNNING,
                task_id=task.get("task_id"),
                request_id=request_id,
                issue=issue or task.get("issue_number"),
            )

    def _publish(
        self,
        task: dict[str, Any],
        type_: str,
        body: str,
        *,
        recipient: str,
        request_id: str | None = None,
        in_reply_to: str | None = None,
        message_id: str | None = None,
        sender_role: str | None = None,
    ) -> Envelope:
        if self.role == "agent" and type_ not in {
            MessageType.ANALYSIS.value, MessageType.QUESTION.value
        }:
            raise PolicyError("agent não publica nem executa tarefas")
        if type_ == MessageType.DISCUSS.value and self.role != "orchestrator":
            raise PolicyError("apenas orquestradora solicita discuss")
        issue = task.get("issue_number")
        if not issue:
            raise ProtocolError("tarefa sem issue_number; não é possível publicar")
        role = sender_role or self.role
        env = build_envelope(
            project_id=self.cfg.project_id,
            repository=self.cfg.github.repository,
            task_id=task["task_id"],
            sender_role=role,
            sender_id=self.sender_id if role == self.role else role,
            recipient_role=recipient,
            type=type_,
            body=body,
            in_reply_to=in_reply_to,
            request_id=request_id,
            attempt=1,
            context_revision=task.get("context_revision"),
            message_id=message_id,
        )
        rendered = render_message(env, body)
        self.store.enqueue_outbox(self.ns, env.message_id, env.task_id, int(issue), rendered)
        if self.dry_run:
            self.store.audit(self.ns, "dry_run_publish_skipped", env.task_id, {"message_id": env.message_id, "type": type_})
            return env
        return env

    def flush_outbox(self) -> int:
        published = 0
        for item in self.store.pending_outbox(self.ns):
            if self.role == "agent":
                parsed = parse_comment(item["body"])
                if not parsed.envelope or (
                    parsed.envelope.sender_role != "agent"
                    or parsed.envelope.type not in {MessageType.ANALYSIS.value, MessageType.QUESTION.value}
                    or parsed.envelope.recipient_role != "orchestrator"
                ):
                    continue  # do not flush the primary worker's shared outbox
            if self.dry_run:
                continue
            issue = int(item["issue_number"])
            mid = item["message_id"]
            existing = self.transport.find_comment_by_message_id(issue, mid)
            if existing:
                self.store.mark_outbox(self.ns, mid, "PUBLISHED", github_comment_id=existing.id)
                published += 1
                self._close_issue_if_complete_body(issue, item["body"])
                continue
            attempts = int(item["attempts"]) + 1
            self.store.mark_outbox(self.ns, mid, "PUBLISHING", attempts=attempts)
            try:
                comment = self.transport.create_comment(issue, item["body"])
            except Exception as exc:  # noqa: BLE001
                found = self.transport.find_comment_by_message_id(issue, mid)
                if found:
                    self.store.mark_outbox(self.ns, mid, "PUBLISHED", github_comment_id=found.id)
                    published += 1
                    self._close_issue_if_complete_body(issue, item["body"])
                    continue
                self.store.mark_outbox(self.ns, mid, "FAILED", last_error=str(exc), attempts=attempts)
                continue
            self.store.mark_outbox(self.ns, mid, "PUBLISHED", github_comment_id=comment.id)
            published += 1
            self._close_issue_if_complete_body(issue, item["body"])
        return published

    def _close_issue_if_complete_body(self, issue_number: int, body: str) -> None:
        parsed = parse_comment(body)
        if not parsed.envelope or parsed.envelope.type != MessageType.COMPLETE.value:
            return
        if self.dry_run:
            return
        try:
            self.store.set_task_state(
                self.ns,
                parsed.envelope.task_id,
                TaskState.COMPLETED.value,
                github_state="closed",
                closed_at=utc_now(),
            )
        except KeyError:
            pass
        try:
            self.set_issue_status(issue_number, STATUS_COMPLETED)
            self.transport.close_issue(issue_number)
            self.store.audit(
                self.ns,
                "issue_closed_on_complete",
                parsed.envelope.task_id,
                {"issue": issue_number},
            )
        except Exception as exc:  # noqa: BLE001 — complete já está publicado
            self.store.audit(
                self.ns,
                "issue_close_failed",
                parsed.envelope.task_id,
                {"issue": issue_number, "error": str(exc)},
            )


def run_worker(
    cfg: ProjectConfig,
    store: Store,
    transport: Transport,
    role: str,
    *,
    once: bool = False,
    dry_run: bool = False,
    home: Path | None = None,
    model: ModelAdapter | None = None,
    executor: ExecutorAdapter | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> list[dict[str, Any]]:
    import time

    lock_dir = data_dir(cfg, home) / "locks"
    section = {"orchestrator": cfg.orchestrator, "executor": cfg.executor, "agent": cfg.agent}[role]
    worker_id = section.worker_id
    owner = section.owner
    lock = WorkerLock(store, lock_dir, cfg.project_id, role, worker_id, owner or "unknown")
    lock.acquire()
    engine = Engine(cfg, store, transport, role, model=model, executor=executor, dry_run=dry_run, home=home)
    ticks = []
    try:
        while True:
            ticks.append(engine.tick())
            lock.heartbeat()
            if once:
                break
            interval = cfg.polling.interval_seconds
            (sleeper or time.sleep)(interval)
    finally:
        lock.release()
    return ticks
