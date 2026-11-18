import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.science import response_plan, rewritten_features  # noqa: E402
from jla.stage08_operator import t4_clock_predicate, t4_evaluate  # noqa: E402


def _row(week, clicks, recency_lag, s_star=1):
    return {
        "id_student": 1,
        "code_module": "AAA",
        "code_presentation": "2013J",
        "week": week,
        "recency": 1 if week == 1 else 0,
        "total_clicks": clicks,
        "streak": 0,
        "submitted_this_week": 0,
        "event": 0,
        "lag_available": int(week > 0),
        "total_clicks_lag": 0.0,
        "recency_lag": recency_lag,
        "streak_lag": 0.0,
        "submitted_lag": 0.0,
        "studied_credits": 60,
        "num_of_prev_attempts": 0,
        "highest_education": "A Level or Equivalent",
        "age_band": "0-35",
        "gender": "F",
        "s_star": s_star,
    }


def _frame():
    # Semana 3 é s*+2: clique atual 0 e ação anterior 7.
    # Semana 4 é s*+3: a ação herdada da semana 3 é 0.
    return pd.DataFrame(
        [
            _row(1, 3.0, 2.0),
            _row(2, 7.0, 2.0),
            _row(3, 0.0, 5.0),
            _row(4, 1.0, 5.0),
        ]
    )


def test_current_zero_with_positive_previous_action_passes():
    frame = _frame()
    plan = response_plan(frame)
    week = frame["week"].to_numpy()
    assert plan.loc[week == 3, "first_response"].item()
    assert plan.loc[week == 4, "second_response"].item()
    assert not plan.loc[week == 2, "first_response"].item()
    result = t4_clock_predicate(frame)
    assert result["ok"]
    assert result["forced_moves"]
    assert result["identity"]
    assert result["zero_action_stays_zero"]
    forced = rewritten_features(frame, plan, 0.0, 0.0, enabled=True)
    outside = ~plan["first_response"].to_numpy(dtype=bool) & ~plan["second_response"].to_numpy(dtype=bool)
    assert np.allclose(forced.loc[outside, "total_clicks_lag"], frame.loc[outside, "total_clicks_lag"])


def test_zero_action_keeps_rewritten_lag_at_zero():
    frame = _frame()
    plan = response_plan(frame)
    forced = rewritten_features(frame, plan, 0.0, 0.0, enabled=True)
    week4 = frame["week"].to_numpy() == 4
    assert plan.loc[week4, "clicks_action"].item() == 0.0
    assert forced.loc[week4, "total_clicks_lag"].item() == 0.0


def test_lag_different_from_action_fails():
    response = np.array([True])
    ok = t4_evaluate(response, np.array([0.0]), np.array([4.0]), np.array([1.0]), np.array([7.0]))
    assert not ok["identity"]
    assert not ok["ok"]


def test_zero_action_rewritten_positive_fails():
    response = np.array([True])
    ok = t4_evaluate(response, np.array([0.0]), np.array([4.0]), np.array([3.0]), np.array([0.0]))
    assert not ok["zero_action_stays_zero"]
    assert not ok["ok"]


def test_no_response_or_unforced_state_fails():
    quiet = _frame()
    quiet["s_star"] = np.nan
    assert not t4_clock_predicate(quiet)["response_any"]
    assert not t4_clock_predicate(quiet)["ok"]
    already = _frame()
    already["recency_lag"] = 0.0
    parked = t4_clock_predicate(already)
    assert parked["response_any"]
    assert not parked["forced_moves"]
    assert not parked["ok"]

