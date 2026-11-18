from __future__ import annotations

from pathlib import Path
from typing import Any

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.config import ProjectConfig, example_config_dict
from ia_orchestrator.persistence import Store
from ia_orchestrator.protocol import MessageType, build_envelope, new_id, parse_comment, render_message
from ia_orchestrator.transport import MemoryTransport
from ia_orchestrator.workers import Engine


def make_cfg(tmp: Path, project_id: str, repo: str, **overrides: Any) -> ProjectConfig:
    ws = tmp / project_id / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "proposta.md").write_text("proposta", encoding="utf-8")
    (ws / "AGENTS.md").write_text("instrucoes", encoding="utf-8")
    data = example_config_dict(project_id, repo, str(ws))
    data["orchestrator"]["mode"] = "simulated"
    data["orchestrator"]["provider"] = "simulated"
    data["executor"]["mode"] = "simulated"
    data["alerts"]["enabled"] = False
    data["github"]["allowed_senders"] = {
        "human": ["usuario-responsavel"],
        "orchestrator": ["bot-orquestrador"],
        "executor": ["bot-executor"],
    }
    for key, value in overrides.items():
        data[key] = value
    return ProjectConfig.model_validate(data)


def pair(tmp: Path, project_id: str, repo: str, shared: dict, **kwargs: Any):
    cfg_o = make_cfg(tmp, project_id, repo, **kwargs)
    cfg_e = make_cfg(tmp, project_id, repo, **kwargs)
    orch_store = Store(tmp / project_id / "orch.sqlite")
    exec_store = Store(tmp / project_id / "exec.sqlite")
    orch_t = MemoryTransport("github.com", repo, actor="bot-orquestrador", shared=shared)
    exec_t = MemoryTransport("github.com", repo, actor="bot-executor", shared=shared)
    return cfg_o, cfg_e, orch_store, exec_store, orch_t, exec_t


def open_task(human_t: MemoryTransport, cfg: ProjectConfig, body: str, title: str = "tarefa"):
    task_id = new_id()
    env = build_envelope(
        project_id=cfg.project_id,
        repository=cfg.github.repository,
        task_id=task_id,
        sender_role="human",
        sender_id="usuario-responsavel",
        recipient_role="orchestrator",
        type=MessageType.TASK_OPEN.value,
        body=body,
    )
    rendered = render_message(env, body)
    prev = human_t.actor
    human_t.actor = "usuario-responsavel"
    issue = human_t.create_issue(title, rendered, labels=["ia-orchestrator", f"project:{cfg.project_id}"])
    human_t.create_comment(issue.number, rendered)
    human_t.actor = prev
    return task_id, issue, env


def comment_types(transport: MemoryTransport, number: int) -> list[str]:
    types = []
    for c in transport.list_issue_comments(number):
        parsed = parse_comment(c.body)
        if parsed.envelope:
            types.append(parsed.envelope.type)
    return types
