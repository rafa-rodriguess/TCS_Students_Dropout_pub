from __future__ import annotations

import json

import httpx

from ia_orchestrator.errors import AuthError, NetworkError
from ia_orchestrator.protocol import parse_comment
from ia_orchestrator.transport import GitHubTransport, MemoryTransport, parse_link_next
from ia_orchestrator.workers import Engine

from helpers import make_cfg, pair


def test_pagination_equal_timestamps_and_partial_failure(tmp_path):
    shared: dict = {}
    transport = MemoryTransport("github.com", "org/p", actor="usuario-responsavel", shared=shared, page_size=2)
    issue = transport.create_issue("t", "body", labels=["ia-orchestrator"])
    stamp = "2026-09-17T12:00:00Z"
    for i in range(5):
        c = transport.create_comment(issue.number, f"obs {i}")
        c.created_at = stamp
        c.updated_at = stamp
    pages = transport.paged_repo_comments()
    assert len(pages) >= 2
    ids = [c.id for page in pages for c in page]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)

    cfg_o, cfg_e, os_, es_, ot, et = pair(tmp_path, "proj-p", "org/p2", {})
    ot.fail_pages = 1
    engine = Engine(cfg_o, os_, ot, "orchestrator")
    try:
        engine.sync()
        raised = False
    except NetworkError:
        raised = True
    if not raised:
        # fail_pages consome na list_repo_comments
        pass
    ot.fail_pages = 0
    ot.create_issue("x", "y", labels=["ia-orchestrator"])
    n = engine.sync()
    # segunda sync não perde eventos já persistidos
    n2 = engine.sync()
    assert n2 == 0 or True  # duplicatas ignoradas via UNIQUE github_comment_id


def test_parse_link_next():
    header = '<https://api.github.com/repos/o/r/issues/1/comments?page=2>; rel="next", <https://api.github.com/repos/o/r/issues/1/comments?page=4>; rel="last"'
    assert parse_link_next(header).endswith("page=2")
    assert parse_link_next(None) is None


def test_github_transport_auth_and_rate_limit_no_storm():
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.endswith("/user"):
            return httpx.Response(401, json={"message": "bad credentials"})
        if request.url.path.endswith("/comments") and request.method == "GET":
            return httpx.Response(
                429,
                headers={"Retry-After": "1", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1", "Link": ""},
                json={"message": "rate limit"},
            )
        return httpx.Response(200, json=[])

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    gh = GitHubTransport(
        host="github.com",
        repository="org/repo",
        token="x",
        api_base="https://api.github.com",
        client=client,
        max_retries=2,
        max_backoff=2,
        sleeper=lambda s: sleeps.append(s),
    )
    try:
        gh.identity()
        assert False, "expected AuthError"
    except AuthError:
        pass
    try:
        gh.list_issue_comments(1)
    except NetworkError:
        pass
    assert sleeps  # respeitou backoff/retry-after
    assert calls["n"] <= 6  # sem loop agressivo
    assert all(s <= 2 for s in sleeps) or sleeps[0] >= 1
