"""Transporte GitHub (polling) e transporte em memória para testes."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

import httpx

from ia_orchestrator.errors import AuthError, NetworkError
from ia_orchestrator.issue_status import merge_status_labels
from ia_orchestrator.protocol import MARKER_START, parse_comment

GITHUB_API_VERSION = "2022-11-28"
ACCEPT = "application/vnd.github+json"
USER_AGENT = "ia-orchestrator/0.1.0"


def parse_link_next(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' in section:
            start = section.find("<")
            end = section.find(">")
            if start >= 0 and end > start:
                return section[start + 1 : end]
    return None


def _sleep(seconds: float, sleeper: Callable[[float], None] | None = None) -> None:
    (sleeper or time.sleep)(seconds)


def compute_backoff(attempt: int, base: float = 1.0, cap: float = 300.0) -> float:
    return min(cap, base * (2 ** attempt)) * (0.5 + random.random() / 2.0)


@dataclass
class RemoteComment:
    id: int
    issue_number: int
    body: str
    user_login: str
    created_at: str
    updated_at: str
    html_url: str = ""


@dataclass
class RemoteIssue:
    id: int
    number: int
    title: str
    body: str
    state: str
    user_login: str
    html_url: str = ""
    labels: list[str] = field(default_factory=list)


class Transport(Protocol):
    host: str
    repository: str

    def identity(self) -> dict[str, Any]: ...
    def get_repository(self) -> dict[str, Any]: ...
    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> RemoteIssue: ...
    def get_issue(self, number: int) -> RemoteIssue: ...
    def list_issue_comments(self, number: int, since: str | None = None) -> list[RemoteComment]: ...
    def list_repo_comments(self, since: str | None = None) -> list[RemoteComment]: ...
    def create_comment(self, number: int, body: str) -> RemoteComment: ...
    def find_comment_by_message_id(self, number: int, message_id: str) -> RemoteComment | None: ...
    def list_issues(self, labels: list[str] | None = None, state: str = "open") -> list[RemoteIssue]: ...
    def close_issue(self, number: int) -> None: ...
    def set_issue_status_label(self, number: int, status: str) -> None: ...


class GitHubTransport:
    """Cliente HTTP da API REST de Issues/comentários.

    Endpoints oficiais (docs.github.com/en/rest/issues):
    - POST /repos/{owner}/{repo}/issues
    - GET  /repos/{owner}/{repo}/issues/{issue_number}
    - GET  /repos/{owner}/{repo}/issues/{issue_number}/comments
    - POST /repos/{owner}/{repo}/issues/{issue_number}/comments
    - PATCH /repos/{owner}/{repo}/issues/{issue_number}  (fecho; labels status:*)
    - GET  /repos/{owner}/{repo}/issues/comments
    Paginação pelo header Link rel=next. Rate limit via x-ratelimit-* e Retry-After.
    """

    def __init__(
        self,
        *,
        host: str,
        repository: str,
        token: str,
        api_base: str,
        timeout: float = 30.0,
        max_retries: int = 5,
        max_backoff: float = 300.0,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] | None = None,
        on_retry: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.host = host
        self.repository = repository
        self.owner, self.repo = repository.split("/", 1)
        self.api_base = api_base.rstrip("/")
        self.max_retries = max_retries
        self.max_backoff = max_backoff
        self._sleeper = sleeper
        self._on_retry = on_retry
        self._client = client or httpx.Client(
            base_url=self.api_base,
            timeout=timeout,
            headers={
                "Accept": ACCEPT,
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": USER_AGENT,
            },
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                last_exc = NetworkError(f"timeout HTTP {method} {url}: {exc}")
                self._backoff(attempt, None, "timeout")
                continue
            except httpx.HTTPError as exc:
                last_exc = NetworkError(str(exc))
                self._backoff(attempt, None, "http_error")
                continue
            if response.status_code == 401:
                raise AuthError("autenticação GitHub inválida (401); verifique o token e o token_env")
            if response.status_code == 403 and "rate limit" in response.text.lower():
                self._respect_rate_limit(response, attempt)
                last_exc = NetworkError("rate limit GitHub")
                continue
            if response.status_code == 429:
                self._respect_rate_limit(response, attempt)
                last_exc = NetworkError("rate limit GitHub (429)")
                continue
            if response.status_code == 410:
                raise NetworkError("Issues desabilitadas neste repositório (410 Gone)")
            if response.status_code >= 500:
                last_exc = NetworkError(f"GitHub {response.status_code}")
                self._backoff(attempt, response, "server")
                continue
            if response.status_code >= 400:
                raise NetworkError(f"GitHub {response.status_code}: {response.text[:500]}")
            return response
        raise last_exc or NetworkError("falha HTTP esgotou retries")

    def _respect_rate_limit(self, response: httpx.Response, attempt: int) -> None:
        retry_after = response.headers.get("Retry-After")
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        wait = None
        if retry_after:
            try:
                wait = float(retry_after)
            except ValueError:
                wait = 60.0
        elif remaining == "0" and reset:
            try:
                reset_ts = int(reset)
                wait = max(1.0, reset_ts - time.time())
            except ValueError:
                wait = 60.0
        else:
            wait = max(60.0, compute_backoff(attempt, cap=self.max_backoff))
        wait = min(wait, self.max_backoff)
        if self._on_retry:
            self._on_retry({"reason": "rate_limit", "wait": wait, "attempt": attempt, "remaining": remaining})
        _sleep(wait, self._sleeper)

    def _backoff(self, attempt: int, response: httpx.Response | None, reason: str) -> None:
        if attempt >= self.max_retries:
            return
        wait = compute_backoff(attempt, cap=self.max_backoff)
        if self._on_retry:
            self._on_retry({"reason": reason, "wait": wait, "attempt": attempt})
        _sleep(wait, self._sleeper)

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        items: list[Any] = []
        url: str | None = path
        query = params
        while url:
            response = self._request("GET", url, params=query)
            data = response.json()
            if not isinstance(data, list):
                raise NetworkError("resposta de listagem não é uma lista")
            items.extend(data)
            next_url = parse_link_next(response.headers.get("Link"))
            url = next_url
            query = None  # a URL next já contém os parâmetros
        return items

    def identity(self) -> dict[str, Any]:
        response = self._request("GET", "/user")
        data = response.json()
        return {"login": data.get("login"), "id": data.get("id"), "type": data.get("type")}

    def get_repository(self) -> dict[str, Any]:
        response = self._request("GET", f"/repos/{self.owner}/{self.repo}")
        return response.json()

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> RemoteIssue:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        response = self._request("POST", f"/repos/{self.owner}/{self.repo}/issues", json=payload)
        return _issue_from_api(response.json())

    def get_issue(self, number: int) -> RemoteIssue:
        response = self._request("GET", f"/repos/{self.owner}/{self.repo}/issues/{number}")
        return _issue_from_api(response.json())

    def close_issue(self, number: int) -> None:
        self._request(
            "PATCH",
            f"/repos/{self.owner}/{self.repo}/issues/{number}",
            json={"state": "closed"},
        )

    def set_issue_status_label(self, number: int, status: str) -> None:
        issue = self.get_issue(number)
        labels = merge_status_labels(issue.labels, status)
        self._request(
            "PATCH",
            f"/repos/{self.owner}/{self.repo}/issues/{number}",
            json={"labels": labels},
        )

    def list_issues(self, labels: list[str] | None = None, state: str = "open") -> list[RemoteIssue]:
        params: dict[str, Any] = {"per_page": 100, "state": state}
        if labels:
            params["labels"] = ",".join(labels)
        raw = self._paginate(f"/repos/{self.owner}/{self.repo}/issues", params)
        return [_issue_from_api(item) for item in raw if not item.get("pull_request")]

    def list_issue_comments(self, number: int, since: str | None = None) -> list[RemoteComment]:
        params = {"per_page": 100}
        if since:
            params["since"] = since
        raw = self._paginate(f"/repos/{self.owner}/{self.repo}/issues/{number}/comments", params)
        return [_comment_from_api(item, number) for item in raw]

    def list_repo_comments(self, since: str | None = None) -> list[RemoteComment]:
        params: dict[str, Any] = {"per_page": 100, "sort": "created", "direction": "asc"}
        if since:
            params["since"] = since
        raw = self._paginate(f"/repos/{self.owner}/{self.repo}/issues/comments", params)
        comments = []
        for item in raw:
            issue_url = item.get("issue_url") or ""
            number = _issue_number_from_url(issue_url)
            comments.append(_comment_from_api(item, number))
        return comments

    def create_comment(self, number: int, body: str) -> RemoteComment:
        response = self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/issues/{number}/comments",
            json={"body": body},
        )
        return _comment_from_api(response.json(), number)

    def find_comment_by_message_id(self, number: int, message_id: str) -> RemoteComment | None:
        for comment in self.list_issue_comments(number):
            parsed = parse_comment(comment.body)
            if parsed.envelope and parsed.envelope.message_id == message_id:
                return comment
            if f'"message_id": "{message_id}"' in comment.body or f'"message_id":"{message_id}"' in comment.body:
                return comment
        return None


def _issue_from_api(data: dict[str, Any]) -> RemoteIssue:
    user = data.get("user") or {}
    labels = []
    for lab in data.get("labels") or []:
        if isinstance(lab, dict):
            labels.append(str(lab.get("name", "")))
        else:
            labels.append(str(lab))
    return RemoteIssue(
        id=int(data["id"]),
        number=int(data["number"]),
        title=data.get("title") or "",
        body=data.get("body") or "",
        state=data.get("state") or "open",
        user_login=user.get("login") or "",
        html_url=data.get("html_url") or "",
        labels=labels,
    )


def _comment_from_api(data: dict[str, Any], issue_number: int) -> RemoteComment:
    user = data.get("user") or {}
    return RemoteComment(
        id=int(data["id"]),
        issue_number=issue_number,
        body=data.get("body") or "",
        user_login=user.get("login") or "",
        created_at=data.get("created_at") or "",
        updated_at=data.get("updated_at") or data.get("created_at") or "",
        html_url=data.get("html_url") or "",
    )


def _issue_number_from_url(issue_url: str) -> int:
    path = urlparse(issue_url).path.rstrip("/")
    try:
        return int(path.rsplit("/", 1)[-1])
    except ValueError:
        return 0


class MemoryTransport:
    """GitHub simulado em memória. Isolado por host+repositório."""

    def __init__(
        self,
        host: str,
        repository: str,
        *,
        actor: str = "bot-orquestrador",
        has_issues: bool = True,
        page_size: int = 100,
        fail_pages: int = 0,
        timeout_after_create: bool = False,
        auth_ok: bool = True,
        rate_limit_remaining: int | None = None,
        shared: dict[str, Any] | None = None,
    ) -> None:
        self.host = host
        self.repository = repository
        self.actor = actor
        self.has_issues = has_issues
        self.page_size = page_size
        self.fail_pages = fail_pages
        self.timeout_after_create = timeout_after_create
        self.auth_ok = auth_ok
        self.rate_limit_remaining = rate_limit_remaining
        self.shared = shared if shared is not None else {}
        bucket = self._bucket()
        bucket.setdefault("issues", {})
        bucket.setdefault("comments", {})
        bucket.setdefault("next_issue", 1)
        bucket.setdefault("next_comment", 1)

    def _bucket(self) -> dict[str, Any]:
        key = f"{self.host.lower()}|{self.repository.lower()}"
        return self.shared.setdefault(key, {})

    def identity(self) -> dict[str, Any]:
        if not self.auth_ok:
            raise AuthError("autenticação GitHub inválida (401)")
        return {"login": self.actor, "id": 1, "type": "Bot"}

    def get_repository(self) -> dict[str, Any]:
        if not self.auth_ok:
            raise AuthError("autenticação GitHub inválida (401)")
        return {
            "full_name": self.repository,
            "has_issues": self.has_issues,
            "permissions": {"admin": False, "push": False, "pull": True},
        }

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> RemoteIssue:
        if not self.auth_ok:
            raise AuthError("autenticação GitHub inválida (401)")
        if not self.has_issues:
            raise NetworkError("Issues desabilitadas neste repositório (410 Gone)")
        bucket = self._bucket()
        number = bucket["next_issue"]
        bucket["next_issue"] = number + 1
        issue_id = 1000 + number
        issue = RemoteIssue(
            id=issue_id,
            number=number,
            title=title,
            body=body,
            state="open",
            user_login=self.actor,
            html_url=f"https://{self.host}/{self.repository}/issues/{number}",
            labels=list(labels or []),
        )
        bucket["issues"][number] = issue
        return issue

    def get_issue(self, number: int) -> RemoteIssue:
        issue = self._bucket()["issues"].get(number)
        if not issue:
            raise NetworkError(f"issue {number} não encontrada")
        return issue

    def list_issues(self, labels: list[str] | None = None, state: str = "open") -> list[RemoteIssue]:
        issues = list(self._bucket()["issues"].values())
        if state != "all":
            issues = [i for i in issues if i.state == state]
        if labels:
            issues = [i for i in issues if set(labels) <= set(i.labels)]
        return sorted(issues, key=lambda i: i.number)

    def close_issue(self, number: int) -> None:
        issue = self.get_issue(number)
        issue.state = "closed"

    def set_issue_status_label(self, number: int, status: str) -> None:
        issue = self.get_issue(number)
        issue.labels = merge_status_labels(list(issue.labels), status)

    def list_issue_comments(self, number: int, since: str | None = None) -> list[RemoteComment]:
        comments = [c for c in self._bucket()["comments"].values() if c.issue_number == number]
        comments.sort(key=lambda c: c.id)
        return self._filter_since(comments, since)

    def list_repo_comments(self, since: str | None = None) -> list[RemoteComment]:
        if self.fail_pages > 0:
            self.fail_pages -= 1
            raise NetworkError("falha parcial de sincronização")
        comments = list(self._bucket()["comments"].values())
        comments.sort(key=lambda c: c.id)
        filtered = self._filter_since(comments, since)
        # simula paginação: devolve tudo; testes usam page_size via paged_repo_comments
        return filtered

    def paged_repo_comments(self, since: str | None = None) -> list[list[RemoteComment]]:
        items = self.list_repo_comments(since)
        pages = [items[i : i + self.page_size] for i in range(0, len(items), self.page_size)] or [[]]
        return pages

    def create_comment(self, number: int, body: str) -> RemoteComment:
        if not self.auth_ok:
            raise AuthError("autenticação GitHub inválida (401)")
        bucket = self._bucket()
        if number not in bucket["issues"]:
            raise NetworkError(f"issue {number} não encontrada")
        cid = bucket["next_comment"]
        bucket["next_comment"] = cid + 1
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        comment = RemoteComment(
            id=cid,
            issue_number=number,
            body=body,
            user_login=self.actor,
            created_at=now,
            updated_at=now,
            html_url=f"https://{self.host}/{self.repository}/issues/{number}#issuecomment-{cid}",
        )
        bucket["comments"][cid] = comment
        if self.timeout_after_create:
            self.timeout_after_create = False
            raise NetworkError("timeout HTTP POST comments após possível sucesso remoto")
        return comment

    def edit_comment(self, comment_id: int, body: str) -> None:
        comment = self._bucket()["comments"][comment_id]
        comment.body = body
        comment.updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def find_comment_by_message_id(self, number: int, message_id: str) -> RemoteComment | None:
        for comment in self.list_issue_comments(number):
            parsed = parse_comment(comment.body)
            if parsed.envelope and parsed.envelope.message_id == message_id:
                return comment
        return None

    def _filter_since(self, comments: list[RemoteComment], since: str | None) -> list[RemoteComment]:
        if not since:
            return comments
        return [c for c in comments if c.updated_at >= since or c.created_at >= since]


def overlap_since(cursor_since: str | None, overlap_seconds: int) -> str | None:
    if not cursor_since:
        return None
    try:
        stamp = datetime.fromisoformat(cursor_since.replace("Z", "+00:00"))
    except ValueError:
        return cursor_since
    earlier = stamp - timedelta(seconds=overlap_seconds)
    return earlier.replace(microsecond=0).isoformat().replace("+00:00", "Z")
