"""CLI ia-orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Sequence

from ia_orchestrator import PROTOCOL_VERSION, SOFTWARE_NAME, __version__
from ia_orchestrator.config import (
    ProjectConfig,
    data_dir,
    db_path,
    default_home,
    example_config_dict,
    load_registry,
    resolve_project,
    save_registry,
    save_yaml,
)
from ia_orchestrator.demo import run_offline_demo
from ia_orchestrator.doctor import doctor_report
from ia_orchestrator.errors import OrchestratorError, UsageError
from ia_orchestrator.persistence import Store
from ia_orchestrator.issue_status import STATUS_PREFIX, STATUS_RUNNING
from ia_orchestrator.protocol import (
    RECOVERY_CONTROL_TYPES,
    MessageType,
    build_envelope,
    new_id,
    render_message,
    status_telemetry_body,
    utc_now,
)
from ia_orchestrator.transport import GitHubTransport, MemoryTransport
from ia_orchestrator.workers import Engine, run_worker


EXIT_HELP = {
    0: "sucesso",
    1: "erro genérico",
    2: "uso incorrecto",
    3: "autenticação",
    4: "não encontrado",
    5: "lock",
    6: "protocolo",
    7: "política",
    8: "rede",
    9: "limite",
}


def _home(ns: argparse.Namespace) -> Path:
    if getattr(ns, "home", None):
        return Path(ns.home).expanduser().resolve()
    return default_home()


def _json_mode(ns: argparse.Namespace) -> bool:
    return bool(getattr(ns, "json", False))


def emit(ns: argparse.Namespace, payload: Any, *, text: str | None = None) -> None:
    if _json_mode(ns):
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    elif text is not None:
        print(text)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def announce_repo(cfg: ProjectConfig, action: str) -> None:
    print(f"Repositório resolvido: {cfg.resolved_repo_label()} (project_id={cfg.project_id}) — {action}", file=sys.stderr)


def build_transport(cfg: ProjectConfig, *, memory: MemoryTransport | None = None) -> GitHubTransport | MemoryTransport:
    if memory is not None:
        return memory
    return GitHubTransport(
        host=cfg.github.host,
        repository=cfg.github.repository,
        token=cfg.token(),
        api_base=cfg.github.resolved_api_base(),
        timeout=30.0,
        max_backoff=cfg.polling.max_backoff_seconds,
    )


def cmd_project_add(ns: argparse.Namespace) -> int:
    home = _home(ns)
    home.mkdir(parents=True, exist_ok=True)
    if not ns.repo or "/" not in ns.repo:
        raise UsageError("--repo owner/repo é obrigatório")
    if not ns.workspace:
        raise UsageError("--workspace é obrigatório")
    cfg_dict = example_config_dict(ns.project, ns.repo, ns.workspace, host=ns.host)
    if ns.token_env:
        cfg_dict["github"]["token_env"] = ns.token_env
    config_path = home / "projects" / ns.project / "config.yaml"
    if config_path.exists() and not ns.force:
        raise UsageError(f"config já existe: {config_path} (use --force)")
    save_yaml(config_path, cfg_dict)
    registry = load_registry(home)
    registry.projects[ns.project] = str(config_path)
    save_registry(registry, home)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, "cadastro (nenhum recurso remoto modificado)")
    emit(
        ns,
        {
            "project_id": ns.project,
            "repository": cfg.resolved_repo_label(),
            "config": str(config_path),
            "home": str(home),
        },
        text=(
            f"Projecto cadastrado: {ns.project}\n"
            f"Repositório: {cfg.resolved_repo_label()}\n"
            f"Config: {config_path}\n"
            f"Workers NÃO foram iniciados. Preencha allowed_senders e credenciais, depois: ia-orchestrator doctor --project {ns.project}"
        ),
    )
    return 0


def cmd_project_list(ns: argparse.Namespace) -> int:
    home = _home(ns)
    registry = load_registry(home)
    rows = []
    for pid, path in registry.projects.items():
        try:
            cfg = resolve_project(pid, home)
            rows.append({"project_id": pid, "repository": cfg.resolved_repo_label(), "config": path})
        except Exception as exc:  # noqa: BLE001
            rows.append({"project_id": pid, "error": str(exc), "config": path})
    emit(ns, {"home": str(home), "projects": rows}, text="\n".join(f"{r.get('project_id')}\t{r.get('repository', r.get('error'))}" for r in rows) or "(nenhum)")
    return 0


def cmd_project_show(ns: argparse.Namespace) -> int:
    cfg = resolve_project(ns.project, _home(ns))
    announce_repo(cfg, "consulta")
    dump = json.loads(cfg.model_dump_json())
    dump.pop("source_path", None)
    emit(ns, dump)
    return 0


def cmd_bootstrap(ns: argparse.Namespace) -> int:
    code = cmd_project_add(ns)
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    guide = f"""# Activação do projecto {cfg.project_id}

Repositório de comunicação: {cfg.resolved_repo_label()}
Este guia não liga serviços persistentes.

1. Exporte o token: export {cfg.github.token_env}=...
2. Ajuste allowed_senders em {cfg.source_path}
3. ia-orchestrator doctor --project {cfg.project_id} --probe
4. Foreground (modo headless; NÃO use se executor.mode=cursor_chat):
   ia-orchestrator worker run --project {cfg.project_id} --role orchestrator
   ia-orchestrator worker run --project {cfg.project_id} --role executor
5. Chat aberto Cursor: executor.mode/orchestrator.mode cursor_chat, depois
   ia-orchestrator loop arm --project {cfg.project_id} --role executor
   (o poller acorda este chat; ver docs/CURSOR_CHAT_LOOP.md)
6. Análise em paralelo (outro chat): configurar github.allowed_senders.agent,
   instalar regras examples/cursor/agent.mdc no chat do agente, depois
   ia-orchestrator loop arm --project {cfg.project_id} --role agent.
   O agente não é outro executor e worker run --role agent só sincroniza.
