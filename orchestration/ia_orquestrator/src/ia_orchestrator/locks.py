"""Locks locais de worker e de workspace. Sem eleição distribuída."""

from __future__ import annotations

import os
from pathlib import Path

from ia_orchestrator.errors import LockError
from ia_orchestrator.persistence import Store
from ia_orchestrator.protocol import utc_now

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = None

    def acquire(self) -> None:
        self._fh = open(self.path, "a+", encoding="utf-8")
        if fcntl is None:
            return
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._fh.close()
            self._fh = None
            raise LockError(f"lock ocupado: {self.path}") from exc

    def release(self) -> None:
        if self._fh is None:
            return
        if fcntl is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._fh.close()
        self._fh = None

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


def worker_lock_key(project_id: str, role: str) -> str:
    return f"{project_id}|{role}"


class WorkerLock:
    """Um worker activo por papel/projecto neste host.

    Outro host com worker_id diferente NÃO assume automaticamente a identidade.
    Transferência é manual: parar o dono anterior, reconciliar, activar o novo.
    """

    def __init__(self, store: Store, lock_dir: Path, project_id: str, role: str, worker_id: str, owner: str) -> None:
        self.store = store
        self.key = worker_lock_key(project_id, role)
        self.worker_id = worker_id
        self.owner = owner
        self.file_lock = FileLock(lock_dir / f"{project_id}-{role}.lock")

    def acquire(self) -> None:
        self.file_lock.acquire()
        row = self.store.execute("SELECT * FROM worker_locks WHERE lock_key=?", (self.key,)).fetchone()
        if row and row["worker_id"] != self.worker_id:
            self.file_lock.release()
            raise LockError(
                f"identidade {self.key} pertence a worker_id={row['worker_id']} owner={row['owner']}. "
                "Transferência manual: pare o proprietário anterior, reconcilie outbox/execuções e só então altere worker_id."
            )
        now = utc_now()
        if row:
            self.store.execute(
                "UPDATE worker_locks SET owner=?, pid=?, heartbeat_at=? WHERE lock_key=?",
                (self.owner, os.getpid(), now, self.key),
            )
        else:
            self.store.execute(
                "INSERT INTO worker_locks(lock_key, worker_id, owner, pid, heartbeat_at) VALUES (?,?,?,?,?)",
                (self.key, self.worker_id, self.owner, os.getpid(), now),
            )
        self.store.commit()

    def heartbeat(self) -> None:
        self.store.execute(
            "UPDATE worker_locks SET heartbeat_at=?, pid=? WHERE lock_key=? AND worker_id=?",
            (utc_now(), os.getpid(), self.key, self.worker_id),
        )
        self.store.commit()

    def release(self) -> None:
        self.store.execute(
            "DELETE FROM worker_locks WHERE lock_key=? AND worker_id=?",
            (self.key, self.worker_id),
        )
        self.store.commit()
        self.file_lock.release()


class WorkspaceLock:
    def __init__(self, store: Store, workspace_root: Path, namespace: str, task_id: str, worker_id: str) -> None:
        self.store = store
        self.workspace_root = str(workspace_root.resolve())
        self.namespace = namespace
        self.task_id = task_id
        self.worker_id = worker_id

    def acquire(self) -> None:
        row = self.store.execute(
            "SELECT * FROM workspace_locks WHERE workspace_root=?",
            (self.workspace_root,),
        ).fetchone()
        if row and (row["task_id"] != self.task_id or row["namespace"] != self.namespace):
            raise LockError(
                f"workspace {self.workspace_root} ocupado por {row['namespace']} task={row['task_id']}"
            )
        now = utc_now()
        if row:
            self.store.execute(
                "UPDATE workspace_locks SET namespace=?, task_id=?, worker_id=?, heartbeat_at=? WHERE workspace_root=?",
                (self.namespace, self.task_id, self.worker_id, now, self.workspace_root),
            )
        else:
            self.store.execute(
                "INSERT INTO workspace_locks(workspace_root, namespace, task_id, worker_id, heartbeat_at) VALUES (?,?,?,?,?)",
                (self.workspace_root, self.namespace, self.task_id, self.worker_id, now),
            )
        self.store.commit()

    def release(self) -> None:
        self.store.execute(
            "DELETE FROM workspace_locks WHERE workspace_root=? AND task_id=?",
            (self.workspace_root, self.task_id),
        )
        self.store.commit()
