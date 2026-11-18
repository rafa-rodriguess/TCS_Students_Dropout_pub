"""Alertas opcionais. Este pacote não traz discord_msg. Nunca substituem o transporte GitHub."""

from __future__ import annotations

import re
import sys
from typing import Any

from ia_orchestrator.config import ProjectConfig

DEFAULT_EVENTS = (
    "envelope_arrived",
    "request_claimed",
    "execution_started",
    "result_delivered",
    "task_completed",
    "quarantine",
    "git_error",
)
SKIP_TYPES = frozenset({"ack", "progress"})
_WEBHOOK_URL = re.compile(r"https://discord(?:app)?\.com/api/webhooks/\S+")
ARRIVAL_TYPES = frozenset({
    "request",
    "non_blocking",
    "programmed_stop",
    "task_open",
    "question",
    "answer",
    "review",
    "send_file",
    "send_file_ready",
    "get_file",
})


def phase_for_envelope_type(typ: str | None) -> str | None:
    if not typ or typ in SKIP_TYPES:
        return None
    if typ in ARRIVAL_TYPES:
        return "envelope_arrived"
    if typ in {"result", "control_result"}:
        return "result_delivered"
    if typ == "complete":
        return "task_completed"
    return "envelope_arrived"


def _send_fn():
    """Importa discord_msg só se o operador o instalou à parte. Não procura a árvore privada."""
    from discord_msg import send
    from discord_msg.config import DiscordMsgConfig

    return send, DiscordMsgConfig


def format_alert(phase: str, cfg: ProjectConfig, fields: dict[str, Any]) -> str:
    lines = [
        "ia-orchestrator ALERT",
        f"phase={phase}",
        f"project={cfg.project_id}",
        f"repository={cfg.resolved_repo_label()}",
    ]
    for key in ("role", "type", "task_id", "request_id", "issue", "message_id", "reason", "status"):
        value = fields.get(key)
        if value is None or value == "":
            continue
        lines.append(f"{key}={value}")
    return "\n".join(lines)


def _failure_line(phase: str, exc: BaseException) -> str:
    status = getattr(exc, "status", None)
    detail = _WEBHOOK_URL.sub("[webhook]", str(exc)).replace("\n", " ")[:240]
    return (
        f"ia-orchestrator alert failed phase={phase} "
        f"error={type(exc).__name__} status={status} detail={detail}"
    )


def notify(cfg: ProjectConfig, phase: str, **fields: Any) -> bool:
    """POST um alerta. Devolve True se enviou. Nunca propaga erro ao protocolo."""
    alerts = cfg.alerts
    if not alerts.enabled:
        return False
    allowed = tuple(alerts.events) if alerts.events else DEFAULT_EVENTS
    if phase not in allowed:
        return False
    try:
        send, discord_cfg_cls = _send_fn()
        settings = discord_cfg_cls(
            webhook_url_env=alerts.webhook_url_env,
            username=alerts.username,
            code_block=True,
            suppress_mentions=True,
        )
        send(format_alert(phase, cfg, fields), cfg=settings)
        return True
    except Exception as exc:  # noqa: BLE001 — alerta nunca bloqueia GitHub
        print(_failure_line(phase, exc), file=sys.stderr)
        return False