7. Exemplos launchd/systemd em examples/macos e examples/linux (instalação manual).

Software {SOFTWARE_NAME} {__version__}, protocolo v{PROTOCOL_VERSION}.
"""
    guide_path = home / "projects" / ns.project / "ACTIVACAO.md"
    guide_path.write_text(guide, encoding="utf-8")
    print(guide)
    return code


def cmd_doctor(ns: argparse.Namespace) -> int:
    cfg = resolve_project(ns.project, _home(ns))
    announce_repo(cfg, "diagnóstico")
    transport = None
    if ns.probe:
        transport = build_transport(cfg)
    report = doctor_report(cfg, transport, _home(ns), probe_github=bool(ns.probe))
    emit(ns, report)
    return 0 if report["ok"] else 1


def cmd_task_create(ns: argparse.Namespace) -> int:
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, "criar issue/tarefa" + (" [dry-run]" if ns.dry_run else ""))
    prompt = Path(ns.prompt_file).read_text(encoding="utf-8")
    task_id = ns.task_id or new_id()
    sender_role = ns.sender_role or "orchestrator"
    if sender_role == "human":
        sender_id = ns.sender_id or (cfg.github.allowed_senders.human[0] if cfg.github.allowed_senders.human else "human")
        recipient = "orchestrator"
        open_type = MessageType.TASK_OPEN.value
    else:
        sender_id = ns.sender_id or cfg.orchestrator.worker_id
        recipient = "executor"
        open_type = MessageType.TASK_OPEN.value
    env = build_envelope(
        project_id=cfg.project_id,
        repository=cfg.github.repository,
        task_id=task_id,
        sender_role=sender_role,
        sender_id=sender_id,
        recipient_role=recipient,
        type=open_type,
        body=prompt,
        context_revision=None,
    )
    rendered = render_message(env, prompt)
    if ns.dry_run:
        emit(ns, {"dry_run": True, "task_id": task_id, "repository": cfg.resolved_repo_label(), "body": rendered})
        return 0
    transport = build_transport(cfg)
    issue = transport.create_issue(ns.title or Path(ns.prompt_file).name, rendered, labels=["ia-orchestrator", f"project:{cfg.project_id}"])
    transport.create_comment(issue.number, rendered)
    store = Store(db_path(cfg, home))
    store.upsert_task(cfg.namespace, task_id, issue_number=issue.number, github_issue_id=issue.id, title=issue.title, objective=prompt)
    store.audit(cfg.namespace, "task_created", task_id, {"issue": issue.number, "html_url": issue.html_url, "sender_role": sender_role})
    dispatched = None
    if ns.dispatch:
        engine = Engine(cfg, store, transport, "orchestrator", dry_run=False)
        req = engine._publish(store.get_task(cfg.namespace, task_id), MessageType.REQUEST.value, prompt, recipient="executor")
        engine.flush_outbox()
        dispatched = req.message_id
    emit(
        ns,
        {
            "task_id": task_id,
            "issue": issue.number,
            "html_url": issue.html_url,
            "repository": cfg.resolved_repo_label(),
            "request_message_id": dispatched,
        },
        text=f"Tarefa {task_id}\nIssue #{issue.number} {issue.html_url}"
        + (f"\nRequest {dispatched}" if dispatched else ""),
    )
    return 0


def cmd_task_list(ns: argparse.Namespace) -> int:
    cfg = resolve_project(ns.project, _home(ns))
    store = Store(db_path(cfg, _home(ns)))
    tasks = store.list_tasks(cfg.namespace)
    emit(ns, {"repository": cfg.resolved_repo_label(), "tasks": tasks}, text="\n".join(f"{t['task_id']}\t{t['state']}\tissue={t.get('issue_number')}" for t in tasks) or "(nenhuma)")
    return 0


def cmd_task_show(ns: argparse.Namespace) -> int:
    cfg = resolve_project(ns.project, _home(ns))
    store = Store(db_path(cfg, _home(ns)))
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada neste projecto/repositório")
    msgs = store.messages_for_task(cfg.namespace, ns.task)
    emit(ns, {"repository": cfg.resolved_repo_label(), "task": task, "messages": msgs})
    return 0


def _control(ns: argparse.Namespace, type_: str, body: str) -> int:
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"{type_} tarefa {ns.task}" + (" [dry-run]" if ns.dry_run else ""))
    store = Store(db_path(cfg, home))
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, "orchestrator", dry_run=ns.dry_run)
    env = engine._publish(task, type_, body, recipient="broadcast")
    engine.flush_outbox()
    emit(ns, {"message_id": env.message_id, "type": type_, "task_id": ns.task, "dry_run": ns.dry_run})
    return 0


def cmd_task_pause(ns: argparse.Namespace) -> int:
    return _control(ns, MessageType.PAUSE.value, f"## Pausa\n{ns.reason}\n")


def cmd_task_resume(ns: argparse.Namespace) -> int:
    return _control(ns, MessageType.RESUME.value, "## Retoma\nRetoma autorizada.\n")


def cmd_task_cancel(ns: argparse.Namespace) -> int:
    return _control(ns, MessageType.CANCEL.value, f"## Cancelamento\n{ns.reason}\n")


def cmd_task_export(ns: argparse.Namespace) -> int:
    cfg = resolve_project(ns.project, _home(ns))
    store = Store(db_path(cfg, _home(ns)))
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")
    msgs = store.messages_for_task(cfg.namespace, ns.task)
    lines = [
        f"# Tarefa {ns.task}",
        f"Repositório: {cfg.resolved_repo_label()}",
        f"Estado: {task['state']}",
        f"Issue: {task.get('issue_number')}",
        "",
    ]
    for m in msgs:
        lines.append(f"## {m.get('type')} ({m.get('message_id')})")
        lines.append(f"remetente: {m.get('sender_role')} / {m.get('github_login')}")
        lines.append(m.get("body_text") or "")
        lines.append("")
    text = "\n".join(lines)
    Path(ns.output).write_text(text, encoding="utf-8")
    emit(ns, {"output": ns.output, "messages": len(msgs)}, text=f"Exportado {ns.output}")
    return 0


def cmd_worker_run(ns: argparse.Namespace) -> int:
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"worker {ns.role}" + (" --once" if ns.once else "") + (" [dry-run]" if ns.dry_run else ""))
    if ns.role == "agent" or (ns.role == "executor" and cfg.executor.mode == "cursor_chat") or (
        ns.role == "orchestrator" and cfg.orchestrator.mode == "cursor_chat"
    ):
        print(
            "aviso: mode=cursor_chat — worker run só sincroniza; não executa o job. Use loop tick/arm neste chat.",
            file=sys.stderr,
        )
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    awake = None
    if not ns.once:
        from ia_orchestrator.keep_awake import spawn, stop_process

        awake = spawn()
    try:
        ticks = run_worker(cfg, store, transport, ns.role, once=ns.once, dry_run=ns.dry_run, home=home)
    finally:
        if awake is not None:
            stop_process(awake)
    emit(ns, {"ticks": ticks, "repository": cfg.resolved_repo_label()})
    return 0


def cmd_pending(ns: argparse.Namespace) -> int:
    cfg = resolve_project(ns.project, _home(ns))
    store = Store(db_path(cfg, _home(ns)))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, ns.role)
    engine.sync()
    from ia_orchestrator.loop import pending_rows

    pending = pending_rows(store, cfg.namespace, ns.role, cfg)
    emit(ns, {"repository": cfg.resolved_repo_label(), "pending": pending}, text="\n".join(f"{p.get('type')}\t{p.get('task_id')}\t{p.get('request_id')}" for p in pending) or "(nada pendente)")
    return 0




def cmd_check(ns: argparse.Namespace) -> int:
    """Sincroniza e inspeciona passivamente uma tarefa sem publicar controle."""
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, "check passivo da execução")
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, "orchestrator", home=home)
    engine.sync()
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")

    issue = transport.get_issue(int(task["issue_number"])) if task.get("issue_number") else None
    messages = store.messages_for_task(cfg.namespace, ns.task)
    relevant_types = {
        MessageType.ACK.value,
        MessageType.PROGRESS.value,
        MessageType.QUESTION.value,
        MessageType.RESULT.value,
        MessageType.CONTROL_RESULT.value,
        MessageType.ERROR.value,
    }
    relevant = [row for row in messages if row.get("type") in relevant_types]
    latest = relevant[-20:]
    payload = {
        "checked_at": utc_now(),
        "task_id": task["task_id"],
        "task_state": task["state"],
        "active_request_id": task.get("active_request_id"),
        "issue_number": task.get("issue_number"),
        "issue_state": issue.state if issue else None,
        "issue_labels": issue.labels if issue else [],
        "messages": [
            {
                "type": row.get("type"),
                "request_id": row.get("request_id"),
                "message_id": row.get("message_id"),
                "observed_at": row.get("observed_at"),
                "body": row.get("body_text"),
            }
            for row in latest
        ],
    }
    emit(
        ns,
        payload,
        text=(
            f"Check task={task['task_id']} state={task['state']} "
            f"issue=#{task.get('issue_number')} mensagens_relevantes={len(latest)}"
        ),
    )
    return 0


def request_execution_status(
    cfg: ProjectConfig,
    store: Store,
    transport: GitHubTransport | MemoryTransport,
    task_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publica o non_blocking padronizado de telemetria se a execução primária está activa."""
    engine = Engine(cfg, store, transport, "orchestrator", dry_run=dry_run)
    engine.sync()
    task = store.get_task(cfg.namespace, task_id)
    if not task:
        raise UsageError("tarefa não encontrada")
    issue_number = task.get("issue_number")
    if not issue_number:
        raise UsageError("tarefa sem issue; nada foi publicado")
    issue = transport.get_issue(int(issue_number))
    running_label = f"{STATUS_PREFIX}{STATUS_RUNNING}"
    if running_label not in (issue.labels or []):
        raise UsageError(
            f"não há execução primária activa (label {running_label} ausente); nada foi publicado"
        )
    in_reply_to = None
    for row in store.messages_for_task(cfg.namespace, task_id):
        if row.get("type") == MessageType.REQUEST.value:
            in_reply_to = row.get("message_id")
    request_id = new_id()
    env = engine._publish(
        task,
        MessageType.NON_BLOCKING.value,
        status_telemetry_body(),
        recipient="executor",
        request_id=request_id,
        in_reply_to=in_reply_to,
        sender_role="orchestrator",
    )
    published = engine.flush_outbox()
    return {
        "published": (not dry_run) and published > 0,
        "dry_run": dry_run,
        "type": MessageType.NON_BLOCKING.value,
        "task_id": task_id,
        "request_id": request_id,
        "message_id": env.message_id,
        "in_reply_to": in_reply_to,
        "issue_number": int(issue_number),
    }


