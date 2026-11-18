from __future__ import annotations

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.workers import Engine

from helpers import open_task, pair


def test_two_projects_different_repos_same_issue_number(tmp_path):
    shared: dict = {}
    a = pair(tmp_path, "p1", "org/one", shared)
    b = pair(tmp_path, "p2", "org/two", shared)
    run_one(a, "p1")
    run_one(b, "p2")
    (_, _, os_a, _, ot_a, _) = a
    (_, _, os_b, _, ot_b, _) = b
    # ambos podem ter issue #1 sem cruzar
    tasks_a = os_a.list_tasks(a[0].namespace)
    tasks_b = os_b.list_tasks(b[0].namespace)
    assert tasks_a and tasks_b
    assert tasks_a[0]["issue_number"] == tasks_b[0]["issue_number"] == 1
    assert a[0].namespace != b[0].namespace
    bodies_a = [c.body for c in ot_a.list_issue_comments(1)]
    bodies_b = [c.body for c in ot_b.list_issue_comments(1)]
    assert any("p1" in x or "org/one" in x for x in bodies_a)
    assert any("org/two" in x for x in bodies_b)
    assert os_a.messages_for_task(a[0].namespace, tasks_a[0]["task_id"])
    # mensagens do B não estão no store A
    for m in os_a.unprocessed_messages(a[0].namespace) + os_a.messages_for_task(a[0].namespace, tasks_a[0]["task_id"]):
        if m.get("envelope_json"):
            assert "org/two" not in (m.get("envelope_json") or "")


def test_two_projects_same_repo_separated(tmp_path):
    shared: dict = {}
    a = pair(tmp_path, "alpha", "org/shared", shared)
    b = pair(tmp_path, "beta", "org/shared", shared)
    run_one(a, "alpha")
    run_one(b, "beta")
    comments = a[4].list_repo_comments()
    envs_a = [c for c in comments if '"project_id": "alpha"' in c.body or '"project_id":"alpha"' in c.body]
    envs_b = [c for c in comments if '"project_id": "beta"' in c.body]
    assert envs_a and envs_b
    # store A ignora project_id beta
    for m in a[2].conn.execute("SELECT * FROM messages WHERE namespace=?", (a[0].namespace,)).fetchall():
        if m["envelope_json"]:
            assert "beta" not in m["envelope_json"] or m["kind"] != "envelope" or '"project_id": "alpha"' in m["envelope_json"]


def run_one(pack, tag: str) -> None:
    cfg_o, cfg_e, os_, es_, ot, et = pack
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(
        cfg_e,
        es_,
        et,
        "executor",
        executor=SimulatedExecutorAdapter(
            script=[
                {
                    "status": "success",
                    "summary": tag,
                    "tests": [{"name": "t", "passed": True, "evidence": "e"}],
                    "shared_artifacts": [{"repository": cfg_o.github.repository, "path": "x", "commit": "c", "sha256": "s"}],
                }
            ]
        ),
    )
    task_id, issue, _ = open_task(ot, cfg_o, f"objetivo {tag}")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title=tag)
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title=tag)
    for _ in range(8):
        orch.tick()
        exe.tick()
        if (os_.get_task(cfg_o.namespace, task_id) or {}).get("state") == "COMPLETED":
            break
    assert os_.get_task(cfg_o.namespace, task_id)["state"] == "COMPLETED"
    assert issue.number >= 1
