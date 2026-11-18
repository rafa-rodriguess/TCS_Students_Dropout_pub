"""Persistência SQLite: inbox, outbox, tarefas, execuções, auditoria e migrações."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ia_orchestrator.protocol import Envelope, utc_now
from ia_orchestrator.state import DeliveryState, ExecutionState, RequestState, TaskState

MIGRATIONS = [
    """
    CREATE TABLE schema_migrations (
      version INTEGER PRIMARY KEY,
      applied_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE tasks (
      namespace TEXT NOT NULL,
      task_id TEXT NOT NULL,
      issue_number INTEGER,
      github_issue_id INTEGER,
      state TEXT NOT NULL,
      previous_state TEXT,
      resume_state TEXT,
      title TEXT,
      objective TEXT,
      context_revision TEXT,
      github_state TEXT,
      round_count INTEGER NOT NULL DEFAULT 0,
      revision_count INTEGER NOT NULL DEFAULT 0,
      active_request_id TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      closed_at TEXT,
      PRIMARY KEY (namespace, task_id)
    );
    """,
    """
    CREATE TABLE messages (
      namespace TEXT NOT NULL,
      message_id TEXT NOT NULL,
      task_id TEXT,
      github_comment_id INTEGER,
      issue_number INTEGER,
      type TEXT,
      sender_role TEXT,
      sender_id TEXT,
      github_login TEXT,
      recipient_role TEXT,
      request_id TEXT,
      in_reply_to TEXT,
      attempt INTEGER,
      created_at TEXT,
      observed_at TEXT NOT NULL,
      observed_hash TEXT NOT NULL,
      current_hash TEXT NOT NULL,
      hash_diverged INTEGER NOT NULL DEFAULT 0,
      envelope_json TEXT,
      body_text TEXT,
      raw_body TEXT,
      processed_at TEXT,
      kind TEXT NOT NULL,
      quarantine_reason TEXT,
      PRIMARY KEY (namespace, message_id)
    );
    CREATE UNIQUE INDEX idx_messages_github
      ON messages(namespace, github_comment_id)
      WHERE github_comment_id IS NOT NULL;
    """,
    """
    CREATE TABLE events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      namespace TEXT NOT NULL,
      github_comment_id INTEGER,
      issue_number INTEGER,
      observed_at TEXT NOT NULL,
      payload_json TEXT,
      UNIQUE (namespace, github_comment_id)
    );
    """,
    """
    CREATE TABLE outbox (
      namespace TEXT NOT NULL,
      message_id TEXT NOT NULL,
      task_id TEXT NOT NULL,
      issue_number INTEGER,
      body TEXT NOT NULL,
      status TEXT NOT NULL,
      github_comment_id INTEGER,
      attempts INTEGER NOT NULL DEFAULT 0,
      last_error TEXT,
      created_at TEXT NOT NULL,
      published_at TEXT,
      PRIMARY KEY (namespace, message_id)
    );
    """,
    """
    CREATE TABLE requests (
      namespace TEXT NOT NULL,
      request_id TEXT NOT NULL,
      task_id TEXT NOT NULL,
      message_id TEXT,
      attempt INTEGER NOT NULL DEFAULT 1,
      status TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      blocked_by_question TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (namespace, request_id)
    );
    CREATE UNIQUE INDEX idx_requests_idem
      ON requests(namespace, idempotency_key);
    """,
    """
    CREATE TABLE executions (
      namespace TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      request_id TEXT NOT NULL,
      task_id TEXT NOT NULL,
      attempt INTEGER NOT NULL,
      status TEXT NOT NULL,
      started_at TEXT,
      finished_at TEXT,
      input_json TEXT,
      output_json TEXT,
      checkpoint_json TEXT,
      error TEXT,
      PRIMARY KEY (namespace, idempotency_key)
    );
    """,
    """
    CREATE TABLE model_calls (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      namespace TEXT NOT NULL,
      task_id TEXT,
      request_id TEXT,
      provider TEXT,
      model TEXT,
      prompt_tokens INTEGER,
      completion_tokens INTEGER,
      cost_usd REAL,
      cost_known INTEGER NOT NULL DEFAULT 0,
      decision_json TEXT,
      error TEXT,
      created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE quarantine (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      namespace TEXT NOT NULL,
      github_comment_id INTEGER,
      message_id TEXT,
      reason TEXT NOT NULL,
      detail TEXT,
      raw_body TEXT,
      created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE pending_refs (
      namespace TEXT NOT NULL,
      message_id TEXT NOT NULL,
      missing_ref TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY (namespace, message_id, missing_ref)
    );
    """,
    """
    CREATE TABLE sync_cursors (
      namespace TEXT PRIMARY KEY,
      since TEXT,
      last_comment_id INTEGER,
      overlap_seconds INTEGER,
      updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      namespace TEXT NOT NULL,
      task_id TEXT,
      event_type TEXT NOT NULL,
      detail_json TEXT,
      created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE worker_locks (
      lock_key TEXT PRIMARY KEY,
      worker_id TEXT NOT NULL,
      owner TEXT NOT NULL,
      pid INTEGER,
      heartbeat_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE workspace_locks (
      workspace_root TEXT PRIMARY KEY,
      namespace TEXT,
      task_id TEXT,
      worker_id TEXT,
      heartbeat_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE scheduled_followups (
      namespace TEXT NOT NULL,
      followup_id TEXT NOT NULL,
      role TEXT NOT NULL,
      task_id TEXT NOT NULL,
      request_id TEXT,
      kind TEXT NOT NULL,
      due_at TEXT NOT NULL,
      payload_json TEXT,
      created_at TEXT NOT NULL,
      consumed_at TEXT,
      PRIMARY KEY (namespace, followup_id)
    );
    CREATE INDEX idx_scheduled_followups_due
      ON scheduled_followups(namespace, role, consumed_at, due_at);
    """,
    """
    ALTER TABLE scheduled_followups ADD COLUMN result_json TEXT;
    ALTER TABLE scheduled_followups ADD COLUMN result_persisted_at TEXT;
    ALTER TABLE scheduled_followups ADD COLUMN github_comment_id INTEGER;
    """,
]


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        if not cur.fetchone():
            applied = 0
        else:
            row = self.conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
            applied = int(row[0])
        for index, sql in enumerate(MIGRATIONS, start=1):
            if index <= applied:
                continue
            with self.conn:
                self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (index, utc_now()),
                )

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    def commit(self) -> None:
        self.conn.commit()

    def transaction(self):
        return self.conn

    # --- audit ---
    def audit(self, namespace: str, event_type: str, task_id: str | None = None, detail: Any = None) -> None:
        self.conn.execute(
            "INSERT INTO audit(namespace, task_id, event_type, detail_json, created_at) VALUES (?,?,?,?,?)",
            (namespace, task_id, event_type, json.dumps(detail, ensure_ascii=False) if detail is not None else None, utc_now()),
        )
        self.conn.commit()

    # --- tasks ---
    def upsert_task(
        self,
        namespace: str,
        task_id: str,
        *,
        issue_number: int | None = None,
        github_issue_id: int | None = None,
        state: str = TaskState.NEW.value,
        title: str | None = None,
        objective: str | None = None,
        context_revision: str | None = None,
        github_state: str = "open",
    ) -> dict[str, Any]:
        existing = self.get_task(namespace, task_id)
        now = utc_now()
        if existing:
            self.conn.execute(
                """
                UPDATE tasks SET issue_number=COALESCE(?, issue_number),
                  github_issue_id=COALESCE(?, github_issue_id),
                  title=COALESCE(?, title), objective=COALESCE(?, objective),
                  context_revision=COALESCE(?, context_revision),
                  github_state=COALESCE(?, github_state), updated_at=?
                WHERE namespace=? AND task_id=?
                """,
                (issue_number, github_issue_id, title, objective, context_revision, github_state, now, namespace, task_id),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO tasks(namespace, task_id, issue_number, github_issue_id, state, title, objective,
                  context_revision, github_state, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (namespace, task_id, issue_number, github_issue_id, state, title, objective, context_revision, github_state, now, now),
            )
        self.conn.commit()
        return self.get_task(namespace, task_id)  # type: ignore[return-value]

    def get_task(self, namespace: str, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE namespace=? AND task_id=?",
            (namespace, task_id),
        ).fetchone()
        return dict(row) if row else None

    def get_task_by_issue(self, namespace: str, issue_number: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE namespace=? AND issue_number=?",
            (namespace, issue_number),
        ).fetchone()
        return dict(row) if row else None

    def list_tasks(self, namespace: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE namespace=? ORDER BY updated_at DESC",
            (namespace,),
        ).fetchall()
        return [dict(r) for r in rows]

    def active_tasks(self, namespace: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE namespace=? AND state NOT IN ('COMPLETED','FAILED','CANCELLED')",
            (namespace,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_task_state(
        self,
        namespace: str,
        task_id: str,
        new_state: str,
        *,
        previous: str | None = None,
        resume_state: str | None = None,
        github_state: str | None = None,
        closed_at: str | None = None,
        active_request_id: str | None = None,
        bump_round: bool = False,
        bump_revision: bool = False,
    ) -> None:
        task = self.get_task(namespace, task_id)
        if not task:
            raise KeyError(task_id)
        prev = previous if previous is not None else task["state"]
        resume = resume_state if resume_state is not None else task["resume_state"]
        rounds = task["round_count"] + (1 if bump_round else 0)
        revisions = task["revision_count"] + (1 if bump_revision else 0)
        req = task["active_request_id"] if active_request_id is None else active_request_id
        self.conn.execute(
            """
            UPDATE tasks SET state=?, previous_state=?, resume_state=?, github_state=COALESCE(?, github_state),
              closed_at=COALESCE(?, closed_at), active_request_id=?, round_count=?, revision_count=?, updated_at=?
            WHERE namespace=? AND task_id=?
            """,
            (new_state, prev, resume, github_state, closed_at, req, rounds, revisions, utc_now(), namespace, task_id),
        )
        self.conn.commit()

    # --- events / inbox ---
    def persist_event(self, namespace: str, comment: dict[str, Any]) -> bool:
        """Persiste o evento bruto antes de avançar o cursor. False se duplicado."""
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO events(namespace, github_comment_id, issue_number, observed_at, payload_json)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        namespace,
                        comment.get("id"),
                        comment.get("issue_number"),
                        utc_now(),
                        json.dumps(comment, ensure_ascii=False, default=str),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_message_by_id(self, namespace: str, message_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM messages WHERE namespace=? AND message_id=?",
            (namespace, message_id),
        ).fetchone()
        return dict(row) if row else None

    def get_message_by_github(self, namespace: str, github_comment_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM messages WHERE namespace=? AND github_comment_id=?",
            (namespace, github_comment_id),
        ).fetchone()
        return dict(row) if row else None

    def find_message_anywhere(self, namespace: str, message_id: str) -> dict[str, Any] | None:
        found = self.get_message_by_id(namespace, message_id)
        if found:
            return found
        row = self.conn.execute(
            "SELECT * FROM outbox WHERE namespace=? AND message_id=?",
            (namespace, message_id),
        ).fetchone()
        return dict(row) if row else None

    def upsert_message(
        self,
        namespace: str,
        *,
        message_id: str,
        task_id: str | None,
        github_comment_id: int | None,
        issue_number: int | None,
        envelope: Envelope | None,
        body: str,
        raw: str,
        observed_hash: str,
        kind: str,
        github_login: str | None,
        quarantine_reason: str | None = None,
    ) -> dict[str, Any]:
        existing = None
        if github_comment_id is not None:
            existing = self.get_message_by_github(namespace, github_comment_id)
        if existing is None:
            existing = self.get_message_by_id(namespace, message_id)
        now = utc_now()
        diverged = 0
        if existing and existing["observed_hash"] != observed_hash:
            diverged = 1
        env_json = envelope.model_dump() if envelope else None
        if existing:
            self.conn.execute(
                """
                UPDATE messages SET current_hash=?, hash_diverged=?, raw_body=?,
                  github_login=COALESCE(?, github_login),
                  github_comment_id=COALESCE(?, github_comment_id),
                  issue_number=COALESCE(?, issue_number)
                WHERE namespace=? AND message_id=?
                """,
                (observed_hash, max(diverged, existing["hash_diverged"]), raw, github_login, github_comment_id, issue_number, namespace, existing["message_id"]),
            )
            self.conn.commit()
            return self.get_message_by_id(namespace, existing["message_id"])  # type: ignore[return-value]
        self.conn.execute(
            """
            INSERT INTO messages(namespace, message_id, task_id, github_comment_id, issue_number, type,
              sender_role, sender_id, github_login, recipient_role, request_id, in_reply_to, attempt,
              created_at, observed_at, observed_hash, current_hash, hash_diverged, envelope_json,
              body_text, raw_body, kind, quarantine_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                namespace,
                message_id,
                task_id,
                github_comment_id,
                issue_number,
                envelope.type if envelope else None,
                envelope.sender_role if envelope else None,
                envelope.sender_id if envelope else None,
                github_login,
                envelope.recipient_role if envelope else None,
                envelope.request_id if envelope else None,
                envelope.in_reply_to if envelope else None,
                envelope.attempt if envelope else None,
                envelope.created_at if envelope else None,
                now,
                observed_hash,
                observed_hash,
                0,
                json.dumps(env_json, ensure_ascii=False) if env_json else None,
                body,
                raw,
                kind,
                quarantine_reason,
            ),
        )
        self.conn.commit()
        return self.get_message_by_id(namespace, message_id)  # type: ignore[return-value]

    def unprocessed_messages(self, namespace: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE namespace=? AND processed_at IS NULL
            ORDER BY COALESCE(github_comment_id, 0), observed_at, message_id
            """,
            (namespace,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_processed(self, namespace: str, message_id: str) -> None:
        self.conn.execute(
            "UPDATE messages SET processed_at=? WHERE namespace=? AND message_id=?",
            (utc_now(), namespace, message_id),
        )
        self.conn.commit()

    def add_pending_ref(self, namespace: str, message_id: str, missing_ref: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO pending_refs(namespace, message_id, missing_ref, created_at) VALUES (?,?,?,?)",
            (namespace, message_id, missing_ref, utc_now()),
        )
        self.conn.commit()

    def pending_ready(self, namespace: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT m.* FROM messages m
            JOIN pending_refs p ON p.namespace=m.namespace AND p.message_id=m.message_id
            WHERE m.namespace=? AND m.processed_at IS NULL
              AND EXISTS (
                SELECT 1 FROM messages x WHERE x.namespace=m.namespace AND x.message_id=p.missing_ref
              )
            """,
            (namespace,),
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_pending_ref(self, namespace: str, message_id: str, missing_ref: str) -> None:
        self.conn.execute(
            "DELETE FROM pending_refs WHERE namespace=? AND message_id=? AND missing_ref=?",
            (namespace, message_id, missing_ref),
        )
        self.conn.commit()

    def has_quarantine(
        self,
        namespace: str,
        *,
        github_comment_id: int | None = None,
        message_id: str | None = None,
    ) -> bool:
        if github_comment_id is not None:
            row = self.conn.execute(
                "SELECT 1 FROM quarantine WHERE namespace=? AND github_comment_id=? LIMIT 1",
                (namespace, github_comment_id),
            ).fetchone()
            if row:
                return True
        if message_id:
            row = self.conn.execute(
                "SELECT 1 FROM quarantine WHERE namespace=? AND message_id=? LIMIT 1",
                (namespace, message_id),
            ).fetchone()
            if row:
                return True
        return False

    def quarantine(
        self,
        namespace: str,
        reason: str,
        *,
        github_comment_id: int | None = None,
        message_id: str | None = None,
        detail: str | None = None,
        raw_body: str | None = None,
    ) -> bool:
        """Insere uma linha de quarentena. Devolve True se era a primeira vez (mesmo comment/message)."""
        if self.has_quarantine(namespace, github_comment_id=github_comment_id, message_id=message_id):
            return False
        self.conn.execute(
            """
            INSERT INTO quarantine(namespace, github_comment_id, message_id, reason, detail, raw_body, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (namespace, github_comment_id, message_id, reason, detail, raw_body, utc_now()),
        )
        self.conn.commit()
        return True

    def list_quarantine(self, namespace: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM quarantine WHERE namespace=? ORDER BY id DESC",
            (namespace,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- outbox ---
    def enqueue_outbox(self, namespace: str, message_id: str, task_id: str, issue_number: int, body: str) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO outbox(namespace, message_id, task_id, issue_number, body, status, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (namespace, message_id, task_id, issue_number, body, DeliveryState.PENDING.value, utc_now()),
        )
        self.conn.commit()

    def pending_outbox(self, namespace: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM outbox WHERE namespace=? AND status IN ('PENDING','PUBLISHING','FAILED') ORDER BY created_at, rowid",
            (namespace,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_outbox(self, namespace: str, message_id: str, status: str, **fields: Any) -> None:
        sets = ["status=?"]
        params: list[Any] = [status]
        if "github_comment_id" in fields:
            sets.append("github_comment_id=?")
            params.append(fields["github_comment_id"])
        if "last_error" in fields:
            sets.append("last_error=?")
            params.append(fields["last_error"])
        if "attempts" in fields:
            sets.append("attempts=?")
            params.append(fields["attempts"])
        if status == DeliveryState.PUBLISHED.value:
            sets.append("published_at=?")
            params.append(utc_now())
        params.extend([namespace, message_id])
        self.conn.execute(
            f"UPDATE outbox SET {', '.join(sets)} WHERE namespace=? AND message_id=?",
            params,
        )
        self.conn.commit()

    def get_outbox(self, namespace: str, message_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM outbox WHERE namespace=? AND message_id=?",
            (namespace, message_id),
        ).fetchone()
        return dict(row) if row else None

    # --- requests / executions ---
    def upsert_request(
        self,
        namespace: str,
        request_id: str,
        task_id: str,
        *,
        message_id: str | None,
        attempt: int,
        status: str = RequestState.OPEN.value,
        idempotency_key: str | None = None,
    ) -> None:
        key = idempotency_key or f"{namespace}:{request_id}:{attempt}"
        now = utc_now()
        existing = self.get_request(namespace, request_id)
        if existing:
            self.conn.execute(
                "UPDATE requests SET status=?, message_id=COALESCE(?, message_id), updated_at=? WHERE namespace=? AND request_id=?",
                (status, message_id, now, namespace, request_id),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO requests(namespace, request_id, task_id, message_id, attempt, status, idempotency_key, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (namespace, request_id, task_id, message_id, attempt, status, key, now, now),
            )
        self.conn.commit()

    def get_request(self, namespace: str, request_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM requests WHERE namespace=? AND request_id=?",
            (namespace, request_id),
        ).fetchone()
        return dict(row) if row else None

    def release_request(self, namespace: str, request_id: str) -> None:
        """Encerra a request local sem fechar a tarefa. Um answer não a retoma."""
        now = utc_now()
        self.conn.execute(
            "UPDATE requests SET status=?, blocked_by_question=NULL, updated_at=? WHERE namespace=? AND request_id=?",
            (RequestState.DONE.value, now, namespace, request_id),
        )
        self.conn.commit()

    def set_request_blocked(self, namespace: str, request_id: str, question_id: str | None) -> None:
        status = RequestState.BLOCKED.value if question_id else RequestState.RUNNING.value
        self.conn.execute(
            "UPDATE requests SET status=?, blocked_by_question=?, updated_at=? WHERE namespace=? AND request_id=?",
            (status, question_id, utc_now(), namespace, request_id),
        )
        self.conn.commit()

    def start_execution(
        self,
        namespace: str,
        *,
        idempotency_key: str,
        request_id: str,
        task_id: str,
        attempt: int,
        input_json: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.get_execution(namespace, idempotency_key)
        if existing:
            return existing
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO executions(namespace, idempotency_key, request_id, task_id, attempt, status, started_at, input_json)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                namespace,
                idempotency_key,
                request_id,
                task_id,
                attempt,
                ExecutionState.STARTING.value,
                now,
                json.dumps(input_json, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return self.get_execution(namespace, idempotency_key)  # type: ignore[return-value]

    def get_execution(self, namespace: str, idempotency_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM executions WHERE namespace=? AND idempotency_key=?",
            (namespace, idempotency_key),
        ).fetchone()
        return dict(row) if row else None

    def get_execution_by_request(self, namespace: str, request_id: str, attempt: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM executions WHERE namespace=? AND request_id=? AND attempt=?",
            (namespace, request_id, attempt),
        ).fetchone()
        return dict(row) if row else None

    def finish_execution(
        self,
        namespace: str,
        idempotency_key: str,
        status: str,
        output: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE executions SET status=?, finished_at=?, output_json=?, checkpoint_json=?, error=?
            WHERE namespace=? AND idempotency_key=?
            """,
            (
                status,
                utc_now(),
                json.dumps(output, ensure_ascii=False) if output is not None else None,
                json.dumps(checkpoint, ensure_ascii=False) if checkpoint is not None else None,
                error,
                namespace,
                idempotency_key,
            ),
        )
        self.conn.commit()

    def record_model_call(
        self,
        namespace: str,
        *,
        task_id: str | None,
        request_id: str | None,
        provider: str,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        cost_usd: float | None,
        cost_known: bool,
        decision: dict[str, Any] | None,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO model_calls(namespace, task_id, request_id, provider, model, prompt_tokens,
              completion_tokens, cost_usd, cost_known, decision_json, error, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                namespace,
                task_id,
                request_id,
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                1 if cost_known else 0,
                json.dumps(decision, ensure_ascii=False) if decision is not None else None,
                error,
                utc_now(),
            ),
        )
        self.conn.commit()

    def task_usage(self, namespace: str, task_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(cost_usd), 0) AS cost_usd,
                   MIN(cost_known) AS all_known
            FROM model_calls WHERE namespace=? AND task_id=? AND error IS NULL
            """,
            (namespace, task_id),
        ).fetchone()
        return dict(row)

    def get_cursor(self, namespace: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM sync_cursors WHERE namespace=?", (namespace,)).fetchone()
        return dict(row) if row else None

    def set_cursor(self, namespace: str, since: str | None, last_comment_id: int | None, overlap: int) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_cursors(namespace, since, last_comment_id, overlap_seconds, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(namespace) DO UPDATE SET since=excluded.since, last_comment_id=excluded.last_comment_id,
              overlap_seconds=excluded.overlap_seconds, updated_at=excluded.updated_at
            """,
            (namespace, since, last_comment_id, overlap, utc_now()),
        )
        self.conn.commit()

    def messages_for_task(self, namespace: str, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE namespace=? AND task_id=? ORDER BY observed_at, message_id",
            (namespace, task_id),
        ).fetchall()
        return [dict(r) for r in rows]