def cmd_status(ns: argparse.Namespace) -> int:
    """Pede telemetria da execução activa com um non_blocking de corpo fixo."""
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, "status da execução" + (" [dry-run]" if ns.dry_run else ""))
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    payload = request_execution_status(cfg, store, transport, ns.task, dry_run=ns.dry_run)
    emit(
        ns,
        payload,
        text=(
            f"status task={payload['task_id']} request_id={payload['request_id']} "
            f"message_id={payload['message_id']} published={payload['published']}"
        ),
    )
    return 0


def cmd_execution_start(ns: argparse.Namespace) -> int:
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, "registar início da execução")
    store = Store(db_path(cfg, home))
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")
    idem = f"{cfg.namespace}:{ns.request}:{ns.attempt}"
    store.start_execution(
        cfg.namespace,
        idempotency_key=idem,
        request_id=ns.request,
        task_id=ns.task,
        attempt=ns.attempt,
        input_json={"manual": True, "cursor_chat": True},
    )
    store.finish_execution(cfg.namespace, idem, "RUNNING")
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, "executor")
    in_reply_to = None
    req = store.get_request(cfg.namespace, ns.request)
    if req and req.get("message_id"):
        in_reply_to = req["message_id"]
    else:
        for row in store.messages_for_task(cfg.namespace, ns.task):
            if row.get("type") in ({MessageType.REQUEST.value} | RECOVERY_CONTROL_TYPES) and row.get("request_id") == ns.request:
                in_reply_to = row.get("message_id")
                break
    engine.announce_execution_started(
        task,
        request_id=ns.request,
        in_reply_to=in_reply_to,
        issue=task.get("issue_number"),
    )
    engine.flush_outbox()
    emit(ns, {"idempotency_key": idem, "status": "RUNNING", "issue": task.get("issue_number")})
    return 0


