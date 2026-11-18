from __future__ import annotations

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.protocol import parse_comment
from ia_orchestrator.workers import Engine

from helpers import comment_types, make_cfg, open_task, pair


def test_two_rounds_and_complete(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-a", "org/alpha", shared)
    model = SimulatedModelAdapter()
    executor = SimulatedExecutorAdapter(
        script=[
            {"status": "success", "summary": "sem testes", "tests": [], "shared_artifacts": []},
            {
                "status": "success",
                "summary": "ok",
                "tests": [{"name": "t", "passed": True, "evidence": "log"}],
                "shared_artifacts": [{"repository": "org/alpha", "path": "a.md", "commit": "1", "sha256": "2"}],
            },
        ]
    )
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=model)
    exe = Engine(cfg_e, es_, et, "executor", executor=executor)
    human = ot
    task_id, issue, _ = open_task(human, cfg_o, "## Objetivo\nFazer a entrega.\n")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t", objective="x")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t", objective="x")
    for _ in range(10):
        orch.tick()
        exe.tick()
        if (os_.get_task(cfg_o.namespace, task_id) or {}).get("state") == "COMPLETED":
            break
    types = comment_types(ot, issue.number)
    assert "task_open" in types
    assert types.count("request") >= 2
    assert "result" in types
    assert "review" in types
    assert "complete" in types
    assert os_.get_task(cfg_o.namespace, task_id)["state"] == "COMPLETED"
    assert ot.get_issue(issue.number).state == "closed"
    assert "org/alpha" in cfg_o.namespace
