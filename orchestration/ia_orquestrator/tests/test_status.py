from __future__ import annotations

import pytest

from ia_orchestrator.cli import request_execution_status
from ia_orchestrator.errors import UsageError
from ia_orchestrator.protocol import MessageType, build_envelope, new_id, parse_comment, render_message, status_telemetry_body

from helpers import open_task, pair


def test_status_publishes_fixed_non_blocking_only_while_running(tmp_path):
    shared: dict = {}
    cfg, _cfg_e, store, _exec_store, transport, _exec_t = pair(tmp_path, "exemplo", "org/repo", shared)
    task_id, issue, _env = open_task(transport, cfg, "objetivo")
    store.upsert_task(cfg.namespace, task_id, issue_number=issue.number, title="tarefa")
    store.set_task_state(cfg.namespace, task_id, "RUNNING")
    primary_id = new_id()
    primary = build_envelope(
        project_id=cfg.project_id,
        repository=cfg.github.repository,
        task_id=task_id,
        sender_role="orchestrator",
        sender_id="bot-orquestrador",
        recipient_role="executor",
        type=MessageType.REQUEST.value,
        body="pedido primario",
        request_id=primary_id,
    )
    transport.actor = "bot-orquestrador"
    transport.create_comment(issue.number, render_message(primary, "pedido primario"))

    before = len(transport.list_issue_comments(issue.number))
    with pytest.raises(UsageError, match="nada foi publicado"):
        request_execution_status(cfg, store, transport, task_id)
    assert len(transport.list_issue_comments(issue.number)) == before

    transport.set_issue_status_label(issue.number, "running")
    payload = request_execution_status(cfg, store, transport, task_id)
    assert payload["published"] is True
    assert payload["type"] == "non_blocking"
    assert payload["request_id"] != primary_id
    assert payload["in_reply_to"] == primary.message_id
    assert store.get_task(cfg.namespace, task_id)["state"] == "RUNNING"

    parsed = parse_comment(transport.list_issue_comments(issue.number)[-1].body)
    assert parsed.envelope is not None
    assert parsed.envelope.type == "non_blocking"
    assert parsed.envelope.request_id == payload["request_id"]
    assert parsed.body == status_telemetry_body().strip("\n")

    transport.set_issue_status_label(issue.number, "waiting-orchestrator")
    after = len(transport.list_issue_comments(issue.number))
    with pytest.raises(UsageError, match="nada foi publicado"):
        request_execution_status(cfg, store, transport, task_id)
    assert len(transport.list_issue_comments(issue.number)) == after