def cmd_execution_deliver(ns: argparse.Namespace) -> int:
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, "entregar resultado manual" + (" [dry-run]" if ns.dry_run else ""))
    store = Store(db_path(cfg, home))
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")
    output = json.loads(Path(ns.result_file).read_text(encoding="utf-8"))
    idem = f"{cfg.namespace}:{ns.request}:{ns.attempt}"
    status_map = {"success": "SUCCEEDED", "failed": "FAILED", "blocked": "BLOCKED", "unknown": "UNKNOWN"}
    store.finish_execution(cfg.namespace, idem, status_map.get(output.get("status"), "UNKNOWN"), output=output)
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, "executor", dry_run=ns.dry_run)
    in_reply_to = None
    origin_type = None
    req = store.get_request(cfg.namespace, ns.request)
    if req and req.get("message_id"):
        in_reply_to = req["message_id"]
        original = store.get_message_by_id(cfg.namespace, req["message_id"])
        origin_type = (original or {}).get("type")
    else:
        for row in store.messages_for_task(cfg.namespace, ns.task):
            if row.get("type") in ({MessageType.REQUEST.value} | RECOVERY_CONTROL_TYPES) and row.get("request_id") == ns.request:
                in_reply_to = row.get("message_id")
                origin_type = row.get("type")
                break
    is_control = origin_type in RECOVERY_CONTROL_TYPES
    heading = "## Resultado de controle (manual)" if is_control else "## Resultado (manual)"
    body = f"{heading}\n```json\n{json.dumps(output, indent=2, ensure_ascii=False)}\n```\n"
    engine._publish(
        task,
        MessageType.CONTROL_RESULT.value if is_control else MessageType.RESULT.value,
        body,
        recipient="orchestrator",
        request_id=ns.request,
        in_reply_to=in_reply_to,
    )
    if not is_control:
        engine.set_issue_status(task.get("issue_number"), "waiting-orchestrator")
        from ia_orchestrator.state import decision_block

        if decision_block(output):
            store.release_request(cfg.namespace, ns.request)
        if output.get("status") == "success" and not ns.dry_run:
            from ia_orchestrator.publish import publish_authorized_commits

            store.audit(
                cfg.namespace,
                "authorized_push",
                ns.task,
                publish_authorized_commits(cfg.workspace_root(), allow_push=cfg.policy.allow_push),
            )
    engine.flush_outbox()
    from ia_orchestrator.loop import complete_local_claim

    archived = complete_local_claim(cfg, store, home, ns.request)
    emit(ns, {"delivered": True, "dry_run": ns.dry_run, "archived_running": archived})
    return 0


def cmd_message_post(ns: argparse.Namespace) -> int:
    # A discussion does not dispatch, and an agent cannot masquerade as executor.
    role = ns.sender_role
    if ns.type == MessageType.DISCUSS.value and (role, ns.recipient) != ("orchestrator", "agent"):
        raise UsageError("discuss exige sender-role orchestrator e recipient agent")
    if ns.type == MessageType.ANALYSIS.value and (role, ns.recipient) != ("agent", "orchestrator"):
        raise UsageError("analysis exige sender-role agent e recipient orchestrator")
    if role == "agent" and not (
        ns.type in {MessageType.ANALYSIS.value, MessageType.QUESTION.value}
        and ns.recipient == "orchestrator"
    ):
        raise UsageError("agente só pode enviar analysis/question à orquestradora")
    if ns.recipient == "agent" and ns.type != MessageType.DISCUSS.value:
        raise UsageError("agente só recebe discuss")
    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"publicar {ns.type}" + (" [dry-run]" if ns.dry_run else ""))
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, role if role in {"orchestrator", "executor", "agent"} else "orchestrator", dry_run=ns.dry_run, home=home)
    engine.sync()
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")
    body = Path(ns.body_file).read_text(encoding="utf-8") if ns.body_file else ns.body or ""
    if ns.type == MessageType.DISCUSS.value and "execução: não ordenar e não executar" not in body:
        raise UsageError("discuss precisa declarar: execução: não ordenar e não executar")
    if role == "agent":
        reference = store.get_message_by_id(cfg.namespace, ns.in_reply_to or "")
        if not reference or reference.get("type") != MessageType.DISCUSS.value:
            raise UsageError("analysis/question exige discuss válido em in-reply-to")
        if reference.get("request_id") != ns.request_id or reference.get("task_id") != ns.task:
            raise UsageError("agent request_id/task_id precisam coincidir com discuss original")
        if ns.type == MessageType.ANALYSIS.value and (
            "## Parecer" not in body or "efeito_na_executora: nenhum" not in body
        ):
            raise UsageError("analysis exige ## Parecer e efeito_na_executora: nenhum")
    env = engine._publish(
        task,
        ns.type,
        body,
        recipient=ns.recipient,
        request_id=ns.request_id,
        in_reply_to=ns.in_reply_to,
    )
    engine.flush_outbox()
    if (
        role == "executor"
        and not ns.dry_run
        and ns.request_id
        and ns.type in {MessageType.QUESTION.value, MessageType.RESULT.value, MessageType.ERROR.value}
    ):
        from ia_orchestrator.loop import complete_local_claim

        complete_local_claim(cfg, store, home, ns.request_id)
        engine.set_issue_status(task.get("issue_number"), "waiting-orchestrator")
    if role == "agent" and not ns.dry_run:
        outbox = store.get_outbox(cfg.namespace, env.message_id)
        if not outbox or outbox.get("status") != "PUBLISHED":
            raise UsageError("parecer não publicado; discuss permanece pendente para retry")
        from ia_orchestrator.loop import complete_agent_discussion
        complete_agent_discussion(cfg, store, home, ns.in_reply_to)
    emit(ns, {"message_id": env.message_id, "type": ns.type, "dry_run": ns.dry_run})
    return 0


