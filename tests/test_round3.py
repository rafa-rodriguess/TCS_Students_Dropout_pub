import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.audit import compare_baseline, mechanism_respects_clock, verdict  # noqa: E402
from jla.checkpoint import fingerprint, input_token, load_state, output_token, save_state  # noqa: E402
from jla.landmark import cohort_frame, evaluate_landmark, g_from_train_at_risk  # noqa: E402
from jla.paths import Context  # noqa: E402
from jla.science import FEATURES, STATICS, bootstrap, censoring_g  # noqa: E402


class _ClickModel:
    def predict_proba(self, frame):
        p = frame["total_clicks_lag"].to_numpy(dtype=float) / 100.0
        return np.column_stack([1.0 - p, p])


class _ConstantModel:
    def predict_proba(self, frame):
        ones = np.full(len(frame), 0.1)
        return np.column_stack([1.0 - ones, ones])


def _statics():
    return {
        "studied_credits": 60,
        "num_of_prev_attempts": 0,
        "highest_education": "A Level or Equivalent",
        "age_band": "0-35",
        "gender": "F",
    }


def test_cohort_frame_keeps_statics_and_refuses_missing():
    enr = pd.DataFrame([{**{"id_student": 1, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 1}, **_statics()}])
    clicks = pd.DataFrame({"id_student": pd.Series(dtype="int64"), "code_module": pd.Series(dtype="object"), "code_presentation": pd.Series(dtype="object"), "week": pd.Series(dtype="int64"), "total_clicks": pd.Series(dtype="float64")})
    submitted = pd.DataFrame({"id_student": pd.Series(dtype="int64"), "code_module": pd.Series(dtype="object"), "code_presentation": pd.Series(dtype="object"), "week": pd.Series(dtype="int64"), "submitted_this_week": pd.Series(dtype="int64")})
    frame = cohort_frame(enr, clicks, submitted)
    assert set(STATICS).issubset(frame.columns)
    assert set(FEATURES).issubset(frame.columns)
    broken = enr.copy()
    broken["gender"] = np.nan
    with pytest.raises(RuntimeError, match="refusing to impute"):
        cohort_frame(broken, clicks, submitted)


def _panel_row(student, week, clicks, lag_clicks):
    return {
        **{"id_student": student, "code_module": "AAA", "code_presentation": "2013J"},
        **_statics(),
        "week": week,
        "total_clicks": clicks,
        "recency": 0,
        "streak": 1,
        "submitted_this_week": 0,
        "lag_available": 1,
        "total_clicks_lag": lag_clicks,
        "recency_lag": 0.0,
        "streak_lag": 1.0,
        "submitted_lag": 0.0,
        "event": 0,
    }


def test_landmark_uses_train_risk_and_week8_snapshot():
    rows = []
    for student, weeks in ((1, (8, 9)), (2, (8, 9)), (3, (8, 9)), (4, (8,))):
        for week in weeks:
            rows.append(_panel_row(student, week, 10.0 if week == 8 else 0.0, 10.0 if week == 9 else 0.0))
    frame = pd.DataFrame(rows)
    report = evaluate_landmark(
        pd.DataFrame(
            [
                {"id_student": 1, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 30},
                {"id_student": 2, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 1, "t_event_week": 10, "t_final_week": 10},
                {"id_student": 3, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 20},
                {"id_student": 4, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 8},
            ]
        ),
        frame,
        _ClickModel(),
        {1},
        require_frozen=False,
    )
    assert report["n_cases"] == 1
    assert report["n_without_week9"] >= 1
    assert isinstance(report["auc"], float)
    assert isinstance(report["auc_unweighted"], float)
    enr = pd.DataFrame(
        [
            {"id_student": 1, "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 30},
            {"id_student": 5, "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 10},
        ]
    )
    train_g = g_from_train_at_risk(enr, {1})
    pooled = censoring_g(enr)
    assert train_g[18] == 1.0
    assert pooled[18] < 1.0


def test_recency_change_with_unchanged_clicks_rewrites_the_next_hazard():
    frame = pd.DataFrame(
        {
            "id_student": [7, 7, 7, 7],
            "code_module": ["AAA"] * 4,
            "code_presentation": ["2013J"] * 4,
            "week": [0, 1, 2, 3],
            "recency": [1, 0, 0, 0],
            "total_clicks": [0.0, 0.0, 0.0, 0.0],
            "streak": [0, 0, 0, 0],
            "submitted_this_week": [0, 0, 0, 0],
            "event": [0, 0, 0, 0],
            "lag_available": [0, 1, 1, 1],
            "total_clicks_lag": [0.0, 0.0, 0.0, 0.0],
            "recency_lag": [0.0, 4.0, 4.0, 4.0],
            "streak_lag": [0.0, 0.0, 0.0, 0.0],
            "submitted_lag": [0.0, 0.0, 0.0, 0.0],
            "studied_credits": [60] * 4,
            "num_of_prev_attempts": [0] * 4,
            "highest_education": ["A Level or Equivalent"] * 4,
            "age_band": ["0-35"] * 4,
            "gender": ["M"] * 4,
            "s_star": [0, 0, 0, 0],
        }
    )
    base = np.full(4, 0.2)
    clock = mechanism_respects_clock(frame, base, _ConstantModel())
    assert clock["action_unchanged"]
    assert clock["response"].any()
    assert not np.allclose(clock["mech"][clock["response"]], base[clock["response"]])


def test_bootstrap_gap_on_a_toy_table_and_blocked_baseline_cannot_pass():
    table = pd.DataFrame(
        {
            "id_student": [1, 2, 3, 4],
            "dS": [0.1, 0.2, 0.3, 0.4],
            "S_base": [0.8, 0.7, 0.6, 0.5],
            "S_scenario": [0.9, 0.9, 0.9, 0.9],
            "female": [True, True, False, False],
        }
    )
    boot_s, boot_g = bootstrap(table, "dS")
    assert len(boot_s) == 500 and 0 < len(boot_g) <= 500
    blocked = compare_baseline({"weekly_auc_4dp": 0.81424}, {"weekly_auc_4dp": 0.8142, "delta_gap_shock_full_float": "A CONFIRMAR"})
    assert verdict(blocked) == "FAIL"
    missing = compare_baseline({}, {"n_enrollments": 32593})
    assert verdict(missing) == "FAIL"


def test_deleted_output_invalidates_later_stage(tmp_path):
    produced = tmp_path / "results" / "private" / "pp_test_scores.csv"
    produced.parent.mkdir(parents=True)
    produced.write_text("id\n1\n", encoding="utf-8")
    (tmp_path / "results" / "landmark.json").write_text("{}", encoding="utf-8")
    ctx = Context(output_dir=tmp_path)
    ctx.ensure_dirs()
    current = fingerprint()
    state = {"fingerprint": current, "stages": {}}
    for name in ("00", "01", "02", "03", "04", "05", "06"):
        state["stages"][name] = {"status": "PASS", "fingerprint": current, "input_token": input_token(ctx, name), "output_token": output_token(ctx, name)}
    save_state(ctx, state)
    produced.unlink()
    run = subprocess.run(
        [sys.executable, str(ROOT / "orquestrator.py"), "--stage", "06", "--output-dir", str(tmp_path), "--resume"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1
    saved = load_state(ctx)
    assert "06" not in saved["stages"]
    assert "05" not in saved["stages"]
