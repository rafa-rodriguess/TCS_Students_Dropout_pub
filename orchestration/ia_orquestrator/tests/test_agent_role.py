"""Agent role: real three-role MemoryTransport integration; no paid models or real data."""
from __future__ import annotations

import pytest

from helpers import make_cfg, open_task, pair
from ia_orchestrator.errors import PolicyError, ProtocolError
from ia_orchestrator.loop import (
    STATUS_IDLE, STATUS_JOB, STATUS_RECOVERY, complete_agent_discussion,
    inspect, pending_rows, running_dir, sentinel_for, tick,
)
from ia_orchestrator.persistence import Store
from ia_orchestrator.protocol import (
    MessageType, build_envelope, parse_comment, render_message,
)
from ia_orchestrator.transport import MemoryTransport
from ia_orchestrator.workers import Engine


def test_agent_protocol_round_trip_and_forbidden_routes():
    body = "## Discussão\n- pergunta: verificar contrato?\n- execução: não ordenar e não executar"
    discussion = build_envelope(
        project_id="p", repository="org/p", task_id="task", sender_role="orchestrator",
        sender_id="bot-orquestrador", recipient_role="agent",
        type="discuss", body=body, request_id="discussion-a",
    )
    parsed = parse_comment(render_message(discussion, body))
    assert parsed.kind == "envelope"
    reply_body = "## Parecer\n- status: answered\n- efeito_na_executora: nenhum"
    reply = build_envelope(
        project_id="p", repository="org/p", task_id="task", sender_role="agent",
        sender_id="bot-agent", recipient_role="orchestrator", type="analysis",
        body=reply_body, request_id="discussion-a", in_reply_to=discussion.message_id,
    )
    assert parse_comment(render_message(reply, reply_body)).kind == "envelope"
    for sender,recipient,kind in (
        ("agent","executor","request"),
        ("agent","orchestrator","result"),
        ("executor","agent","request"),
        ("agent","orchestrator","complete"),
    ):
        bad = build_envelope(
            project_id="p", repository="org/p", task_id="task", sender_role=sender,
            sender_id="bad", recipient_role=recipient, type=kind, body="bad",
            request_id="discussion-a", in_reply_to=discussion.message_id,
        )
        with pytest.raises(ProtocolError):
            render_message(bad, "bad")
    missing_parent = build_envelope(
        project_id="p", repository="org/p", task_id="task", sender_role="agent",
        sender_id="bot-agent", recipient_role="orchestrator", type="analysis",
        body=reply_body, request_id="discussion-a",
    )
    with pytest.raises(ProtocolError):
        render_message(missing_parent, reply_body)


