"""Diagnóstico sem chamadas pagas."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ia_orchestrator.config import ProjectConfig, db_path
from ia_orchestrator.errors import AuthError, NetworkError, PolicyError
from ia_orchestrator.persistence import Store
from ia_orchestrator.transport import Transport


def doctor_report(cfg: ProjectConfig, transport: Transport | None, home: Path | None, *, probe_github: bool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    ws = Path(cfg.workspace.root).expanduser()
    add("workspace", ws.exists(), str(ws.resolve()) if ws.exists() else f"ausente: {ws}")

    db = db_path(cfg, home)
    try:
        store = Store(db)
        store.close()
        add("database", True, str(db))
    except Exception as exc:  # noqa: BLE001
        add("database", False, str(exc))

    token_set = bool(os.environ.get(cfg.github.token_env))
    add("github_token_env", token_set, cfg.github.token_env if token_set else f"{cfg.github.token_env} não definida")

    senders = cfg.github.allowed_senders
    overlap = set(senders.orchestrator) & set(senders.executor)
    add(
        "roles",
        bool(senders.human and senders.orchestrator and senders.executor),
        "contas distintas" if not overlap else "ATENÇÃO: orquestradora e executora partilham login; garantia de identidade reduzida",
    )

    if probe_github and transport is not None:
        try:
            ident = transport.identity()
            add("github_auth", True, f"login={ident.get('login')}")
        except AuthError as exc:
            add("github_auth", False, str(exc))
        except NetworkError as exc:
            add("github_auth", False, str(exc))
        try:
            repo = transport.get_repository()
            add("issues_enabled", bool(repo.get("has_issues", True)), f"has_issues={repo.get('has_issues')}")
            perms = repo.get("permissions") or {}
            add("permissions", True, f"pull={perms.get('pull')} push={perms.get('push')} (push não é exigido para Issues)")
        except Exception as exc:  # noqa: BLE001
            add("repository", False, str(exc))
    else:
        add("github_auth", token_set, "não sondado (use --probe para GET /user; sem chamada paga)")
        add("issues_enabled", True, "não sondado")

    if cfg.orchestrator.mode == "api":
        key_name = cfg.orchestrator.api_key_env
        present = bool(key_name and os.environ.get(key_name))
        add("model_credential", present, key_name or "api_key_env ausente")
        add("model_adapter", True, f"provider={cfg.orchestrator.provider} model={cfg.orchestrator.model} (doctor não chama o modelo)")
    else:
        add("model_adapter", True, f"mode={cfg.orchestrator.mode} provider={cfg.orchestrator.provider}")

    add("executor", True, f"mode={cfg.executor.mode} command={cfg.executor.command or '(simulated/manual/cursor_chat)'}")
    add(
        "agent_channel",
        True,  # Optional for legacy projects; cannot imply runtime independence.
        "configured (chat-only)" if cfg.github.allowed_senders.agent
        else "disabled until github.allowed_senders.agent is configured",
    )
    add("policy", True, f"allow_push={cfg.policy.allow_push} allow_merge={cfg.policy.allow_merge} allow_deploy={cfg.policy.allow_deploy}")
    if cfg.alerts.enabled:
        env_present = bool(os.environ.get(cfg.alerts.webhook_url_env))
        add(
            "discord_alerts",
            True,
            cfg.alerts.webhook_url_env if env_present else "discord_msg não vem neste pacote; desligue alerts ou instale o envio à parte",
        )
    else:
        add("discord_alerts", True, "desligados (alerts.enabled=false); GitHub continua a SoT")
    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "project_id": cfg.project_id,
        "repository": cfg.resolved_repo_label(),
        "checks": checks,
    }
