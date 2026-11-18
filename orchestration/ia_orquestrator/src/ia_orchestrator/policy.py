"""Políticas, limites e validação de autoridade. O modelo não decide permissões."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ia_orchestrator.config import ProjectConfig
from ia_orchestrator.errors import PolicyError
from ia_orchestrator.protocol import Envelope
from ia_orchestrator.state import TaskState, blocks_new_work

FORBIDDEN_POLICY_KEYS = ("allow_push", "allow_merge", "allow_deploy", "token_env", "api_key_env", "repository")


def authorize_sender(cfg: ProjectConfig, envelope: Envelope, github_login: str | None) -> None:
    allowed = cfg.github.allowed_senders.logins_for(envelope.sender_role)
    if not github_login:
        raise PolicyError("comentário sem autoria GitHub autenticada")
    if github_login not in allowed:
        raise PolicyError(
            f"remetente GitHub '{github_login}' não autorizado para o papel {envelope.sender_role} no projecto {cfg.project_id}"
        )
    orch = set(cfg.github.allowed_senders.orchestrator)
    exe = set(cfg.github.allowed_senders.executor)
    if orch & exe:
        # mesma conta nos dois papéis reduz garantia de identidade
        pass


def assert_project_match(cfg: ProjectConfig, envelope: Envelope) -> None:
    if envelope.project_id != cfg.project_id:
        raise PolicyError(f"project_id do envelope ({envelope.project_id}) ≠ config ({cfg.project_id})")
    if envelope.repository.lower() != cfg.github.repository.lower():
        raise PolicyError("repositório do envelope não coincide com o cadastrado")


def reject_unauthorized_mutations(body: str, cfg: ProjectConfig) -> None:
    lowered = body.lower()
    if "exfiltrate" in lowered or "send the token" in lowered or "envie o token" in lowered:
        raise PolicyError("resultado pediu envio de segredos; rejeitado")
    if "trocar repositório" in lowered or "change repository to" in lowered:
        raise PolicyError("resultado pediu troca de repositório; rejeitado")


def resolve_under_root(root: Path, relative: str) -> Path:
    if os.path.isabs(relative):
        path = Path(relative).resolve()
    else:
        path = (root / relative).resolve()
    root_res = root.resolve()
    if not path.is_relative_to(root_res):
        raise PolicyError(f"path fora do workspace autorizado: {relative}")
    return path


def check_limits(
    cfg: ProjectConfig,
    *,
    rounds: int,
    revisions: int,
    usage: dict[str, Any],
    elapsed_seconds: float | None = None,
) -> str | None:
    limits = cfg.limits
    if rounds >= limits.max_rounds_per_task:
        return "limite de rodadas atingido"
    if revisions >= limits.max_revisions_per_request:
        return "limite de revisões atingido"
    if usage.get("calls", 0) >= limits.max_model_calls_per_task:
        return "limite de chamadas de modelo atingido"
    tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
    if tokens >= limits.max_input_tokens + limits.max_output_tokens * max(1, int(usage.get("calls") or 1)):
        # limite brando informativo; o corte duro é por chamada
        pass
    if elapsed_seconds is not None and elapsed_seconds >= limits.task_timeout_seconds:
        return "timeout da tarefa"
    cost = usage.get("cost_usd")
    if cfg.limits.budget_usd_per_task is not None and usage.get("all_known") not in (0, None):
        if cost is not None and float(cost) >= cfg.limits.budget_usd_per_task:
            return "orçamento da tarefa esgotado"
    return None


def can_dispatch(state: str) -> bool:
    try:
        return not blocks_new_work(TaskState(state))
    except ValueError:
        return False


def subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Ambiente mínimo. Tokens de transporte/modelo não são herdados."""
    allow = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT"}
    env = {k: v for k, v in os.environ.items() if k in allow or k.startswith("LC_")}
    blocked_needles = ("TOKEN", "API_KEY", "SECRET", "PASSWORD", "OPENAI", "ANTHROPIC", "GITHUB")
    for key in list(env):
        upper = key.upper()
        if any(n in upper for n in blocked_needles):
            env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_cost_usd(cfg: ProjectConfig, model: str, prompt_tokens: int, completion_tokens: int) -> tuple[float | None, bool]:
    prices = cfg.pricing.models.get(model)
    if not prices:
        return None, False
    cost = (prompt_tokens / 1_000_000) * prices.input_per_1m + (completion_tokens / 1_000_000) * prices.output_per_1m
    return cost, True