def test_agent_parallel_routing_and_state_isolation(tmp_path):
    shared = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path,"agent-proj","org/agent",shared)
    cfg_a = make_cfg(tmp_path,"agent-proj","org/agent")
    for cfg in (cfg_o,cfg_e,cfg_a):
        cfg.github.allowed_senders.agent = ["bot-agent"]
    cfg_o.orchestrator.mode = "manual"
    cfg_e.executor.mode = "cursor_chat"
    as_ = Store(tmp_path/"agent.sqlite")
    at = MemoryTransport("github.com","org/agent",actor="bot-agent",shared=shared)
    orch = Engine(cfg_o,os_,ot,"orchestrator")
    executor = Engine(cfg_e,es_,et,"executor")
    agent = Engine(cfg_a,as_,at,"agent")
    task_id, issue, _ = open_task(ot,cfg_o,"run primary")
    for store,cfg in ((os_,cfg_o),(es_,cfg_e),(as_,cfg_a)):
        store.upsert_task(cfg.namespace,task_id,issue_number=issue.number,title="task")
    orch.sync()
    task = os_.get_task(cfg_o.namespace,task_id)
    orch._publish(task,MessageType.REQUEST.value,"primary request",
                  recipient="executor",request_id="execution-1")
    orch.flush_outbox()
    orch.sync()
    orch.process_inbox()
    executor.sync()
    request_before = pending_rows(es_,cfg_e.namespace,"executor")
    assert len(request_before) == 1
    assert request_before[0]["request_id"] == "execution-1"

    discuss_body = "## Discussão\n- pergunta: há suporte?\n- execução: não ordenar e não executar"
    discuss = orch._publish(task,"discuss",discuss_body,recipient="agent",request_id="discussion-1")
    orch.flush_outbox()
    agent.sync()
    executor.sync()
    assert len(pending_rows(es_,cfg_e.namespace,"executor")) == 1
    assert len(pending_rows(as_,cfg_a.namespace,"agent")) == 1
    assert sentinel_for("agent") == "AGENT_LOOP_TICK_agent"
    assert running_dir(cfg_a,tmp_path/"host-agent","agent") != running_dir(cfg_e,tmp_path/"host-agent","executor")
    a_snap = tick(cfg_a,as_,agent,"agent",tmp_path/"host-agent",do_claim=True)
    assert a_snap["status"] == STATUS_RECOVERY
    assert a_snap["sentinel"].startswith("AGENT_LOOP_TICK_agent")
    assert not list(running_dir(cfg_a,tmp_path/"host-agent","executor").glob("*.md"))
    agent_task = as_.get_task(cfg_a.namespace,task_id)
    reply = agent._publish(
        agent_task,"analysis","## Parecer\n- status: answered\n- efeito_na_executora: nenhum",
        recipient="orchestrator",request_id="discussion-1",in_reply_to=discuss.message_id,
    )
    agent.flush_outbox()
    complete_agent_discussion(cfg_a,as_,tmp_path/"host-agent",discuss.message_id)
    assert inspect(cfg_a,as_,"agent",tmp_path/"host-agent")["status"] == STATUS_IDLE

    agent_remote = Store(tmp_path/"agent-fresh.sqlite")
    agent_fresh = Engine(cfg_a,agent_remote,at,"agent")
    agent_fresh.sync()
    assert pending_rows(agent_remote,cfg_a.namespace,"agent") == []
    state_before = os_.get_task(cfg_o.namespace,task_id)["state"]
    orch.sync()
    assert pending_rows(os_,cfg_o.namespace,"orchestrator")[0]["type"] == "analysis"
    orch.process_inbox()
    assert os_.get_task(cfg_o.namespace,task_id)["state"] == state_before
    assert pending_rows(es_,cfg_e.namespace,"executor")[0]["request_id"] == "execution-1"
    assert not any(m["type"]=="analysis" for m in pending_rows(es_,cfg_e.namespace,"executor"))


def test_agent_does_not_claim_primary_task(tmp_path):
    cfg = make_cfg(tmp_path,"agent-safe","org/agent-safe")
    store = Store(tmp_path/"safe.sqlite")
    transport = MemoryTransport("github.com","org/agent-safe",actor="bot-agent")
    engine = Engine(cfg,store,transport,"agent")
    assert engine.cursor_chat_mode()
    assert engine.tick()["processed"] == 0
    with pytest.raises(PolicyError):
        engine._publish({"task_id":"bad","issue_number":1},"request","execute",recipient="executor")


def test_agent_does_not_flush_primary_shared_outbox(tmp_path):
    cfg = make_cfg(tmp_path, "agent-shared", "org/agent-shared")
    store = Store(tmp_path / "one-host.sqlite")
    transport = MemoryTransport("github.com", "org/agent-shared", actor="bot-agent")
    issue = transport.create_issue("job", "plain task", labels=["ia-orchestrator"])
    store.upsert_task(cfg.namespace, "task-a", issue_number=issue.number, title="job")
    task = store.get_task(cfg.namespace, "task-a")
    orchestrator = Engine(cfg, store, transport, "orchestrator")
    agent = Engine(cfg, store, transport, "agent")
    orchestrator._publish(task, "request", "Do the primary job",
                          recipient="executor", request_id="primary-id")
    assert len(store.pending_outbox(cfg.namespace)) == 1
    assert agent.flush_outbox() == 0
    assert transport.list_issue_comments(issue.number) == []
    # The agent must not close the issue or publish a primary request.
    assert transport.get_issue(issue.number).state == "open"