def cmd_outbox_reconcile(ns: argparse.Namespace) -> int:
    cfg = resolve_project(ns.project, _home(ns))
    announce_repo(cfg, "reconciliar outbox")
    store = Store(db_path(cfg, _home(ns)))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, ns.role, dry_run=ns.dry_run)
    n = engine.flush_outbox()
    emit(ns, {"published_or_reconciled": n, "dry_run": ns.dry_run})
    return 0


def cmd_demo(ns: argparse.Namespace) -> int:
    root = Path(ns.output).expanduser() if ns.output else Path.cwd() / "ia-orchestrator-demo"
    result = run_offline_demo(root)
    emit(ns, result, text=f"Demo offline: estado={result['state']} issue=#{result['issue']} comentários={result['comments']}\nTipos: {result['types']}\nPasta: {result['root']}")
    return 0 if result.get("state") == "COMPLETED" else 1


def cmd_loop_inspect(ns: argparse.Namespace) -> int:
    from ia_orchestrator.loop import inspect as loop_inspect

    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"loop inspect {ns.role}")
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, ns.role, home=home)
    engine.sync()
    snapshot = loop_inspect(cfg, store, ns.role, home)
    emit(ns, snapshot)
    return 0


def cmd_loop_tick(ns: argparse.Namespace) -> int:
    from ia_orchestrator.loop import last_wake_path, tick as loop_tick

    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, ns.role, home=home)
    if ns.reset_wake:
        last_wake_path(cfg, home, ns.role).unlink(missing_ok=True)
    snapshot = loop_tick(cfg, store, engine, ns.role, home, do_claim=ns.claim)
    if _json_mode(ns):
        emit(ns, snapshot)
        if snapshot.get("sentinel"):
            print(snapshot["sentinel"], file=sys.stderr)
        return 0
    if snapshot.get("sentinel"):
        print(snapshot["sentinel"])
    elif snapshot["status"] == "IDLE" and snapshot.get("changed"):
        print(f"back_to_idle {utc_now()}")
    else:
        print(f"idle {utc_now()} status={snapshot['status']}")
    return 0


def cmd_loop_rearm(ns: argparse.Namespace) -> int:
    from ia_orchestrator.loop import rearm_next_wake

    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"loop rearm {ns.role}")
    snapshot = rearm_next_wake(cfg, home, ns.role)
    emit(
        ns,
        snapshot,
        text=(
            f"rearmed role={ns.role}; o próximo tick do poller pode reemitir "
            "o sentinela para o job RECOVERY_REQUIRED."
        ),
    )
    return 0


def _add_send_file_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", required=True, choices=["orchestrator", "executor"])
    parser.add_argument("--task", help="obrigatório para transferir; omisso só ao gravar a pasta")
    parser.add_argument("--file", help="arquivo local; obrigatório para publicar a transferência")
    parser.add_argument("--request", help="request_id do send_file; obrigatório para o executor")
    parser.add_argument("--name", help="nome do arquivo dentro de transfered_files")
    parser.add_argument("--folder-link", help="link público da pasta compartilhada do Google Drive")
    parser.add_argument("--drive-url", help="link público do arquivo já colocado nessa pasta")
    parser.add_argument("--push", action="store_true", help="commit e push só do arquivo recebido; omissão = false")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--wait", action="store_true", help="orquestrador: espera o result da executora")
    parser.add_argument("--timeout", type=int, default=960)
    parser.set_defaults(func=cmd_send_file)


