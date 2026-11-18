import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.checkpoint import fingerprint, save_state  # noqa: E402
from jla.paths import Context  # noqa: E402


def _git_top(start: Path) -> Path:
    completed = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return Path(completed.stdout.strip()).resolve()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "orquestrator.py"), *args], check=False, capture_output=True, text=True)


def test_help_and_plan_need_no_output_dir():
    help_run = _run(["--help"])
    plan = _run(["--plan"])
    assert help_run.returncode == 0
    assert "--output-dir" in help_run.stdout
    assert plan.returncode == 0
    assert "ETAPA 00" in plan.stdout and "ETAPA 10" in plan.stdout


def test_full_without_output_dir_is_refused():
    run = _run(["--all"])
    assert run.returncode == 1
    assert "explícito" in run.stderr
    assert "DOWNLOAD" not in run.stdout


def test_output_inside_the_checkout_is_refused():
    inside = ROOT / "outputs_local"
    run = _run(["--all", "--output-dir", str(inside)])
    assert run.returncode == 1
    assert "checkout" in run.stderr
    assert not inside.exists()
    checkout = _git_top(ROOT)
    root_run = _run(["--stage", "00", "--output-dir", str(checkout)])
    assert root_run.returncode == 1
    assert "checkout" in root_run.stderr


def test_preexisting_artifacts_are_not_overwritten(tmp_path):
    marker = tmp_path / "results" / "p3_metrics.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"keep": true}\n', encoding="utf-8")
    run = _run(["--all", "--output-dir", str(tmp_path)])
    assert run.returncode == 1
    assert "preexistente" in run.stderr
    assert marker.read_text(encoding="utf-8") == '{"keep": true}\n'
    assert "DOWNLOAD" not in run.stdout


def test_resume_rejects_a_bad_fingerprint_and_keeps_the_directory(tmp_path):
    ctx = Context(output_dir=tmp_path)
    ctx.ensure_dirs()
    save_state(ctx, {"fingerprint": "0" * 64, "stages": {"00": {"status": "PASS"}}})
    before = (ctx.checkpoints / "state.json").read_text(encoding="utf-8")
    run = _run(["--stage", "00", "--resume", "--output-dir", str(tmp_path)])
    assert run.returncode == 1
    assert "fingerprint" in run.stderr
    assert (ctx.checkpoints / "state.json").read_text(encoding="utf-8") == before


def test_resume_accepts_a_valid_checkpoint(tmp_path):
    first = _run(["--stage", "00", "--output-dir", str(tmp_path)])
    assert first.returncode == 0, first.stderr
    second = _run(["--stage", "00", "--resume", "--output-dir", str(tmp_path)])
    assert second.returncode == 0, second.stderr
    assert "retomada" in second.stdout
    state = json.loads((tmp_path / "checkpoints" / "state.json").read_text(encoding="utf-8"))
    assert state["fingerprint"] == fingerprint()
    assert state["stages"]["00"]["status"] == "PASS"


def test_gitignore_excludes_results_data_and_models():
    top = _git_top(ROOT)
    ignored = [
        "results/p3_metrics.json",
        "results/public_examples.json",
        "figures/rascunho.svg",
        "data/raw/studentVle.csv",
        "models/hazard.joblib",
    ]
    kept = [
        "baselines/aggregates.json",
        "config/protocol.yaml",
        "src/jla/science.py",
        "tests/test_structure.py",
        "LICENSE",
    ]
    for name in ignored:
        run = subprocess.run(["git", "check-ignore", "-v", str(ROOT / name)], cwd=top, check=False, capture_output=True, text=True)
        assert run.returncode == 0, name
        source = Path(run.stdout.split(":", 1)[0])
        if not source.is_absolute():
            source = top / source
        assert source.resolve() == (ROOT / ".gitignore").resolve(), run.stdout
    for name in kept:
        run = subprocess.run(["git", "check-ignore", "-q", str(ROOT / name)], cwd=top, check=False)
        assert run.returncode == 1, name


def test_suite_runs_when_the_package_is_its_own_git_root(tmp_path):
    if os.environ.get("TCS_CLEAN_COPY") == "1":
        return
    dest = tmp_path / "nested" / "pkg"
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", "outputs_local"))
    init = subprocess.run(["git", "init"], cwd=dest, check=False, capture_output=True, text=True)
    assert init.returncode == 0, init.stderr
    assert _git_top(dest) == dest.resolve()
    env = os.environ.copy()
    env["TCS_CLEAN_COPY"] = "1"
    run = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=dest, env=env, check=False, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "passed" in run.stdout
