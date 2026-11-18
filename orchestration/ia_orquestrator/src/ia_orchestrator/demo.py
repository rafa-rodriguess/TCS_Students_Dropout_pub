"""Demonstração end-to-end offline, sem credenciais."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.config import ProjectConfig, example_config_dict
from ia_orchestrator.persistence import Store
from ia_orchestrator.protocol import MessageType, build_envelope, new_id, render_message
from ia_orchestrator.transport import MemoryTransport
from ia_orchestrator.workers import Engine


def _cfg(project_id: str, repo: str, workspace: Path, actor_role: str) -> ProjectConfig:
    data = example_config_dict(project_id, repo, str(workspace))
    data["orchestrator"]["mode"] = "simulated"
    data["orchestrator"]["provider"] = "simulated"
    data["executor"]["mode"] = "simulated"
    if actor_role == "executor":
        data["github"]["allowed_senders"]["executor"] = ["bot-executor"]
    return ProjectConfig.model_validate(data)


def run_offline_demo(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    shared: dict[str, Any] = {}
    ws = root / "workspace"
    ws.mkdir(exist_ok=True)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "proposta.md").write_text("# Proposta\nDemo offline.\n", encoding="utf-8")
    (ws / "AGENTS.md").write_text("# Instruções\nSiga o protocolo.\n", encoding="utf-8")

    orch_cfg = _cfg("projeto-demo", "organizacao/repositorio-demo", ws, "orchestrator")
    exec_cfg = _cfg("projeto-demo", "organizacao/repositorio-demo", ws, "executor")
    orch_store = Store(root / "orch.sqlite")
    exec_store = Store(root / "exec.sqlite")
    orch_t = MemoryTransport("github.com", "organizacao/repositorio-demo", actor="bot-orquestrador", shared=shared)
    exec_t = MemoryTransport("github.com", "organizacao/repositorio-demo", actor="bot-executor", shared=shared)

    model = SimulatedModelAdapter()
    executor = SimulatedExecutorAdapter(
        script=[
            {
                "status": "success",
                "summary": "Rascunho sem testes.",
                "files_modified": ["a.txt"],
                "tests": [],
                "shared_artifacts": [],
            },
            {
                "status": "success",
                "summary": "Entrega completa.",
                "files_modified": ["a.txt"],
                "tests": [{"name": "demo", "passed": True, "evidence": "ok"}],
                "shared_artifacts": [
                    {"repository": "organizacao/repositorio-demo", "path": "docs/demo.md", "commit": "abc", "sha256": "def"}
                ],
            },
        ]
    )

    orch = Engine(orch_cfg, orch_store, orch_t, "orchestrator", model=model)
    exe = Engine(exec_cfg, exec_store, exec_t, "executor", executor=executor)

    task_id = new_id()
    body = "## Objetivo\nProduzir uma entrega demonstrável com evidência de teste.\n"
    env = build_envelope(
        project_id="projeto-demo",
        repository="organizacao/repositorio-demo",
        task_id=task_id,
        sender_role="human",
        sender_id="usuario-responsavel",
        recipient_role="orchestrator",
        type=MessageType.TASK_OPEN.value,
        body=body,
    )
    rendered = render_message(env, body)
    issue = orch_t.create_issue("Demo offline", rendered, labels=["ia-orchestrator", "project:projeto-demo"])
    # humano autorizado no transporte da orquestradora: injecta como se o humano tivesse aberto
    orch_t.actor = "usuario-responsavel"
    # o issue body precisa ser ingerido: replica como primeiro comentário humano para o polling
    orch_t.create_comment(issue.number, rendered)
    orch_t.actor = "bot-orquestrador"

    orch_store.upsert_task(orch_cfg.namespace, task_id, issue_number=issue.number, title="Demo offline", objective=body)
    exec_store.upsert_task(exec_cfg.namespace, task_id, issue_number=issue.number, title="Demo offline", objective=body)

    timeline = []
    for step in range(8):
        timeline.append({"step": step, "orch": orch.tick(), "exec": exe.tick()})
        task = orch_store.get_task(orch_cfg.namespace, task_id)
        if task and task["state"] == "COMPLETED":
            break

    comments = orch_t.list_issue_comments(issue.number)
    return {
        "task_id": task_id,
        "issue": issue.number,
        "state": (orch_store.get_task(orch_cfg.namespace, task_id) or {}).get("state"),
        "comments": len(comments),
        "types": [c.body.split('"type": "')[1].split('"')[0] if '"type": "' in c.body else "?" for c in comments],
        "timeline": timeline,
        "root": str(root),
    }
