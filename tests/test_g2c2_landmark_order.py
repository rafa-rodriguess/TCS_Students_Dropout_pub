import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import jla.landmark as landmark  # noqa: E402
from jla.landmark import evaluate_landmark, score_ordered_landmark, sort_landmark_test  # noqa: E402


def test_sort_happens_before_case_control_concat() -> None:
    frame = pd.DataFrame(
        [
            {"id_student": 2, "code_module": "AAA", "code_presentation": "2014J", "y": 1, "hazard_hat": 0.8, "t_event_week": 10},
            {"id_student": 1, "code_module": "BBB", "code_presentation": "2013J", "y": 0, "hazard_hat": 0.2, "t_event_week": pd.NA},
        ]
    )
    ordered = sort_landmark_test(frame)
    assert list(ordered["id_student"]) == [1, 2]
    cases = ordered.loc[ordered["y"] == 1]
    controls = ordered.loc[ordered["y"] == 0]
    concatenated = pd.concat([cases, controls], ignore_index=True)
    resorted = concatenated.sort_values(["id_student", "code_module", "code_presentation"], kind="mergesort")
    assert list(concatenated["id_student"]) == [2, 1]
    assert list(resorted["id_student"]) == [1, 2]


def test_evaluate_landmark_uses_the_shared_scorer(monkeypatch) -> None:
    seen = {}
    real = landmark.score_ordered_landmark

    def wrapper(test, g):
        seen["ids"] = list(test["id_student"])
        return real(test, g)

    monkeypatch.setattr(landmark, "score_ordered_landmark", wrapper)
    rows = []
    for student, weeks, lag in ((2, (8, 9), 20.0), (1, (8, 9), 10.0)):
        for week in weeks:
            rows.append(
                {
                    "id_student": student,
                    "code_module": "AAA",
                    "code_presentation": "2013J",
                    "studied_credits": 60,
                    "num_of_prev_attempts": 0,
                    "highest_education": "A Level or Equivalent",
                    "age_band": "0-35",
                    "gender": "F",
                    "week": week,
                    "total_clicks": lag if week == 8 else 0.0,
                    "recency": 0,
                    "streak": 1,
                    "submitted_this_week": 0,
                    "lag_available": 1,
                    "total_clicks_lag": lag,
                    "recency_lag": 0.0,
                    "streak_lag": 1.0,
                    "submitted_lag": 0.0,
                    "event": 0,
                }
            )
    enrollments = pd.DataFrame(
        [
            {"id_student": 2, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 1, "t_event_week": 10, "t_final_week": 10},
            {"id_student": 1, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 30},
            {"id_student": 3, "code_module": "AAA", "code_presentation": "2013J", "event_withdrawn": 0, "t_event_week": np.nan, "t_final_week": 30},
        ]
    )

    class _Model:
        def predict_proba(self, frame):
            import numpy as np

            p = frame["total_clicks_lag"].to_numpy(dtype=float) / 100.0
            return np.column_stack([1.0 - p, p])

    report = evaluate_landmark(enrollments, pd.DataFrame(rows), _Model(), {3}, require_frozen=False)
    assert seen["ids"] == [2, 1]
    assert isinstance(report["auc"], float)
    scored = score_ordered_landmark(
        pd.DataFrame(
            [
                {"id_student": 2, "code_module": "AAA", "code_presentation": "2013J", "y": 1, "hazard_hat": 0.2, "t_event_week": 10},
                {"id_student": 1, "code_module": "AAA", "code_presentation": "2013J", "y": 0, "hazard_hat": 0.1, "t_event_week": pd.NA},
            ]
        ),
        {18: 1.0, 10: 1.0},
    )
    assert scored["landmark_fingerprint"] != scored["ipcw_fingerprint"]