def cmd_send_file(ns: argparse.Namespace) -> int:
    from ia_orchestrator.protocol import Envelope
    from ia_orchestrator.send_file import (
        establish_public_folder,
        load_folder,
        orchestrator_send_file,
        perform_executor_send_file,
        publish_orchestrator_send_file,
        wait_executor_result,
    )

    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"send-file role={ns.role}")
    if ns.role == "orchestrator" and ns.folder_link and not ns.file:
        record = establish_public_folder(cfg, home, ns.folder_link)
        emit(ns, record, text=f"pasta pública gravada: {record['folder_url']}")
        return 0
    if not ns.task:
        raise UsageError("send-file exige --task")
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, ns.role, home=home)
    engine.sync()
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")
    if ns.role == "executor":
        if not ns.request:
            raise UsageError("executor exige --request")
        row = None
        for candidate in store.messages_for_task(cfg.namespace, ns.task):
            if candidate.get("type") == MessageType.SEND_FILE.value and candidate.get("request_id") == ns.request:
                row = candidate
                break
        if row is None or not row.get("envelope_json"):
            raise UsageError("send_file não encontrado para este request")
        env = Envelope.model_validate(json.loads(row["envelope_json"]))
        outcome = perform_executor_send_file(engine, home, env, row.get("body_text") or "")
        emit(ns, outcome)
        return 0 if outcome.get("status") == "success" else 1
    if not ns.file:
        raise UsageError("orquestrador exige --file ou --folder-link")
    if not ns.drive_url:
        raise UsageError("orquestrador exige --drive-url do arquivo já colocado na pasta")
    if ns.folder_link:
        folder = establish_public_folder(cfg, home, ns.folder_link)
    else:
        folder = load_folder(cfg, home)
    if folder is None:
        raise UsageError("defina antes o link público da pasta com --folder-link")
    prepared = orchestrator_send_file(
        file_path=Path(ns.file).expanduser(),
        name=ns.name,
        folder_url=folder["folder_url"],
        drive_url=ns.drive_url,
        push=bool(ns.push),
        overwrite=bool(ns.overwrite),
    )
    env = publish_orchestrator_send_file(engine, task, prepared["spec"])
    payload: dict[str, Any] = {
        "request_id": env.request_id,
        "message_id": env.message_id,
        "destination": prepared["spec"]["destination"],
        "sha256": prepared["spec"]["sha256"],
        "bytes": prepared["spec"]["bytes"],
        "folder_url": prepared["spec"]["folder_url"],
        "drive_url": prepared["spec"]["drive_url"],
        "push": prepared["spec"]["push"],
    }
    if ns.wait:
        payload.update(
            wait_executor_result(
                engine,
                task_id=ns.task,
                request_id=str(env.request_id),
                timeout=float(ns.timeout),
            )
        )
    emit(
        ns,
        payload,
        text=(
            f"send_file request_id={payload['request_id']} destino={payload['destination']} "
            f"sha256={payload['sha256']} push={payload['push']} drive={payload['drive_url']}"
        ),
    )
    if ns.wait and (payload.get("result") or {}).get("status") not in {None, "success"}:
        return 1
    return 0


def _add_get_file_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", required=True, choices=["orchestrator", "executor"])
    parser.add_argument("--task", help="obrigatório para pedir ou receber")
    parser.add_argument("--request", help="request_id do get_file; obrigatório para o executor")
    parser.add_argument("--url", help="URL https do arquivo; obrigatório para a orquestradora pedir")
    parser.add_argument("--name", help="nome do arquivo na pasta pública")
    parser.add_argument("--sha256", help="hash esperado, se a orquestradora já o conhece")
    parser.add_argument("--folder-link", help="link público da pasta compartilhada do Google Drive")
    parser.add_argument("--output", help="destino local depois do --wait; omissão grava em dados do projeto")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--wait", action="store_true", help="orquestrador: espera o result, baixa e apaga no Drive")
    parser.add_argument("--timeout", type=int, default=960)
    parser.set_defaults(func=cmd_get_file)


def cmd_get_file(ns: argparse.Namespace) -> int:
    from ia_orchestrator.get_file import (
        build_request,
        collect_received_file,
        incoming_path,
        perform_executor_get_file,
        publish_orchestrator_get_file,
    )
    from ia_orchestrator.protocol import Envelope
    from ia_orchestrator.send_file import establish_public_folder, load_folder, wait_executor_result

    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"get-file role={ns.role}")
    if ns.role == "orchestrator" and ns.folder_link and not ns.url:
        record = establish_public_folder(cfg, home, ns.folder_link)
        emit(ns, record, text=f"pasta pública gravada: {record['folder_url']}")
        return 0
    if not ns.task:
        raise UsageError("get-file exige --task")
    store = Store(db_path(cfg, home))
    transport = build_transport(cfg)
    engine = Engine(cfg, store, transport, ns.role, home=home)
    engine.sync()
    task = store.get_task(cfg.namespace, ns.task)
    if not task:
        raise UsageError("tarefa não encontrada")
    if ns.role == "executor":
        if not ns.request:
            raise UsageError("executor exige --request")
        row = None
        for candidate in store.messages_for_task(cfg.namespace, ns.task):
            if candidate.get("type") == MessageType.GET_FILE.value and candidate.get("request_id") == ns.request:
                row = candidate
                break
        if row is None or not row.get("envelope_json"):
            raise UsageError("get_file não encontrado para este request")
        env = Envelope.model_validate(json.loads(row["envelope_json"]))
        outcome = perform_executor_get_file(engine, home, env, row.get("body_text") or "")
        emit(ns, outcome)
        return 0 if outcome.get("status") == "success" else 1
    if not ns.url:
        raise UsageError("orquestrador exige --url ou --folder-link")
    if ns.folder_link:
        folder = establish_public_folder(cfg, home, ns.folder_link)
    else:
        folder = load_folder(cfg, home)
    if folder is None:
        raise UsageError("defina antes o link público da pasta com --folder-link")
    spec = build_request(
        source_url=ns.url,
        folder_url=folder["folder_url"],
        filename=ns.name,
        sha256=ns.sha256,
    )
    env = publish_orchestrator_get_file(engine, task, spec)
    payload: dict[str, Any] = {
        "request_id": env.request_id,
        "message_id": env.message_id,
        "filename": spec["filename"],
        "source_url": spec["source_url"],
        "folder_url": spec["folder_url"],
    }
    if ns.wait:
        waited = wait_executor_result(
            engine,
            task_id=ns.task,
            request_id=str(env.request_id),
            timeout=float(ns.timeout),
        )
        payload.update(waited)
        result = waited["result"]
        if result.get("status") == "success":
            output = Path(ns.output).expanduser() if ns.output else incoming_path(cfg, home, str(result["filename"]))
            payload["collected"] = collect_received_file(result, output, overwrite=bool(ns.overwrite))
    emit(
        ns,
        payload,
        text=(
            f"get_file request_id={payload['request_id']} nome={payload['filename']} "
            f"origem={payload['source_url']} pasta={payload['folder_url']}"
        ),
    )
    if ns.wait and (payload.get("result") or {}).get("status") != "success":
        return 1
    if ns.wait and (payload.get("collected") or {}).get("status") != "success":
        return 1
    return 0


