from __future__ import annotations

import pytest

from ia_orchestrator.context import build_context_package, detect_revision_divergence, load_source
from ia_orchestrator.errors import PolicyError, LockError
from ia_orchestrator.locks import WorkerLock, WorkspaceLock
from ia_orchestrator.persistence import Store
from ia_orchestrator.policy import resolve_under_root

from helpers import make_cfg


def test_missing_required_source(tmp_path):
    cfg = make_cfg(tmp_path, "p", "o/r")
    cfg.context.required = ["proposal"]
    cfg.context.proposal = "docs/missing.md"
    with pytest.raises(PolicyError):
        load_source(cfg, "proposal", cfg.context.proposal, required=True)


def test_optional_missing_source_warns(tmp_path):
    cfg = make_cfg(tmp_path, "p", "o/r")
    src = load_source(cfg, "proposal", "docs/nao-existe.md", required=False)
    assert src["present"] is False
    assert "warning" in src


def test_revision_divergence(tmp_path):
    cfg = make_cfg(tmp_path, "p", "o/r")
    task = {"task_id": "t", "state": "NEW", "objective": "o"}
    pkg = build_context_package(cfg, task=task, messages=[])
    assert detect_revision_divergence("oldrev", pkg["context_revision"]) is True
    assert detect_revision_divergence(pkg["context_revision"], pkg["context_revision"]) is False


def test_path_traversal(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    with pytest.raises(PolicyError):
        resolve_under_root(root, "../secret")


def test_worker_and_workspace_locks(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    lock_dir = tmp_path / "locks"
    a = WorkerLock(store, lock_dir, "p", "orchestrator", "w1", "host-a")
    a.acquire()
    with pytest.raises(LockError):
        WorkerLock(store, lock_dir, "p", "orchestrator", "w2", "host-b").acquire()
    a.release()
    b = WorkerLock(store, lock_dir, "p", "orchestrator", "w1", "host-a")
    b.acquire()
    b.release()

    ws = tmp_path / "ws"
    ws.mkdir()
    w1 = WorkspaceLock(store, ws, "ns1", "t1", "w1")
    w1.acquire()
    with pytest.raises(LockError):
        WorkspaceLock(store, ws, "ns2", "t2", "w1").acquire()
    w1.release()
    WorkspaceLock(store, ws, "ns2", "t2", "w1").acquire()
