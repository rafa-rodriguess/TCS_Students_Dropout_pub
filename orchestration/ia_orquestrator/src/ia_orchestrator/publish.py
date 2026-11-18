"""Push só de commits já feitos, depois de uma execução com sucesso.

Não cria commit, não usa --force e não publica árvore suja nem segredo.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_SECRET = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|https://discord\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+)"
)


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def commit_and_push_transferred(workspace: Path, relative: str) -> dict:
    """Cria um commit só do arquivo recebido e faz push sem --force.

    Não altera git config. Recusa caminho fora de transfered_files e conteúdo
    que pareça segredo. Não inclui outros arquivos sujos.
    """
    rel = Path(relative)
    if rel.is_absolute() or rel.parts[:1] != ("transfered_files",) or len(rel.parts) != 2:
        return {"committed": False, "pushed": False, "reason": "path outside transfered_files"}
    target = workspace / rel
    if not target.is_file():
        return {"committed": False, "pushed": False, "reason": "file missing"}
    blob = target.read_bytes()
    if _SECRET.search(blob.decode("utf-8", errors="ignore")):
        return {"committed": False, "pushed": False, "reason": "refused secret in file"}
    if not (workspace / ".git").exists():
        return {"committed": False, "pushed": False, "reason": "not a git checkout"}
    added = _git(workspace, "add", "--", relative)
    if added.returncode != 0:
        return {"committed": False, "pushed": False, "reason": (added.stderr or added.stdout).strip()}
    message = f"transfered_files: receber {rel.name}\n\nArquivo conferido por SHA-256 no comando send-file."
    committed = _git(workspace, "commit", "-m", message, "--", relative)
    combined = f"{committed.stdout}\n{committed.stderr}".lower()
    if committed.returncode != 0:
        if "nothing to commit" in combined or "no changes added" in combined:
            return {"committed": False, "pushed": False, "reason": "nothing to commit"}
        return {"committed": False, "pushed": False, "reason": (committed.stderr or committed.stdout).strip()}
    pushed = _git(workspace, "push")
    head = _git(workspace, "rev-parse", "HEAD")
    if pushed.returncode != 0:
        return {
            "committed": True,
            "pushed": False,
            "reason": (pushed.stderr or pushed.stdout).strip() or "push failed",
            "sha": head.stdout.strip(),
        }
    return {"committed": True, "pushed": True, "reason": "pushed", "sha": head.stdout.strip()}


def publish_authorized_commits(workspace: Path, *, allow_push: bool) -> dict:
    if not allow_push:
        return {"pushed": False, "reason": "allow_push false"}
    git_dir = workspace / ".git"
    if not git_dir.exists():
        return {"pushed": False, "reason": "not a git checkout"}
    dirty = _git(workspace, "status", "--porcelain")
    if dirty.returncode != 0:
        return {"pushed": False, "reason": "git status failed"}
    if dirty.stdout.strip():
        return {"pushed": False, "reason": "uncommitted changes"}
    branch = _git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = _git(workspace, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if branch.returncode != 0 or upstream.returncode != 0:
        return {
            "pushed": False,
            "reason": "no upstream",
            "branch": (branch.stdout or "").strip(),
        }
    ahead = _git(workspace, "rev-list", "--count", "@{upstream}..HEAD")
    if ahead.returncode != 0:
        return {"pushed": False, "reason": "cannot compare upstream"}
    if ahead.stdout.strip() in {"", "0"}:
        head = _git(workspace, "rev-parse", "HEAD")
        return {
            "pushed": False,
            "reason": "already up to date",
            "branch": branch.stdout.strip(),
            "upstream": upstream.stdout.strip(),
            "sha": head.stdout.strip(),
        }
    leaked = _git(workspace, "diff", "@{upstream}...HEAD")
    if leaked.returncode != 0:
        return {"pushed": False, "reason": "cannot inspect commits"}
    if _SECRET.search(leaked.stdout or ""):
        return {"pushed": False, "reason": "refused secret in commits"}
    pushed = _git(workspace, "push")
    head = _git(workspace, "rev-parse", "HEAD")
    if pushed.returncode != 0:
        return {
            "pushed": False,
            "reason": "push failed",
            "branch": branch.stdout.strip(),
            "upstream": upstream.stdout.strip(),
            "sha": head.stdout.strip(),
        }
    return {
        "pushed": True,
        "reason": "pushed",
        "branch": branch.stdout.strip(),
        "upstream": upstream.stdout.strip(),
        "sha": head.stdout.strip(),
    }