def cmd_loop_arm(ns: argparse.Namespace) -> int:
    from ia_orchestrator.loop import arm_plan

    home = _home(ns)
    cfg = resolve_project(ns.project, home)
    announce_repo(cfg, f"loop arm {ns.role}")
    plan = arm_plan(cfg, ns.role, home)
    env_export = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in plan["environment"].items())
    cmd = " ".join(shlex.quote(c) for c in plan["command"])
    emit(
        ns,
        plan,
        text=(
            f"Sentinela: {plan['sentinel']}\n"
            f"Intervalo: {plan['interval_seconds']}s\n"
            f"running_dir: {plan['running_dir']}\n"
            f"pid_file: {plan['pid_file']}\n\n"
            "Neste chat Cursor (Agent local), arranque o poller assim:\n"
            f"  Shell command: {env_export} {cmd}\n"
            "  block_until_ms: 0\n"
            f"  notify_on_output.pattern: {plan['sentinel']}\n"
            f"  notify_on_output.reason: {plan['notify_on_output']['reason']}\n\n"
            f"{plan['note']}"
        ),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ia-orchestrator",
        description=f"{SOFTWARE_NAME} {__version__} — protocolo v{PROTOCOL_VERSION}. Sempre indique --project. O repositório não é inferido do cwd.",
    )
    p.add_argument("--json", action="store_true", help="saída JSON")
    p.add_argument("--home", help="substitui IA_ORCHESTRATOR_HOME")
    p.add_argument("--version", action="version", version=f"{SOFTWARE_NAME} {__version__} protocol/{PROTOCOL_VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bootstrap", help="gerar config e guia de activação")
    b.add_argument("--project", required=True)
    b.add_argument("--repo", required=True)
    b.add_argument("--workspace", required=True)
    b.add_argument("--host", default="github.com")
    b.add_argument("--token-env")
    b.add_argument("--force", action="store_true")
    b.set_defaults(func=cmd_bootstrap)

    proj = sub.add_parser("project", help="cadastro de projectos")
    psub = proj.add_subparsers(dest="proj_cmd", required=True)
    pa = psub.add_parser("add")
    pa.add_argument("--project", required=True)
    pa.add_argument("--repo", required=True)
    pa.add_argument("--workspace", required=True)
    pa.add_argument("--host", default="github.com")
    pa.add_argument("--token-env")
    pa.add_argument("--force", action="store_true")
    pa.set_defaults(func=cmd_project_add)
    pl = psub.add_parser("list")
    pl.set_defaults(func=cmd_project_list)
    ps = psub.add_parser("show")
    ps.add_argument("--project", required=True)
    ps.set_defaults(func=cmd_project_show)

    d = sub.add_parser("doctor")
    d.add_argument("--project", required=True)
    d.add_argument("--probe", action="store_true", help="GET /user e GET /repos; não chama modelos pagos")
    d.set_defaults(func=cmd_doctor)

    t = sub.add_parser("task")
    tsub = t.add_subparsers(dest="task_cmd", required=True)
    tc = tsub.add_parser("create")
    tc.add_argument("--project", required=True)
    tc.add_argument("--prompt-file", required=True)
    tc.add_argument("--title")
    tc.add_argument("--task-id")
    tc.add_argument("--sender-id")
    tc.add_argument("--sender-role", choices=["orchestrator", "human"], default="orchestrator")
    tc.add_argument("--dispatch", action="store_true", help="publica também o primeiro request para a executora")
    tc.add_argument("--dry-run", action="store_true")
    tc.set_defaults(func=cmd_task_create)
    tl = tsub.add_parser("list")
    tl.add_argument("--project", required=True)
    tl.set_defaults(func=cmd_task_list)
    ts = tsub.add_parser("show")
    ts.add_argument("--project", required=True)
    ts.add_argument("--task", required=True)
    ts.set_defaults(func=cmd_task_show)
    tp = tsub.add_parser("pause")
    tp.add_argument("--project", required=True)
    tp.add_argument("--task", required=True)
    tp.add_argument("--reason", required=True)
    tp.add_argument("--dry-run", action="store_true")
    tp.set_defaults(func=cmd_task_pause)
    tr = tsub.add_parser("resume")
    tr.add_argument("--project", required=True)
    tr.add_argument("--task", required=True)
    tr.add_argument("--dry-run", action="store_true")
    tr.set_defaults(func=cmd_task_resume)
    tx = tsub.add_parser("cancel")
    tx.add_argument("--project", required=True)
    tx.add_argument("--task", required=True)
    tx.add_argument("--reason", required=True)
    tx.add_argument("--dry-run", action="store_true")
    tx.set_defaults(func=cmd_task_cancel)
    te = tsub.add_parser("export")
    te.add_argument("--project", required=True)
    te.add_argument("--task", required=True)
    te.add_argument("--output", required=True)
    te.set_defaults(func=cmd_task_export)


    check_cmd = sub.add_parser("check", help="inspecção passiva da execução/tarefa")
    check_cmd.add_argument("--project", required=True)
    check_cmd.add_argument("--task", required=True)
    check_cmd.set_defaults(func=cmd_check)

    status_cmd = sub.add_parser("status", help="non_blocking padronizado de telemetria da execução activa")
    status_cmd.add_argument("--project", required=True)
    status_cmd.add_argument("--task", required=True)
    status_cmd.add_argument("--dry-run", action="store_true")
    status_cmd.set_defaults(func=cmd_status)

    w = sub.add_parser("worker")
    wsub = w.add_subparsers(dest="worker_cmd", required=True)
    wr = wsub.add_parser("run")
    wr.add_argument("--project", required=True)
    wr.add_argument("--role", required=True, choices=["orchestrator", "executor", "agent"])
    wr.add_argument("--once", action="store_true")
    wr.add_argument("--dry-run", action="store_true")
    wr.set_defaults(func=cmd_worker_run)

    pend = sub.add_parser("pending", help="consultar pendências (modo pull/manual)")
    pend.add_argument("--project", required=True)
    pend.add_argument("--role", required=True, choices=["orchestrator", "executor", "agent"])
    pend.set_defaults(func=cmd_pending)

    ex = sub.add_parser("execution")
    esub = ex.add_subparsers(dest="ex_cmd", required=True)
    es = esub.add_parser("start")
    es.add_argument("--project", required=True)
    es.add_argument("--task", required=True)
    es.add_argument("--request", required=True)
    es.add_argument("--attempt", type=int, default=1)
    es.set_defaults(func=cmd_execution_start)
    ed = esub.add_parser("deliver")
    ed.add_argument("--project", required=True)
    ed.add_argument("--task", required=True)
    ed.add_argument("--request", required=True)
    ed.add_argument("--result-file", required=True)
    ed.add_argument("--attempt", type=int, default=1)
    ed.add_argument("--dry-run", action="store_true")
    ed.set_defaults(func=cmd_execution_deliver)

    msg = sub.add_parser("message")
    msub = msg.add_subparsers(dest="msg_cmd", required=True)
    mp = msub.add_parser("post")
    mp.add_argument("--project", required=True)
    mp.add_argument("--task", required=True)
    mp.add_argument("--type", required=True)
    mp.add_argument("--recipient", required=True)
    mp.add_argument("--body-file")
    mp.add_argument("--body")
    mp.add_argument("--request-id")
    mp.add_argument("--in-reply-to")
    mp.add_argument("--sender-role", default="human", choices=["human", "orchestrator", "executor", "agent"])
    mp.add_argument("--dry-run", action="store_true")
    mp.set_defaults(func=cmd_message_post)

    ob = sub.add_parser("outbox")
    osub = ob.add_subparsers(dest="ob_cmd", required=True)
    orec = osub.add_parser("reconcile")
    orec.add_argument("--project", required=True)
    orec.add_argument("--role", default="orchestrator", choices=["orchestrator", "executor"])
    orec.add_argument("--dry-run", action="store_true")
    orec.set_defaults(func=cmd_outbox_reconcile)

    demo = sub.add_parser("demo")
    dsub = demo.add_subparsers(dest="demo_cmd", required=True)
    do = dsub.add_parser("offline")
    do.add_argument("--output")
    do.set_defaults(func=cmd_demo)

    lp = sub.add_parser("loop", help="poller Cursor chat: inspect/tick/arm (não executa o job)")
    lsub = lp.add_subparsers(dest="loop_cmd", required=True)
    li = lsub.add_parser("inspect", help="estado IDLE/JOB/RECOVERY/CONFLICT sem claim")
    li.add_argument("--project", required=True)
    li.add_argument("--role", required=True, choices=["orchestrator", "executor", "agent"])
    li.set_defaults(func=cmd_loop_inspect)
    lt = lsub.add_parser("tick", help="sync GitHub, opcionalmente claim, emite sentinela se o estado mudou")
    lt.add_argument("--project", required=True)
    lt.add_argument("--role", required=True, choices=["orchestrator", "executor", "agent"])
    claim_g = lt.add_mutually_exclusive_group()
    claim_g.add_argument("--claim", dest="claim", action="store_true", help="materializar no máximo um running/*.md (omissão)")
    claim_g.add_argument("--no-claim", dest="claim", action="store_false")
    lt.set_defaults(claim=True)
    lt.add_argument("--reset-wake", action="store_true", help="esquecer last_wake antes deste tick (recuperação manual)")
    lt.set_defaults(func=cmd_loop_tick)
    lr = lsub.add_parser("rearm", help="apagar last_wake sem executar tick; usar como última ação antes de ceder um job multi-turn")
    lr.add_argument("--project", required=True)
    lr.add_argument("--role", required=True, choices=["orchestrator", "executor", "agent"])
    lr.set_defaults(func=cmd_loop_rearm)
    la = lsub.add_parser("arm", help="imprimir comando + notify_on_output para este chat")
    la.add_argument("--project", required=True)
    la.add_argument("--role", required=True, choices=["orchestrator", "executor", "agent"])
    la.set_defaults(func=cmd_loop_arm)

    send_file = sub.add_parser("send-file", help="orquestrador envia um arquivo; executor recebe em transfered_files")
    _add_send_file_arguments(send_file)
    send_file_alias = sub.add_parser("send_file", help="alias de send-file")
    _add_send_file_arguments(send_file_alias)
    send = sub.add_parser("send", help="send file")
    send_sub = send.add_subparsers(dest="send_cmd", required=True)
    send_word = send_sub.add_parser("file", help="alias de send-file")
    _add_send_file_arguments(send_word)

    get_file = sub.add_parser("get-file", help="orquestrador pede um arquivo da internet; executor envia pela pasta do Drive")
    _add_get_file_arguments(get_file)
    get_file_alias = sub.add_parser("get_file", help="alias de get-file")
    _add_get_file_arguments(get_file_alias)
    get = sub.add_parser("get", help="get file")
    get_sub = get.add_subparsers(dest="get_cmd", required=True)
    get_word = get_sub.add_parser("file", help="alias de get-file")
    _add_get_file_arguments(get_word)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
        return int(ns.func(ns))
    except SystemExit as exc:
        code = exc.code
        if code in (0, None):
            raise
        return int(code) if isinstance(code, int) else 2
    except OrchestratorError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return int(getattr(exc, "exit_code", 1))
    except KeyboardInterrupt:
        print("interrompendo; checkpoints e outbox preservados", file=sys.stderr)
        return 1
