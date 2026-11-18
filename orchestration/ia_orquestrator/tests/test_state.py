from __future__ import annotations

import pytest

from ia_orchestrator.errors import ProtocolError
from ia_orchestrator.state import TaskState, apply_transition
from ia_orchestrator.adapters.executor import SimulatedExecutorAdapter
from ia_orchestrator.adapters.model import SimulatedModelAdapter
from ia_orchestrator.protocol import MessageType, build_envelope, render_message
from ia_orchestrator.workers import Engine

from helpers import open_task, pair


def test_transition_table():
    assert apply_transition(TaskState.NEW, "request") == TaskState.WAITING_EXECUTOR
    assert apply_transition(TaskState.WAITING_EXECUTOR, "ack") == TaskState.RUNNING
    assert apply_transition(TaskState.RUNNING, "result") == TaskState.WAITING_ORCHESTRATOR
    assert apply_transition(TaskState.WAITING_ORCHESTRATOR, "complete") == TaskState.COMPLETED
    assert apply_transition(TaskState.RUNNING, "question") == TaskState.WAITING_INPUT
    assert apply_transition(TaskState.RUNNING, "non_blocking") == TaskState.RUNNING
    assert apply_transition(TaskState.RUNNING, "programmed_stop") == TaskState.RUNNING
    assert apply_transition(TaskState.RUNNING, "control_result") == TaskState.RUNNING
    assert apply_transition(TaskState.WAITING_INPUT, "answer", previous=TaskState.RUNNING) == TaskState.RUNNING
    assert apply_transition(TaskState.WAITING_INPUT, "request") == TaskState.WAITING_EXECUTOR
    assert apply_transition(TaskState.WAITING_EXECUTOR, "pause") == TaskState.PAUSED
    assert apply_transition(TaskState.PAUSED, "resume", previous=TaskState.WAITING_ORCHESTRATOR) == TaskState.WAITING_ORCHESTRATOR
    assert apply_transition(TaskState.COMPLETED, "result") == TaskState.COMPLETED
    with pytest.raises(ProtocolError):
        apply_transition(TaskState.COMPLETED, "request")
    with pytest.raises(ProtocolError):
        apply_transition(TaskState.COMPLETED, "programmed_stop")


def test_late_result_after_cancel_and_pause(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-s", "org/s", shared)
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    exe = Engine(cfg_e, es_, et, "executor", executor=SimulatedExecutorAdapter())
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    es_.upsert_task(cfg_e.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    # pausa humana antes da nova rodada
    body = "pausa"
    env = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="human",
        sender_id="usuario-responsavel",
        recipient_role="broadcast",
        type=MessageType.PAUSE.value,
        body=body,
    )
    ot.actor = "usuario-responsavel"
    ot.create_comment(issue.number, render_message(env, body))
    orch.tick()
    exe.tick()
    assert os_.get_task(cfg_o.namespace, task_id)["state"] == "PAUSED"
    # cancel
    cbody = "cancel"
    cenv = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="human",
        sender_id="usuario-responsavel",
        recipient_role="broadcast",
        type=MessageType.CANCEL.value,
        body=cbody,
    )
    ot.create_comment(issue.number, render_message(cenv, cbody))
    orch.tick()
    assert os_.get_task(cfg_o.namespace, task_id)["state"] == "CANCELLED"
    # resultado tardio
    rbody = '{"status":"success"}'
    # encontra request se existir
    from ia_orchestrator.protocol import parse_comment

    req = None
    for c in ot.list_issue_comments(issue.number):
        p = parse_comment(c.body)
        if p.envelope and p.envelope.type == "request":
            req = p.envelope
    if req:
        late = build_envelope(
            project_id=cfg_o.project_id,
            repository=cfg_o.github.repository,
            task_id=task_id,
            sender_role="executor",
            sender_id="bot-executor",
            recipient_role="orchestrator",
            type=MessageType.RESULT.value,
            body=rbody,
            in_reply_to=req.message_id,
            request_id=req.request_id,
        )
        ot.actor = "bot-executor"
        ot.create_comment(issue.number, render_message(late, rbody))
        orch.tick()
        assert os_.get_task(cfg_o.namespace, task_id)["state"] == "CANCELLED"
        audits = os_.conn.execute("SELECT event_type FROM audit WHERE namespace=?", (cfg_o.namespace,)).fetchall()
        assert any(a[0] == "late_message" for a in audits)
