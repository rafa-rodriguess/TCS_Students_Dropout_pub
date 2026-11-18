from __future__ import annotations

from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.state import ExecutionState
from ia_orchestrator.workers import Engine, _stable_id

from helpers import open_task, pair


def test_redelivery_does_not_reexecute(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-r", "org/r", shared)
    adapter = SimulatedExecutorAdapter(
        script=[
            {
                "status": "success",
                "summary": "ok",
                "tests": [{"name": "t", "passed": True, "evidence": "e"}],
                "shared_artifacts": [{"repository": "org/r", "path": "x", "commit": "c", "sha256": "s"}],
            }
        ]
    )
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", executor=adapter)
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    for _ in range(6):
        orch.tick()
        exe.tick()
    assert len(adapter.calls) == 1
    # reentrega: marca request como não processada
    rows = es_.conn.execute(
        "SELECT message_id FROM messages WHERE namespace=? AND type='request'",
        (cfg_e.namespace,),
    ).fetchall()
    assert rows
    es_.conn.execute(
        "UPDATE messages SET processed_at=NULL WHERE namespace=? AND type='request'",
        (cfg_e.namespace,),
    )
    es_.commit()
    exe.process_inbox()
    assert len(adapter.calls) == 1


def test_publish_timeout_after_remote_success(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-t", "org/t", shared)
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    from ia_orchestrator.protocol import MessageType, build_envelope, render_message

    env = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="orchestrator",
        sender_id="coordenador-01",
        recipient_role="executor",
        type=MessageType.PROGRESS.value,
        body="progresso",
        request_id="req-1",
    )
    rendered = render_message(env, "progresso")
    os_.enqueue_outbox(cfg_o.namespace, env.message_id, task_id, issue.number, rendered)
    ot.timeout_after_create = True
    n = orch.flush_outbox()
    row = os_.get_outbox(cfg_o.namespace, env.message_id)
    assert row["status"] == "PUBLISHED"
    assert row["github_comment_id"] is not None
    found = ot.find_comment_by_message_id(issue.number, env.message_id)
    assert found is not None
    assert found.id == row["github_comment_id"]
    assert n >= 1


def test_crash_before_and_after_execution(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-c", "org/c", shared)
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", executor=SimulatedExecutorAdapter(script=[{"status": "success", "summary": "x", "tests": [{"name": "t", "passed": True, "evidence": "e"}]}]))
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    exe.sync()
    # crash antes da execução: STARTING persistido
    req = es_.conn.execute("SELECT * FROM messages WHERE type='request' AND namespace=?", (cfg_e.namespace,)).fetchone()
    assert req
    import json
    from ia_orchestrator.protocol import Envelope

    env = Envelope.model_validate(json.loads(req["envelope_json"]))
    idem = f"{cfg_e.namespace}:{env.request_id}:{env.attempt}"
    es_.start_execution(cfg_e.namespace, idempotency_key=idem, request_id=env.request_id, task_id=task_id, attempt=1, input_json={})
    exe.process_inbox()
    execution = es_.get_execution(cfg_e.namespace, idem)
    assert execution["status"] == ExecutionState.UNKNOWN.value
    # crash depois da execução, antes da publicação: output persistido, outbox reconcilia
    idem2 = f"{cfg_e.namespace}:{env.request_id}:99"
    es_.start_execution(cfg_e.namespace, idempotency_key=idem2, request_id=env.request_id, task_id=task_id, attempt=99, input_json={})
    es_.finish_execution(cfg_e.namespace, idem2, ExecutionState.SUCCEEDED.value, output={"status": "success", "summary": "late"})
    env2 = env.model_copy(update={"attempt": 99, "request_id": env.request_id})
    exe._publish_executor_output(es_.get_task(cfg_e.namespace, task_id), env2, {"status": "success", "summary": "late"}, idem2)
    et.timeout_after_create = True
    exe.flush_outbox()
    out = es_.pending_outbox(cfg_e.namespace)
    # publicado via reconciliação
    row = es_.get_outbox(cfg_e.namespace, _stable_id("result", idem2))
    assert row and row["status"] == "PUBLISHED"
