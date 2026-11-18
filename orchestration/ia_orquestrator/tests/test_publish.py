from __future__ import annotations

import subprocess
from pathlib import Path

from ia_orchestrator.publish import publish_authorized_commits


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _repo(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "test")
    (path / "readme.txt").write_text("ok\n", encoding="utf-8")
    _git(path, "add", "readme.txt")
    _git(path, "commit", "-m", "init")


def test_push_refuses_without_permission(tmp_path):
    workspace = tmp_path / "ws"
    _repo(workspace)
    report = publish_authorized_commits(workspace, allow_push=False)
    assert report["pushed"] is False
    assert report["reason"] == "allow_push false"


def test_push_refuses_dirty_tree_and_missing_upstream(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    workspace = tmp_path / "ws"
    _repo(workspace)
    blocked = publish_authorized_commits(workspace, allow_push=True)
    assert blocked["reason"] == "no upstream"
    _git(workspace, "remote", "add", "origin", str(origin))
    _git(workspace, "push", "-u", "origin", "main")
    (workspace / "readme.txt").write_text("dirty\n", encoding="utf-8")
    dirty = publish_authorized_commits(workspace, allow_push=True)
    assert dirty["pushed"] is False
    assert dirty["reason"] == "uncommitted changes"


def test_push_sends_existing_commit_without_force(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    workspace = tmp_path / "ws"
    _repo(workspace)
    _git(workspace, "remote", "add", "origin", str(origin))
    _git(workspace, "push", "-u", "origin", "main")
    (workspace / "readme.txt").write_text("next\n", encoding="utf-8")
    _git(workspace, "add", "readme.txt")
    _git(workspace, "commit", "-m", "next")
    report = publish_authorized_commits(workspace, allow_push=True)
    assert report["pushed"] is True
    assert report["branch"] == "main"
    assert "--force" not in (report.get("reason") or "")
    again = publish_authorized_commits(workspace, allow_push=True)
    assert again["reason"] == "already up to date"


def test_push_refuses_secret(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    workspace = tmp_path / "ws"
    _repo(workspace)
    _git(workspace, "remote", "add", "origin", str(origin))
    _git(workspace, "push", "-u", "origin", "main")
    (workspace / "secret.txt").write_text("ghp_" + "a" * 24 + "\n", encoding="utf-8")
    _git(workspace, "add", "secret.txt")
    _git(workspace, "commit", "-m", "secret")
    report = publish_authorized_commits(workspace, allow_push=True)
    assert report["pushed"] is False
    assert report["reason"] == "refused secret in commits"
