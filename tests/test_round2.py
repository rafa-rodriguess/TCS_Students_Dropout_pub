import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.audit import (  # noqa: E402
    SCORE_COLUMNS,
    assert_score_contract,
    compare_baseline,
    gender_on_r18,
    ipcw_weights,
    landmark_roles,
    mechanism_respects_clock,
    synthetic_clock,
)
from jla.checkpoint import fingerprint, input_token, load_state, output_token, save_state  # noqa: E402
from jla.paths import Context  # noqa: E402
from jla.science import censoring_g  # noqa: E402
from jla.stage01_download import safe_extract  # noqa: E402


class _ConstantModel:
    def predict_proba(self, frame):
        import numpy as np

        ones = np.full(len(frame), 0.1)
        return np.column_stack([1.0 - ones, ones])


def test_score_contract_rejects_missing_gender():
    frame = pd.DataFrame({column: [1] for column in SCORE_COLUMNS})
    assert_score_contract(frame)
    with pytest.raises(RuntimeError, match="gender"):
        assert_score_contract(frame.drop(columns=["gender"]))


def test_landmark_counts_and_ipcw_weights():
    enr = pd.DataFrame(
        {
            "event_withdrawn": [1, 0, 1, 0],
            "t_event_week": [10, None, 6, None],
            "t_final_week": [10, 20, 6, 12],
        }
    )
    roles = landmark_roles(enr)
    assert int((roles["y"] == 1).sum()) == 1
    assert int((roles["y"] == 0).sum()) == 1
    assert int((roles["at_risk"] & roles["y"].eq(-1)).sum()) == 1
    g = censoring_g(enr.iloc[[0, 1]])
    w_case, w_control = ipcw_weights([10], g, 18, 1)
    assert w_case.shape == (1,)
    assert w_control.shape == (1,)
    assert w_control[0] == 1.0 / g[18]


def test_clock_and_mechanism_do_not_rewrite_the_action_week():
    results = []
    synthetic_clock(results)
    assert all(item["result"] == "PASS" for item in results)
    assert {item["test"] for item in results} >= {"T1", "T1b", "T2", "T3", "T4", "T5"}
    frame = pd.DataFrame(
        {
            "id_student": [1, 1, 1, 1],
            "code_module": ["AAA"] * 4,
            "code_presentation": ["2013J"] * 4,
            "week": [0, 1, 2, 3],
            "recency": [1, 0, 0, 0],
            "total_clicks": [0.0, 10.0, 4.0, 1.0],
            "streak": [0, 1, 2, 3],
            "submitted_this_week": [0, 0, 0, 0],
            "event": [0, 0, 0, 0],
            "lag_available": [0, 1, 1, 1],
            "total_clicks_lag": [0.0, 0.0, 10.0, 4.0],
            "recency_lag": [0.0, 4.0, 0.0, 0.0],
            "streak_lag": [0.0, 0.0, 1.0, 2.0],
            "submitted_lag": [0.0, 0.0, 0.0, 0.0],
            "studied_credits": [60] * 4,
            "num_of_prev_attempts": [0] * 4,
            "highest_education": ["A Level or Equivalent"] * 4,
            "age_band": ["0-35"] * 4,
            "gender": ["F"] * 4,
            "s_star": [0, 0, 0, 0],
        }
    )
    clock = mechanism_respects_clock(frame, pd.Series([0.2, 0.2, 0.2, 0.2]).to_numpy(), _ConstantModel())
    assert clock["action_unchanged"] and clock["outside_unchanged"]


def test_gender_mean_recovers_the_total_and_disability_is_absent():
    table = pd.DataFrame({"dS": [0.2, 0.4], "female": [True, False]})
    summary = gender_on_r18(table)
    assert summary["weighted_matches"]
    assert summary["disability"] == "NOT_SUPPORTED"
    assert summary["causal_claim"] is False


def test_baseline_compare_pass_and_fail():
    baseline = {"delta_s_shock": 0.0013356553564737824, "delta_gap_shock_full_float": "A CONFIRMAR"}
    good = compare_baseline({"delta_s_shock": 0.0013356553564737824, "delta_gap_shock_full_float": "A CONFIRMAR"}, baseline)
    assert {row["status"] for row in good} == {"PASS", "BLOCKED"}
    bad = compare_baseline({"delta_s_shock": 0.2}, baseline)
    assert any(row["metric"] == "delta_s_shock" and row["status"] == "FAIL" for row in bad)
    assert any(row["metric"] == "delta_gap_shock_full_float" and row["status"] == "BLOCKED" and row["observed"] is None for row in bad)


def test_duplicate_csv_in_zip_is_rejected(tmp_path):
    archive = tmp_path / "dup.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("a/studentInfo.csv", "id\n")
        handle.writestr("b/studentInfo.csv", "id\n")
    with pytest.raises(RuntimeError, match="duplicado"):
        safe_extract(archive, tmp_path / "out")


def test_changed_input_drops_downstream_checkpoint(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    target = raw / "studentInfo.csv"
    target.write_text("a\n", encoding="utf-8")
    ctx = Context(output_dir=tmp_path)
    ctx.ensure_dirs()
    state = {
        "fingerprint": fingerprint(),
        "stages": {
            "00": {"status": "PASS", "fingerprint": fingerprint(), "input_token": input_token(ctx, "00"), "output_token": output_token(ctx, "00")},
            "01": {"status": "PASS", "fingerprint": fingerprint(), "input_token": input_token(ctx, "01"), "output_token": output_token(ctx, "01")},
            "02": {"status": "PASS", "fingerprint": fingerprint(), "input_token": input_token(ctx, "02"), "output_token": output_token(ctx, "02")},
            "03": {"status": "PASS", "fingerprint": fingerprint(), "input_token": "stale", "output_token": "stale"},
        },
    }
    save_state(ctx, state)
    target.write_text("b\n", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(ROOT / "orquestrator.py"), "--stage", "03", "--output-dir", str(tmp_path), "--resume"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1
    saved = load_state(ctx)
    assert "03" not in saved["stages"]
    assert "02" not in saved["stages"]
    assert json.loads((ROOT / "baselines" / "aggregates.json").read_text(encoding="utf-8"))["delta_s_shock"] == 0.0013356553564737824
