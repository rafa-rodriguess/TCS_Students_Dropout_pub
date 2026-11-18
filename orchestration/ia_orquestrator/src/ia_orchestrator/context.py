"""Pacote de contexto com fontes e versões verificáveis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ia_orchestrator.config import ProjectConfig
from ia_orchestrator.errors import PolicyError
from ia_orchestrator.policy import estimate_tokens, resolve_under_root
from ia_orchestrator.protocol import sha256_text, utc_now


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head(workspace: Path) -> str | None:
    head = workspace / ".git" / "HEAD"
    if not head.is_file():
        return None
    value = head.read_text(encoding="utf-8").strip()
    if value.startswith("ref:"):
        ref = workspace / ".git" / value.split(" ", 1)[1].strip()
        if ref.is_file():
            return ref.read_text(encoding="utf-8").strip()[:40]
        return None
    return value[:40]


def load_source(cfg: ProjectConfig, name: str, relative: str | None, *, required: bool) -> dict[str, Any]:
    workspace = cfg.workspace_root()
    if not relative:
        if required:
            raise PolicyError(f"fonte obrigatória '{name}' não declarada")
        return {
            "name": name,
            "declared": False,
            "present": False,
            "warning": f"fonte opcional '{name}' não declarada",
        }
    path = resolve_under_root(workspace, relative)
    if not path.exists():
        if required or name in cfg.context.required:
            raise PolicyError(f"fonte obrigatória ausente: {name} -> {relative}")
        return {
            "name": name,
            "path": relative,
            "declared": True,
            "present": False,
            "warning": f"fonte opcional '{name}' declarada mas ausente em {path}",
        }
    text = path.read_text(encoding="utf-8")
    return {
        "name": name,
        "path": relative,
        "resolved": str(path),
        "declared": True,
        "present": True,
        "sha256": file_sha256(path),
        "bytes": len(text.encode("utf-8")),
        "content": text,
    }


def build_context_package(
    cfg: ProjectConfig,
    *,
    task: dict[str, Any],
    messages: list[dict[str, Any]],
    result: dict[str, Any] | None = None,
    human_decisions: list[str] | None = None,
) -> dict[str, Any]:
    required = set(cfg.context.required)
    sources = [
        load_source(cfg, "proposal", cfg.context.proposal, required="proposal" in required),
        load_source(cfg, "source_of_truth", cfg.context.source_of_truth, required="source_of_truth" in required),
        load_source(cfg, "instructions", cfg.context.instructions, required="instructions" in required),
    ]
    for name, rel in cfg.context.extra.items():
        sources.append(load_source(cfg, name, rel, required=name in required))

    revision_parts = [s.get("sha256", "") for s in sources if s.get("present")]
    revision_parts.append(git_head(cfg.workspace_root()) or "")
    context_revision = sha256_text("|".join(revision_parts))[:16]

    warnings = [s["warning"] for s in sources if s.get("warning")]
    package = {
        "schema_version": 1,
        "project_id": cfg.project_id,
        "repository": cfg.github.repository,
        "host": cfg.github.host,
        "task_id": task.get("task_id"),
        "task_state": task.get("state"),
        "objective": task.get("objective"),
        "context_revision": context_revision,
        "workspace_commit": git_head(cfg.workspace_root()),
        "sources": [
            {k: v for k, v in s.items() if k != "content" or True}
            for s in sources
        ],
        "human_decisions": human_decisions or [],
        "limits": cfg.limits.model_dump(),
        "policy": cfg.policy.model_dump(),
        "messages": [
            {
                "message_id": m.get("message_id"),
                "type": m.get("type"),
                "sender_role": m.get("sender_role"),
                "created_at": m.get("created_at"),
                "body": m.get("body_text"),
                "request_id": m.get("request_id"),
            }
            for m in messages
            if m.get("kind") == "envelope"
        ],
        "result": result,
        "warnings": warnings,
        "built_at": utc_now(),
    }
    # Truncar conteúdo se estourar tokens estimados, preservando instruções/critérios.
    packed = json.dumps(package, ensure_ascii=False)
    if estimate_tokens(packed) > cfg.limits.max_input_tokens:
        for source in package["sources"]:
            content = source.get("content")
            if content and len(content) > 2000:
                source["content"] = content[:2000] + "\n\n[resumo: conteúdo truncado; original em " + source.get("path", "") + f" sha256={source.get('sha256')}]"
                source["truncated"] = True
        older = package["messages"][:-8]
        recent = package["messages"][-8:]
        package["messages"] = [
            {
                "summary_of": [m.get("message_id") for m in older],
                "note": "mensagens anteriores resumidas; originais permanecem no registro",
            }
        ] + recent
    return package


def detect_revision_divergence(task_revision: str | None, package_revision: str) -> bool:
    if not task_revision:
        return False
    return task_revision != package_revision
