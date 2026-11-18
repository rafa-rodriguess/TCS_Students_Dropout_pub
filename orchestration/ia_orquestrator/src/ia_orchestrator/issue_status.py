"""Labels de status visíveis na issue GitHub. Não substituem o envelope."""

from __future__ import annotations

STATUS_PREFIX = "status:"
STATUS_CLAIMED = "claimed"
STATUS_RUNNING = "running"
STATUS_WAITING_ORCHESTRATOR = "waiting-orchestrator"
STATUS_COMPLETED = "completed"
# waiting-input is a task state. It does not close the issue and has no
# status: label of its own. The issue stays open for a later request.


def merge_status_labels(existing: list[str], status: str) -> list[str]:
    token = status.strip()
    if not token:
        raise ValueError("status vazio")
    kept = [lab for lab in existing if lab and not str(lab).startswith(STATUS_PREFIX)]
    return kept + [f"{STATUS_PREFIX}{token}"]
