"""Inspect/claim da campainha Cursor: GitHub é a SoT; running/ é o work item local."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ia_orchestrator.alerts import notify as alert_notify
from ia_orchestrator.config import ProjectConfig, data_dir, default_home
from ia_orchestrator.errors import AuthError, NetworkError, PolicyError
from ia_orchestrator.persistence import Store
from ia_orchestrator.protocol import RECOVERY_CONTROL_TYPES, Envelope, MessageType, utc_now
from ia_orchestrator.workers import Engine

STATUS_IDLE = "IDLE"
STATUS_JOB = "JOB"
STATUS_RECOVERY = "RECOVERY_REQUIRED"
STATUS_CONFLICT = "QUEUE_CONFLICT"
STATUS_GIT_ERROR = "GIT_ERROR"

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def running_dir(cfg: ProjectConfig, home: Path | None, role: str = "executor") -> Path:
    if role == "agent":
        path = data_dir(cfg, home) / "agent_discussions"
        path.mkdir(parents=True, exist_ok=True)
        return path
    if cfg.loop.running_dir:
        path = Path(cfg.loop.running_dir).expanduser()
        if not path.is_absolute():
            path = Path(cfg.workspace.root).expanduser() / path
        path = path.resolve()
    else:
        path = data_dir(cfg, home) / "running"
    path.mkdir(parents=True, exist_ok=True)
    return path


def last_wake_path(cfg: ProjectConfig, home: Path | None, role: str) -> Path:
    return data_dir(cfg, home) / f"cursor_loop_{role}.last_wake"


def rearm_next_wake(cfg: ProjectConfig, home: Path | None, role: str) -> dict[str, Any]:
    """Clear only the wake-dedup marker so the background poller wakes again.

    Unlike 'loop tick --reset-wake', this helper does not tick immediately.
    A cursor-chat executor uses it as the last action before yielding an
    unfinished RECOVERY_REQUIRED job to the next assistant turn.
    """
    path = last_wake_path(cfg, home, role)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return {
        "project_id": cfg.project_id,
        "repository": cfg.resolved_repo_label(),
        "role": role,
        "rearmed": True,
        "had_previous_wake": existed,
        "last_wake_path": str(path),
    }


def pid_path(cfg: ProjectConfig, home: Path | None, role: str) -> Path:
    return data_dir(cfg, home) / f"cursor_loop_{role}.pid"


def list_running_md(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".md")


def sentinel_for(role: str) -> str:
    if role == "orchestrator":
        return "AGENT_LOOP_TICK_orchestrator"
    if role == "agent":
        return "AGENT_LOOP_TICK_agent"
    return "AGENT_LOOP_TICK_executor"


def _logical_name(row: dict[str, Any]) -> str:
    raw = row.get("request_id") or row.get("message_id") or "job"
    short = str(raw).replace("-", "")[:12]
    kind = row.get("type") or "job"
    return _SAFE.sub("-", f"{kind}-{short}")[:80]


def pending_rows(store: Store, namespace: str, role: str, cfg: ProjectConfig | None = None) -> list[dict[str, Any]]:
    rows = []
    for row in store.unprocessed_messages(namespace):
        if row.get("kind") != "envelope":
            continue
        recipient = row.get("recipient_role")
        typ = row.get("type")
        if role == "agent":
            if recipient != "agent" or typ != MessageType.DISCUSS.value or row.get("sender_role") != "orchestrator":
                continue
            if cfg is not None and row.get("github_login") not in cfg.github.allowed_senders.orchestrator:
                continue
            # The replying agent might live on another host/SQLite. GitHub
            # replies are definitive; suppress already answered discussions.
            replies = store.messages_for_task(namespace, str(row.get("task_id")))
            if any(
                reply.get("sender_role") == "agent"
                and reply.get("in_reply_to") == row.get("message_id")
                and reply.get("request_id") == row.get("request_id")
                and reply.get("type") in {MessageType.ANALYSIS.value, MessageType.QUESTION.value}
                for reply in replies
            ):
                continue
            rows.append(row)
            continue
        if recipient not in {role, "broadcast"}:
            continue
        if role == "executor" and typ in ({MessageType.REQUEST.value, MessageType.SEND_FILE.value, MessageType.GET_FILE.value} | RECOVERY_CONTROL_TYPES):
            rows.append(row)
        elif role == "orchestrator" and typ in {
            MessageType.RESULT.value,
            MessageType.CONTROL_RESULT.value,
            MessageType.QUESTION.value,
            MessageType.ANALYSIS.value,
            MessageType.SEND_FILE_READY.value,
        }:
            rows.append(row)
        elif role == "orchestrator" and typ == MessageType.TASK_OPEN.value:
            task_id = row.get("task_id")
            already = any(
                m.get("type") == MessageType.REQUEST.value
                for m in store.messages_for_task(namespace, str(task_id))
            )
            if not already:
                rows.append(row)
    return rows


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": row.get("type"),
        "task_id": row.get("task_id"),
        "request_id": row.get("request_id"),
        "message_id": row.get("message_id"),
        "issue_number": row.get("issue_number"),
    }


def inspect(cfg: ProjectConfig, store: Store, role: str, home: Path | None) -> dict[str, Any]:
    directory = running_dir(cfg, home, role)
    running = list_running_md(directory)
    pending = pending_rows(store, cfg.namespace, role, cfg)
    control_pending = [
        row for row in pending
        if role == "executor" and row.get("type") in RECOVERY_CONTROL_TYPES
    ]
    if len(running) > 1:
        status = STATUS_CONFLICT
    elif len(running) == 1:
        status = STATUS_RECOVERY
    elif pending:
        status = STATUS_JOB
    else:
        status = STATUS_IDLE
    return {
        "status": status,
        "project_id": cfg.project_id,
        "repository": cfg.resolved_repo_label(),
        "role": role,
        "running_dir": str(directory),
        "running": [p.name for p in running],
        "pending": [_compact(r) for r in pending],
        "head": _compact(pending[0]) if pending else None,
        "control_pending": [_compact(r) for r in control_pending],
        "control_head": _compact(control_pending[0]) if control_pending else None,
    }


def write_running_file(path: Path, cfg: ProjectConfig, row: dict[str, Any]) -> None:
    header = {
        "project_id": cfg.project_id,
        "repository": cfg.github.repository,
        "host": cfg.github.host,
        "task_id": row.get("task_id"),
        "request_id": row.get("request_id"),
        "message_id": row.get("message_id"),
        "issue": row.get("issue_number"),
        "type": row.get("type"),
        "claimed_at": utc_now(),
    }
    body = row.get("body_text") or ""
    lines = ["---"]
    for key, value in header.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def claim(cfg: ProjectConfig, store: Store, role: str, home: Path | None) -> dict[str, Any]:
    snapshot = inspect(cfg, store, role, home)
    if snapshot["status"] != STATUS_JOB or not snapshot["head"]:
        return snapshot
    pending = pending_rows(store, cfg.namespace, role)
    if not pending:
        return inspect(cfg, store, role, home)
    row = pending[0]
    env = None
    if row.get("envelope_json"):
        env = Envelope.model_validate(json.loads(row["envelope_json"]))
        # An agent claim is not a task claim: never overwrite an existing
        # executor task's title/objective/state from a discuss message.
        if role != "agent" or not store.get_task(cfg.namespace, env.task_id):
            store.upsert_task(
                cfg.namespace,
                env.task_id,
                issue_number=row.get("issue_number"),
                title=env.type,
                objective=row.get("body_text"),
                context_revision=env.context_revision,
            )
    directory = running_dir(cfg, home, role)
    dest = directory / f"{_logical_name(row)}.md"
    write_running_file(dest, cfg, row)
    if role != "agent":
        alert_notify(
            cfg,
            "request_claimed",
        role=role,
        type=row.get("type"),
        status="claimed",
        task_id=row.get("task_id"),
        request_id=row.get("request_id"),
        message_id=row.get("message_id"),
        issue=row.get("issue_number"),
        )
    return inspect(cfg, store, role, home)


def archive_running(cfg: ProjectConfig, home: Path | None, request_id: str | None = None, *, role: str = "executor") -> list[str]:
    directory = running_dir(cfg, home, role)
    archived: list[str] = []
    dest_dir = data_dir(cfg, home) / ("agent_discussions_archive" if role == "agent" else "running_archive")
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in list_running_md(directory):
        text = path.read_text(encoding="utf-8")
        if request_id and f"request_id: {request_id}" not in text:
            continue
        target = dest_dir / path.name
        path.replace(target)
        archived.append(str(target))
    return archived


def complete_local_claim(cfg: ProjectConfig, store: Store, home: Path | None, request_id: str) -> list[str]:
    archived = archive_running(cfg, home, request_id)
    for row in store.unprocessed_messages(cfg.namespace):
        if row.get("request_id") == request_id and row.get("type") in {
            MessageType.REQUEST.value,
            MessageType.NON_BLOCKING.value,
            MessageType.PROGRAMMED_STOP.value,
            MessageType.RESULT.value,
            MessageType.CONTROL_RESULT.value,
            MessageType.TASK_OPEN.value,
            MessageType.QUESTION.value,
            MessageType.SEND_FILE.value,
            MessageType.SEND_FILE_READY.value,
            MessageType.GET_FILE.value,
        }:
            store.mark_processed(cfg.namespace, str(row["message_id"]))
    return archived


def complete_agent_discussion(cfg: ProjectConfig, store: Store, home: Path | None, discuss_id: str) -> list[str]:
    """Retire only the answered discussion; never touch executor running/."""
    row = store.get_message_by_id(cfg.namespace, discuss_id)
    if not row or row.get("type") != MessageType.DISCUSS.value or row.get("recipient_role") != "agent":
        raise PolicyError("discuss original não encontrado no inbox do agente")
    store.mark_processed(cfg.namespace, discuss_id)
    return archive_running(cfg, home, row.get("request_id"), role="agent")


def wake_key(snapshot: dict[str, Any]) -> str:
    status = snapshot.get("status")
    material: dict[str, Any] = {
        "status": status,
        "running": snapshot.get("running"),
        "error": snapshot.get("error"),
    }
    if status != STATUS_RECOVERY:
        material["pending"] = snapshot.get("pending")
        material["head"] = snapshot.get("head")
    else:
        # Normal requests stay blocked only while a primary running file exists.
        # A terminal handback archives that file, so the next request is claimable.
        # Rearm keeps the file while the same work is still executable.
        # Side-band controls wake the executor during that window.
        material["control_pending"] = snapshot.get("control_pending")
        material["control_head"] = snapshot.get("control_head")
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_sentinel(role: str, snapshot: dict[str, Any]) -> str:
    if role == "executor":
        prompt = "Execute the pending GitHub work per INSTRUCOES_LLM_EXECUTORA.md and docs/CURSOR_CHAT_LOOP.md"
    elif role == "agent":
        prompt = "Read-only discussion per INSTRUCOES_LLM_AGENTE.md; reply analysis only; no workspace writes"
    else:
        prompt = "Evaluate pending GitHub work per INSTRUCOES_LLM_ORQUESTRADORA.md and docs/CURSOR_CHAT_LOOP.md"
    payload = {
        "prompt": prompt,
        "status": snapshot["status"],
        "payload": {
            "project": snapshot.get("project_id"),
            "repository": snapshot.get("repository"),
            "running": snapshot.get("running"),
            "head": snapshot.get("head"),
            "control_head": snapshot.get("control_head"),
            "control_pending": snapshot.get("control_pending"),
            "running_dir": snapshot.get("running_dir"),
        },
    }
    return f"{sentinel_for(role)} {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"

def tick(
    cfg: ProjectConfig,
    store: Store,
    engine: Engine | None,
    role: str,
    home: Path | None,
    *,
    do_claim: bool = True,
) -> dict[str, Any]:
    error = None
    try:
        if engine is not None:
            engine.sync()
    except (AuthError, NetworkError, PolicyError) as exc:
        error = str(exc)
    if error:
        snapshot: dict[str, Any] = {
            "status": STATUS_GIT_ERROR,
            "project_id": cfg.project_id,
            "repository": cfg.resolved_repo_label(),
            "role": role,
            "running_dir": str(running_dir(cfg, home, role)),
            "running": [p.name for p in list_running_md(running_dir(cfg, home, role))],
            "pending": [],
            "head": None,
            "error": error,
            "claimed": False,
            "wake_status": STATUS_GIT_ERROR,
        }
    else:
        snapshot = inspect(cfg, store, role, home)
        claimed = False
        head_type = (snapshot.get("head") or {}).get("type")
        if (
            do_claim
            and snapshot["status"] == STATUS_JOB
            and snapshot.get("head")
            and not (role == "executor" and head_type in RECOVERY_CONTROL_TYPES)
        ):
            snapshot = claim(cfg, store, role, home)
            claimed = True
        if claimed:
            snapshot["claimed"] = True
            snapshot["wake_status"] = STATUS_JOB
            if role == "executor" and engine is not None:
                try:
                    head = snapshot.get("head") or {}
                    task_id = head.get("task_id")
                    request_id = head.get("request_id")
                    if task_id and request_id:
                        task = engine.store.get_task(cfg.namespace, str(task_id)) or {
                            "task_id": task_id,
                            "issue_number": head.get("issue_number") or head.get("issue"),
                        }
                        if not task.get("issue_number"):
                            task["issue_number"] = head.get("issue_number") or head.get("issue")
                        engine.announce_request_claimed(
                            task,
                            request_id=str(request_id),
                            in_reply_to=head.get("message_id"),
                            issue=task.get("issue_number"),
                            discord=False,
                        )
                        engine.flush_outbox()
                except Exception:  # noqa: BLE001 — claim local já ocorreu; GitHub é best-effort
                    pass
        else:
            snapshot["claimed"] = False
            snapshot["wake_status"] = snapshot["status"]
    key = wake_key(snapshot)
    last_file = last_wake_path(cfg, home, role)
    previous = last_file.read_text(encoding="utf-8").strip() if last_file.is_file() else ""
    changed = key != previous
    last_file.write_text(key + "\n", encoding="utf-8")
    emit_sentinel = changed and snapshot["status"] != STATUS_IDLE
    snapshot["wake_key"] = key
    snapshot["changed"] = changed
    snapshot["wake"] = emit_sentinel
    if changed and snapshot["status"] == STATUS_GIT_ERROR:
        alert_notify(cfg, "git_error", role=role, reason=snapshot.get("error"))
    if emit_sentinel:
        sentinel_snap = dict(snapshot)
        sentinel_snap["status"] = snapshot.get("wake_status") or snapshot["status"]
        snapshot["sentinel"] = build_sentinel(role, sentinel_snap)
    else:
        snapshot["sentinel"] = None
    return snapshot


def loop_script_path() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "examples" / "cursor_chat_loop.sh",
        here.parent / "scripts" / "cursor_chat_loop.sh",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def arm_plan(cfg: ProjectConfig, role: str, home: Path | None) -> dict[str, Any]:
    interval = cfg.loop.interval_seconds
    resolved_home = home or default_home()
    script = loop_script_path()
    pid = pid_path(cfg, resolved_home, role)
    env = {
        "IA_ORCHESTRATOR_HOME": str(resolved_home),
        "IA_ORCHESTRATOR_PROJECT": cfg.project_id,
        "IA_ORCHESTRATOR_ROLE": role,
        "IA_ORCHESTRATOR_POLL_SECONDS": str(interval),
        "IA_ORCHESTRATOR_PID_FILE": str(pid),
    }
    if script is not None:
        command = ["bash", str(script)]
    else:
        command = [
            "bash",
            "-c",
            'python3 -m ia_orchestrator.keep_awake & awake_pid=$!; '
            'trap \'kill "$awake_pid" 2>/dev/null || true\' EXIT; '
            'ia-orchestrator --home "$IA_ORCHESTRATOR_HOME" loop tick --project "$IA_ORCHESTRATOR_PROJECT" --role "$IA_ORCHESTRATOR_ROLE" --claim --reset-wake || true; '
            'while true; do sleep "${IA_ORCHESTRATOR_POLL_SECONDS:-10}"; '
            'ia-orchestrator --home "$IA_ORCHESTRATOR_HOME" loop tick --project "$IA_ORCHESTRATOR_PROJECT" --role "$IA_ORCHESTRATOR_ROLE" --claim || true; done',
        ]
    return {
        "project_id": cfg.project_id,
        "repository": cfg.resolved_repo_label(),
        "role": role,
        "interval_seconds": interval,
        "sentinel": sentinel_for(role),
        "notify_on_output": {"pattern": sentinel_for(role), "reason": f"{role} job wake"},
        "block_until_ms": 0,
        "pid_file": str(pid),
        "running_dir": str(running_dir(cfg, resolved_home, role)),
        "command": command,
        "environment": env,
        "note": "Arranque este comando neste chat com block_until_ms=0 e notify_on_output no sentinela. O bash não executa o job. O monitor lança keep_awake num processo à parte e termina-o ao sair.",
    }
