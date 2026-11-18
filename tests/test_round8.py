import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import orquestrator  # noqa: E402
from jla.checkpoint import fingerprint, input_token, load_state, output_token, save_state  # noqa: E402
from jla.paths import Context  # noqa: E402
from jla.stage01_download import CSV_NAMES  # noqa: E402
from jla.stage10_report import REQUIRED, run as report  # noqa: E402


def _raw_stub(ctx: Context) -> None:
    ctx.ensure_dirs()
    lines = []
    for index in range(8):
        lines.append(f"{index},AAA,2013J")
    keys = "\n".join(lines)
    (ctx.raw / "studentInfo.csv").write_text("id_student,code_module,code_presentation,final_result\n" + "\n".join(f"{row},Pass" for row in keys.splitlines()) + "\n", encoding="utf-8")
    (ctx.raw / "studentRegistration.csv").write_text("id_student,code_module,code_presentation,date_unregistration\n" + "\n".join(f"{row}," for row in keys.splitlines()) + "\n", encoding="utf-8")
    (ctx.raw / "studentVle.csv").write_text("id_student,code_module,code_presentation,date\n" + "\n".join(f"{row},{index * 7}" for index, row in enumerate(keys.splitlines())) + "\n", encoding="utf-8")
    for name in CSV_NAMES:
        path = ctx.raw / name
        if not path.exists():
            path.write_text("id\n", encoding="utf-8")
    panel = ["id_student,code_module,code_presentation,week,event"]
    panel.extend(f"{row},0,0" for row in keys.splitlines())
    (ctx.processed / "person_period.csv").write_text("\n".join(panel) + "\n", encoding="utf-8")


def _stamp(ctx: Context, names: list[str], *, scope_08: str | None = None) -> None:
    current = fingerprint()
    state = {"fingerprint": current, "stages": {}}
    for name in names:
        row = {"status": "PASS", "fingerprint": current, "input_token": input_token(ctx, name), "output_token": output_token(ctx, name)}
        if name == "08" and scope_08 is not None:
            row["scope"] = scope_08
        state["stages"][name] = row
    save_state(ctx, state)


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "orquestrator.py"), *args, "--output-dir", str(tmp_path)], check=False, capture_output=True, text=True)


def test_stage04_keeps_the_base_panel_and_stage05_keeps_stage03(tmp_path, monkeypatch):
    ctx = Context(output_dir=tmp_path)
    _raw_stub(ctx)
    base = (ctx.processed / "person_period.csv").read_bytes()
    _stamp(ctx, ["00", "01", "02", "03"])
    first = _run(tmp_path, "--stage", "04", "--resume")
    assert first.returncode == 0, first.stderr
    assert (ctx.processed / "person_period.csv").read_bytes() == base
    assert "split" not in (ctx.processed / "person_period.csv").read_text(encoding="utf-8")
    assert "split" in (ctx.processed / "person_period_split.csv").read_text(encoding="utf-8")
    assert "03" in load_state(ctx)["stages"]
    assert "etapa 03" not in first.stdout

    def stub(_ctx):
        return {"status": "NOT_RUN_SCIENCE", "message": "stub sem ajuste"}

    stages = list(orquestrator.STAGES)
    stages[5] = ("05", stub)
    monkeypatch.setattr(orquestrator, "STAGES", stages)
    code = orquestrator.main(["--stage", "05", "--output-dir", str(tmp_path), "--resume"])
    assert code == 2
    assert "03" in load_state(ctx)["stages"]
    assert not (tmp_path / "models" / "hazard.joblib").exists()


def test_changed_base_panel_invalidates_dependents(tmp_path):
    ctx = Context(output_dir=tmp_path)
    _raw_stub(ctx)
    _stamp(ctx, ["00", "01", "02", "03"])
    assert _run(tmp_path, "--stage", "04", "--resume").returncode == 0
    panel = ctx.processed / "person_period.csv"
    panel.write_text(panel.read_text(encoding="utf-8") + "9,AAA,2013J,0,0\n", encoding="utf-8")
    second = _run(tmp_path, "--stage", "05", "--resume")
    assert second.returncode == 1
    assert "etapa 03" in second.stderr
    saved = load_state(ctx)
    assert "03" not in saved["stages"]
    assert "04" not in saved["stages"]
    assert not (tmp_path / "models" / "hazard.joblib").exists()


def _complete_jsons(ctx: Context) -> None:
    ctx.ensure_dirs()
    payloads = {
        "p1_metrics.json": {"n_enrollments": 32593, "n_students": 28785, "n_events": 7387, "n_test_students": 8636, "n_test_enrollments": 9738, "n_test_events": 2193, "overlap_students": 0},
        "p2_metrics.json": {"n_test_rows": 232509, "weekly_auc_4dp": 0.8142, "weekly_brier_6dp": 0.009226},
        "p3_metrics.json": {
            "n_r18_enrollments": 6369,
            "n_r18_students": 5894,
            "delta_s_shock": 0.0013356553564737824,
            "delta_s_shock_ci": [0.0013071945442908346, 0.0013637700157101641],
            "delta_s_mechanism": 0.006321944790053086,
            "delta_s_mechanism_ci": [0.006183968634230925, 0.006459618889860236],
            "delta_gap_mechanism": -0.000029654873140660953,
            "delta_gap_mechanism_ci": [-0.0003157480623758424, 0.00024821198187590927],
            "delta_gap_shock": -0.0000345133,
            "delta_gap_shock_ci": [-0.0000930654, 0.000017181],
        },
        "censoring.json": {"g18_4dp": 0.9398},
        "landmark.json": {"landmark_ipcw_auc_4dp": 0.7024, "landmark_unweighted_auc_4dp": 0.7033},
        "operator_tests.json": {},
        "equity.json": {},
    }
    for name in REQUIRED:
        (ctx.results / name).write_text(json.dumps(payloads[name]), encoding="utf-8")


def test_empty_or_stale_checkpoint_blocks_reproduction(tmp_path):
    ctx = Context(output_dir=tmp_path, compare_baseline=True, compare_only=True)
    _complete_jsons(ctx)
    (ctx.checkpoints / "state.json").write_text("{}", encoding="utf-8")
    empty = report(ctx)
    assert empty["status"] == "FAIL"
    assert empty["status"] != "PASS_REPRODUCTION"
    assert "vazio" in empty["message"]
    _stamp(ctx, [f"{index:02d}" for index in range(10)], scope_08="REAL")
    state = load_state(ctx)
    state["fingerprint"] = "0" * 64
    save_state(ctx, state)
    stale = report(ctx)
    assert stale["status"] == "FAIL"
    assert "obsoleto" in stale["message"]


def test_mock_scope_and_pending_hash_block_reproduction(tmp_path):
    ctx = Context(output_dir=tmp_path, compare_baseline=True, compare_only=True)
    _complete_jsons(ctx)
    names = [f"{index:02d}" for index in range(10)]
    _stamp(ctx, names, scope_08="MOCK")
    mocked = report(ctx)
    assert mocked["status"] == "BLOCKED"
    assert mocked["status"] != "PASS_REPRODUCTION"
    assert "REAL" in mocked["message"]
    _stamp(ctx, names, scope_08="REAL")
    blocked = report(ctx)
    assert blocked["status"] == "BLOCKED"
    assert blocked["verification_status"] == "BLOCKED"
    assert blocked["publication_status"] == "BLOCKED"
    assert blocked["status"] != "PASS_REPRODUCTION"
