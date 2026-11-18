from __future__ import annotations

import json

import httpx

from ia_orchestrator.adapters.model import OpenAICompatModelAdapter, SimulatedModelAdapter, parse_model_decision
from ia_orchestrator.errors import PolicyError, ProtocolError
from ia_orchestrator.policy import check_limits
from ia_orchestrator.workers import Engine

from helpers import make_cfg, open_task, pair


def test_limits_and_invalid_model_output(tmp_path):
    shared: dict = {}
    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-l", "org/l", shared)
    cfg_o.limits.max_rounds_per_task = 0
    orch = Engine(cfg_o, os_, ot, "orchestrator", model=SimulatedModelAdapter())
    task_id, issue, _ = open_task(ot, cfg_o, "objetivo")
    os_.upsert_task(cfg_o.namespace, task_id, issue_number=issue.number, title="t")
    orch.tick()
    from ia_orchestrator.protocol import parse_comment

    types = [parse_comment(c.body).envelope.type for c in ot.list_issue_comments(issue.number) if parse_comment(c.body).envelope]
    assert "pause" in types

    cfg_o.limits.max_rounds_per_task = 10
    cfg_o2, cfg_e2, os2, es2, ot2, et2 = pair(tmp_path, "proj-l2", "org/l2", {})
    orch2 = Engine(cfg_o2, os2, ot2, "orchestrator", model=SimulatedModelAdapter(invalid=True))
    task_id2, issue2, _ = open_task(ot2, cfg_o2, "objetivo")
    os2.upsert_task(cfg_o2.namespace, task_id2, issue_number=issue2.number, title="t")
    orch2.tick()
    types2 = [parse_comment(c.body).envelope.type for c in ot2.list_issue_comments(issue2.number) if parse_comment(c.body).envelope]
    assert "pause" in types2


def test_check_limits_budget_and_calls():
    from ia_orchestrator.config import LimitsSection, ProjectConfig, example_config_dict
    from pathlib import Path

    data = example_config_dict("p", "o/r", "/tmp")
    data["limits"]["budget_usd_per_task"] = 1.0
    data["limits"]["max_model_calls_per_task"] = 2
    cfg = ProjectConfig.model_validate(data)
    assert check_limits(cfg, rounds=0, revisions=0, usage={"calls": 2})
    assert check_limits(cfg, rounds=0, revisions=0, usage={"calls": 0, "cost_usd": 2.0, "all_known": 1})
    assert check_limits(cfg, rounds=0, revisions=0, usage={"calls": 0, "cost_usd": 2.0, "all_known": 0}) is None  # custo desconhecido


def test_openai_compat_adapter_parses_usage(tmp_path):
    cfg = make_cfg(tmp_path, "p", "o/r")
    cfg.orchestrator.api_key_env = "LLM_API_KEY"
    import os

    os.environ["LLM_API_KEY"] = "sk-test"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert "messages" in body
        assert body["model"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"schema_version": 1, "decision": "pause", "rationale": "x"})}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
        )

    client = httpx.Client(base_url="https://api.openai.com/v1", transport=httpx.MockTransport(handler))
    adapter = OpenAICompatModelAdapter(cfg, client=client)
    result = adapter.complete({"objective": "x"})
    assert result.decision.decision == "pause"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 4


def test_parse_model_decision_rejects_garbage():
    try:
        parse_model_decision("nope")
        assert False
    except ProtocolError:
        pass
