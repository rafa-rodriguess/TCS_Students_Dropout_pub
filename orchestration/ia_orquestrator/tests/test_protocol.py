from __future__ import annotations

from ia_orchestrator.protocol import (
    MessageType,
    QUARANTINE_NOTICE_MARKER,
    build_envelope,
    executor_capabilities_payload,
    canonical_payload,
    parse_comment,
    parse_executor_capabilities,
    render_executor_capabilities,
    render_message,
    sha256_text,
)
from ia_orchestrator.workers import Engine

from helpers import open_task, pair


def test_invalid_envelope_unauthorized_incompatible_and_edit(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-v", "org/v", shared)
    orch = Engine(cfg_o, os_, ot, "orchestrator")
    task_id, issue, env = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")

    ot.actor = "intruso"
    ot.create_comment(issue.number, render_message(
        build_envelope(
            project_id=cfg_o.project_id,
            repository=cfg_o.github.repository,
            task_id=task_id,
            sender_role="human",
            sender_id="intruso",
            recipient_role="orchestrator",
            type=MessageType.PAUSE.value,
            body="pause ilegal",
        ),
        "pause ilegal",
    ))

    ot.actor = "usuario-responsavel"
    ot.create_comment(issue.number, "<!-- ia-orchestrator:message:v1 -->\n```json\n{not json}\n```\n<!-- ia-orchestrator:body -->\nx\n<!-- ia-orchestrator:end -->\n")
    ot.create_comment(issue.number, "<!-- ia-orchestrator:message:v9 -->\n```json\n{}\n```\n<!-- ia-orchestrator:body -->\nx\n<!-- ia-orchestrator:end -->\n")

    orch.tick()
    reasons = [q["reason"] for q in os_.list_quarantine(cfg_o.namespace)]
    assert any("não autorizado" in r for r in reasons)
    assert any("inválido" in r.lower() or "envelope" in r.lower() for r in reasons)
    assert any("incompatível" in r or "v9" in r for r in reasons)

    comments = [c for c in ot.list_issue_comments(issue.number) if parse_comment(c.body).envelope and parse_comment(c.body).envelope.type == "task_open"]
    assert comments
    original = comments[0]
    ot.edit_comment(original.id, original.body + "\neditado")
    orch.tick()
    msg = os_.get_message_by_github(cfg_o.namespace, original.id)
    assert msg["hash_diverged"] == 1
    # observação sem envelope
    ot.create_comment(issue.number, "apenas um comentário humano")
    orch.tick()
    obs = [m for m in os_.messages_for_task(cfg_o.namespace, task_id) if False]
    rows = os_.conn.execute("SELECT kind FROM messages WHERE namespace=? AND kind='observation'", (cfg_o.namespace,)).fetchall()
    assert rows


def test_quarantine_posts_issue_comment_on_hash_mismatch(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-hash-q", "org/hash-q", shared)
    orch = Engine(cfg_o, os_, ot, "orchestrator")
    exec_engine = Engine(cfg_e, es_, et, "executor")
    task_id, issue, env = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")

    body = "pedido real"
    bad_env = build_envelope(
        project_id=cfg_o.project_id,
        repository=cfg_o.github.repository,
        task_id=task_id,
        sender_role="orchestrator",
        sender_id="bot-orquestrador",
        recipient_role="executor",
        type=MessageType.REQUEST.value,
        body=body,
        request_id="11111111-1111-1111-1111-111111111111",
        in_reply_to=env.message_id,
    )
    rendered = render_message(bad_env, body)
    rendered = rendered.replace(bad_env.payload_sha256, "0" * 64)
    bad = ot.create_comment(issue.number, rendered)

    orch.tick()
    notices = [c for c in ot.list_issue_comments(issue.number) if QUARANTINE_NOTICE_MARKER in c.body]
    assert len(notices) == 1
    assert "payload_sha256" in notices[0].body
    assert f"source-comment-id: {bad.id}" in notices[0].body
    expected = sha256_text(canonical_payload(body))
    assert expected in notices[0].body
    assert "0" * 64 in notices[0].body

    orch.tick()
    exec_engine.tick()
    notices_after = [c for c in ot.list_issue_comments(issue.number) if QUARANTINE_NOTICE_MARKER in c.body]
    assert len(notices_after) == 1
    parsed = parse_comment(notices_after[0].body)
    assert parsed.kind == "observation"


def test_invalid_envelope_posts_quarantine_notices(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-q-note", "org/q-note", shared)
    orch = Engine(cfg_o, os_, ot, "orchestrator")
    task_id, issue, env = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    ot.create_comment(
        issue.number,
        "<!-- ia-orchestrator:message:v1 -->\n```json\n{not json}\n```\n<!-- ia-orchestrator:body -->\nx\n<!-- ia-orchestrator:end -->\n",
    )
    orch.tick()
    notices = [c for c in ot.list_issue_comments(issue.number) if QUARANTINE_NOTICE_MARKER in c.body]
    assert len(notices) == 1
    assert "não executável" in notices[0].body.lower() or "Quarentena" in notices[0].body


def test_recovery_control_messages_round_trip():
    for message_type in (MessageType.NON_BLOCKING.value, MessageType.PROGRAMMED_STOP.value):
        body = f"controle {message_type}"
        env = build_envelope(
            project_id="proj-control",
            repository="org/control",
            task_id="task-active",
            sender_role="orchestrator",
            sender_id="bot-orquestrador",
            recipient_role="executor",
            type=message_type,
            body=body,
            request_id=f"req-{message_type}",
            in_reply_to="primary-request-message",
        )
        parsed = parse_comment(render_message(env, body))
        assert parsed.kind == "envelope"
        assert parsed.envelope is not None
        assert parsed.envelope.type == message_type
        assert parsed.envelope.request_id == f"req-{message_type}"

    result_body = '{"status":"blocked","summary":"interference risk"}'
    result = build_envelope(
        project_id="proj-control",
        repository="org/control",
        task_id="task-active",
        sender_role="executor",
        sender_id="bot-executor",
        recipient_role="orchestrator",
        type=MessageType.CONTROL_RESULT.value,
        body=result_body,
        request_id="req-non_blocking",
        in_reply_to="control-message",
    )
    parsed_result = parse_comment(render_message(result, result_body))
    assert parsed_result.kind == "envelope"
    assert parsed_result.envelope is not None
    assert parsed_result.envelope.type == MessageType.CONTROL_RESULT.value


def test_executor_capabilities_round_trip():
    rendered = render_executor_capabilities()
    parsed = parse_executor_capabilities("## ACK\n\n" + rendered + "\n")
    assert parsed == executor_capabilities_payload()
    assert parsed["util_version"] == "3.08"
    assert "send_file" in parsed["features"]
    assert "get_file" in parsed["features"]
    assert "non_blocking" in parsed["message_types"]
    assert "programmed_stop" in parsed["message_types"]
    assert "control_result" in parsed["message_types"]
    assert parsed["features"] == ["send_file", "get_file"]


def test_executor_capabilities_missing_or_malformed_returns_none():
    assert parse_executor_capabilities("## ACK\nlegacy executor") is None
    assert parse_executor_capabilities(
        '<!-- ia-orchestrator:executor-capabilities:v1 {not-json} -->'
    ) is None
