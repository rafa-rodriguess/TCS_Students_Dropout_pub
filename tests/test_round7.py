import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jla.paths import Context  # noqa: E402
from jla.stage09_equity import run as equity  # noqa: E402
from jla.stage10_report import REQUIRED, run as report  # noqa: E402
from test_round5 import _rehash, _write_mock  # noqa: E402
from jla.stage08_operator import run as audit  # noqa: E402


def _corrupt_r18(tmp_path, column: str) -> None:
    ctx = _write_mock(tmp_path)
    path = ctx.results / "private" / "r18.csv"
    table = pd.read_csv(path)
    table[column] = table[column] + 0.05
    table.to_csv(path, index=False)
    _rehash(ctx)
    result = audit(ctx)
    assert result["status"] == "FAIL"
    tests = json.loads((ctx.results / "operator_tests.json").read_text(encoding="utf-8"))
    assert any(item["test"] == "T8" and item["result"] == "FAIL" for item in tests)


def test_corrupted_shock_survival_fails(tmp_path):
    _corrupt_r18(tmp_path, "S_shock")


def test_corrupted_mechanism_survival_fails(tmp_path):
    _corrupt_r18(tmp_path, "S_mech")


def test_missing_p3_fails_the_parameter_check(tmp_path):
    ctx = _write_mock(tmp_path)
    (ctx.results / "p3_metrics.json").unlink()
    result = audit(ctx)
    assert result["status"] == "FAIL"
    tests = json.loads((ctx.results / "operator_tests.json").read_text(encoding="utf-8"))
    assert any(item["test"] == "T9" and item["result"] == "FAIL" for item in tests)


def test_missing_gap_interval_fails(tmp_path):
    ctx = _write_mock(tmp_path)
    path = ctx.results / "p3_metrics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["delta_gap_mechanism_ci"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = audit(ctx)
    assert result["status"] == "FAIL"
    tests = json.loads((ctx.results / "operator_tests.json").read_text(encoding="utf-8"))
    assert any(item["test"] == "T9" and item["result"] == "FAIL" for item in tests)


def _equity_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_student": [1, 1, 2],
            "code_module": ["AAA", "BBB", "AAA"],
            "code_presentation": ["2013J", "2013J", "2013J"],
            "female": [True, True, False],
            "S_base": [0.40, 0.50, 0.30],
            "S_shock": [0.45, 0.55, 0.32],
            "S_mech": [0.48, 0.58, 0.31],
            "dS_shock": [0.05, 0.05, 0.02],
            "dS_mech": [0.08, 0.08, 0.01],
        }
    )


def _p3_for(table: pd.DataFrame) -> dict:
    female = table["female"].to_numpy()
    shock_gap = float(table.loc[female, "S_shock"].mean() - table.loc[~female, "S_shock"].mean())
    base_gap = float(table.loc[female, "S_base"].mean() - table.loc[~female, "S_base"].mean())
    mech_gap = float(table.loc[female, "S_mech"].mean() - table.loc[~female, "S_mech"].mean())
    return {
        "delta_s_shock": float(table["dS_shock"].mean()),
        "delta_gap_shock": shock_gap - base_gap,
        "delta_s_mechanism": float(table["dS_mech"].mean()),
        "delta_gap_mechanism": mech_gap - base_gap,
    }


def _write_equity(tmp_path, table: pd.DataFrame, metrics: dict) -> Context:
    ctx = Context(output_dir=tmp_path)
    private = ctx.results / "private"
    private.mkdir(parents=True)
    table.to_csv(private / "r18.csv", index=False)
    (ctx.results / "p3_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return ctx


def test_equity_recovers_both_scenarios(tmp_path):
    table = _equity_table()
    result = equity(_write_equity(tmp_path, table, _p3_for(table)))
    assert result["status"] == "PASS"


def test_equity_fails_when_a_scenario_is_mutated(tmp_path):
    table = _equity_table()
    metrics = _p3_for(table)
    table["dS_shock"] = table["dS_shock"] + 0.01
    result = equity(_write_equity(tmp_path, table, metrics))
    assert result["status"] == "FAIL"


def test_equity_fails_without_both_sexes_or_metrics(tmp_path):
    table = _equity_table()
    table["female"] = True
    assert equity(_write_equity(tmp_path, table, _p3_for(_equity_table())))["status"] == "FAIL"
    bare = Context(output_dir=tmp_path / "empty")
    assert equity(bare)["status"] == "FAIL"


def test_compare_baseline_does_not_run_the_study(tmp_path):
    run = subprocess.run(
        [sys.executable, str(ROOT / "orquestrator.py"), "--compare-baseline", "--output-dir", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    assert "ausente" in run.stdout
    assert "ETAPA 00" not in run.stdout and "ETAPA 01" not in run.stdout
    assert "DOWNLOAD" not in run.stdout
    assert not (tmp_path / "models" / "hazard.joblib").exists()
    assert not list((tmp_path / "data" / "raw").glob("*"))


def test_compare_baseline_reads_existing_outputs_only(tmp_path):
    ctx = Context(output_dir=tmp_path, compare_baseline=True, compare_only=True)
    ctx.ensure_dirs()
    for name in REQUIRED:
        (ctx.results / name).write_text("{}", encoding="utf-8")
    (ctx.checkpoints / "state.json").write_text("{}", encoding="utf-8")
    result = report(ctx)
    assert result["status"] == "FAIL"
    assert result["publication_status"] == "BLOCKED"
    manifest = json.loads((ctx.results / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publication_status"] == "BLOCKED"
    assert manifest["verification_status"] == "FAIL"
    assert manifest["fingerprint"]
    assert "numpy" in manifest["libraries"]
