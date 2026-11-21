import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.g2c2_execute import _ReloadedModel, score_arm  # noqa: E402
from jla.science import FEATURES, fit_one  # noqa: E402


def _frame() -> pd.DataFrame:
    rows = []
    for student in range(1, 9):
        for week in (0, 18):
            rows.append(
                {
                    "id_student": student,
                    "code_module": "AAA",
                    "code_presentation": "2013J",
                    "week": week,
                    "event": int(student % 2),
                    "studied_credits": 60,
                    "num_of_prev_attempts": 0,
                    "highest_education": "A Level or Equivalent",
                    "age_band": "0-35",
                    "gender": "F" if student % 2 else "M",
                    "lag_available": 0 if week == 0 else 1,
                    "total_clicks_lag": float(student),
                    "recency_lag": 0.0,
                    "streak_lag": 1.0,
                    "submitted_lag": 0.0,
                    "recency": 1,
                    "total_clicks": float(student),
                    "absent_record": 0,
                    "click_record": 1,
                    "partial_nominal_week": 0,
                    "split": "test" if student > 6 else "train",
                }
            )
    return pd.DataFrame(rows)


def _landmark(clock, frame, model, train_ids, *, require_frozen):
    _landmark.model = model
    return {
        "n_cases": 1,
        "n_controls": 1,
        "n_excluded": 0,
        "auc_unweighted": 0.5,
        "auc_unweighted_ci": [0.4, 0.6],
        "auc": 0.5,
        "auc_ci": [0.4, 0.6],
        "G18": 0.9,
        "ess_cases": 1.0,
        "ess_controls": 1.0,
        "frozen_ok": True,
        "snapshot_gap": 0.0,
        "n_without_week9": 0,
    }


def _contrasts(_both):
    return {
        "delta_s_shock": 0.0,
        "delta_s_shock_ci": [0.0, 0.0],
        "delta_s_mechanism": 0.0,
        "delta_s_mechanism_ci": [0.0, 0.0],
        "delta_gap_shock": 0.0,
        "delta_gap_shock_ci": [0.0, 0.0],
        "delta_gap_mechanism": 0.0,
        "delta_gap_mechanism_ci": [0.0, 0.0],
    }


def test_reloaded_model_reaches_landmark(monkeypatch, tmp_path: Path) -> None:
    import jla.g2c2_execute as execute

    seen = {}
    real_fit = fit_one

    def remember(train):
        seen["memory"] = real_fit(train)
        return seen["memory"]

    monkeypatch.setattr(execute, "fit_one", remember)
    monkeypatch.setattr(execute, "evaluate_landmark", _landmark)
    monkeypatch.setattr(execute, "clock_frame", lambda enrollments, arm: pd.DataFrame())
    monkeypatch.setattr(execute, "mechanism_respects_clock", lambda frame, hazard, model: {"mech": hazard.copy(), "action_unchanged": True, "outside_unchanged": True, "response": np.zeros(len(frame), dtype=bool)})
    monkeypatch.setattr(execute, "policy_contrasts", _contrasts)
    monkeypatch.setattr(execute, "_bootstrap_rows", lambda both, arm: [])
    score_arm(_frame(), pd.DataFrame(), set(), "B", tmp_path, persist=True)
    path = tmp_path / "private" / "B" / "model.joblib"
    loaded = joblib.load(path)
    assert isinstance(_landmark.model, _ReloadedModel)
    assert _landmark.model.model is not seen["memory"]
    probe = _frame().loc[_frame()["split"] == "test", FEATURES]
    assert float(np.max(np.abs(loaded.predict_proba(probe)[:, 1] - seen["memory"].predict_proba(probe)[:, 1]))) <= 1e-9
    assert _landmark.model.calls >= 1


def test_default_score_does_not_write_a_model(monkeypatch, tmp_path: Path) -> None:
    import jla.g2c2_execute as execute

    monkeypatch.setattr(execute, "evaluate_landmark", _landmark)
    monkeypatch.setattr(execute, "clock_frame", lambda enrollments, arm: pd.DataFrame())
    monkeypatch.setattr(execute, "mechanism_respects_clock", lambda frame, hazard, model: {"mech": hazard.copy(), "action_unchanged": True, "outside_unchanged": True, "response": np.zeros(len(frame), dtype=bool)})
    monkeypatch.setattr(execute, "policy_contrasts", _contrasts)
    monkeypatch.setattr(execute, "_bootstrap_rows", lambda both, arm: [])
    score_arm(_frame(), pd.DataFrame(), set(), "B", tmp_path, persist=False)
    assert not (tmp_path / "private" / "B" / "model.joblib").exists()
