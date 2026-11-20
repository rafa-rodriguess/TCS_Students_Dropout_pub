import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from g2c2_reproduction import main  # noqa: E402
from jla.g2c2 import (  # noqa: E402
    FEATURES,
    LEAKAGE,
    MethodStop,
    bootstrap_catalog,
    clock_frame,
    indicator_catalog,
    model_specification,
    panel,
    preflight_decision,
    student_group_splits,
)
from jla.science import FORBIDDEN  # noqa: E402


def _enrollments() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_student": [1, 1, 2, 3],
            "code_module": ["AAA", "BBB", "AAA", "AAA"],
            "code_presentation": ["2014J", "2014J", "2014J", "2014J"],
            "final_result": ["Withdrawn", "Pass", "Withdrawn", "Fail"],
            "date_unregistration": [14, np.nan, -3, 10],
            "t_last_obs_week": [1, 0, 2, 0],
            "module_presentation_length": [20, 16, 30, 16],
        }
    )


def _conflict(frame: pd.DataFrame) -> pd.Series:
    return (frame["id_student"].eq(3)).reset_index(drop=True)


def _clicks() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_student": [1],
            "code_module": ["BBB"],
            "code_presentation": ["2014J"],
            "week": [0],
            "total_clicks": [5.0],
        }
    )


def _empty_submissions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_student": pd.Series(dtype="int64"),
            "code_module": pd.Series(dtype="object"),
            "code_presentation": pd.Series(dtype="object"),
            "week": pd.Series(dtype="int64"),
            "submitted_this_week": pd.Series(dtype="int64"),
        }
    )


def test_enrollment_composition_and_event_week():
    clock = clock_frame(_enrollments(), "B", _conflict(_enrollments()))
    event = clock.loc[clock["id_student"].eq(1) & clock["code_module"].eq("AAA")].iloc[0]
    passed = clock.loc[clock["code_module"].eq("BBB")].iloc[0]
    early = clock.loc[clock["id_student"].eq(2)].iloc[0]
    flagged = clock.loc[clock["id_student"].eq(3)].iloc[0]
    assert int(event["t_final_week"]) == 2 and event["clock_reason"] == "event"
    assert int(passed["t_final_week"]) == 2 and passed["clock_reason"] == "nominal"
    assert int(early["t_final_week"]) == 2 and early["clock_reason"] == "withdrawn_without_v6_event"
    assert int(flagged["conflict_fail"]) == 1 and flagged["clock_reason"] == "nominal"
    assert int(event["t_event_week"]) == 2


def test_historical_arm_does_not_open_nominal_week():
    clock = clock_frame(_enrollments(), "A", None)
    passed = clock.loc[clock["code_module"].eq("BBB")].iloc[0]
    assert int(passed["t_final_week"]) == 0
    assert passed["clock_reason"] == "last_vle"


def test_silent_weeks_partial_final_row_and_lag():
    frame = panel(_enrollments(), _clicks(), _empty_submissions(), "B", _conflict(_enrollments()))
    passed = frame.loc[frame["code_module"].eq("BBB")].sort_values("week")
    assert passed["week"].tolist() == [0, 1, 2]
    assert int(passed.loc[passed["week"].eq(2), "partial_nominal_week"].iloc[0]) == 1
    assert int(passed.loc[passed["week"].eq(0), "absent_record"].iloc[0]) == 0
    assert int(passed.loc[passed["week"].eq(1), "absent_record"].iloc[0]) == 1
    assert float(passed.loc[passed["week"].eq(1), "total_clicks"].iloc[0]) == 0.0
    assert float(passed.loc[passed["week"].eq(1), "total_clicks_lag"].iloc[0]) == 5.0
    assert int(passed.loc[passed["week"].eq(0), "lag_available"].iloc[0]) == 0
    assert set(FEATURES) & LEAKAGE == set()
    assert "date_registration" in LEAKAGE
    assert "total_clicks" in FORBIDDEN


def test_b9_drops_only_the_explicit_mask_and_refuses_to_guess():
    try:
        clock_frame(_enrollments(), "B-9", None)
    except MethodStop as exc:
        assert "predicado" in str(exc)
    else:
        raise AssertionError("B-9 sem máscara deveria parar")
    kept = clock_frame(_enrollments(), "B-9", _conflict(_enrollments()))
    assert set(kept["id_student"]) == {1, 2}
    assert len(kept) == 3


def test_grouped_splits_do_not_use_integer_cv_and_keep_students_out():
    spec = model_specification()
    assert spec["cv"] == "GroupKFold_splits_by_id_student"
    assert spec["ensemble"] is False
    assert spec["cv_integer_forbidden"] is True
    rows = []
    for student in range(10):
        for week in (0, 1):
            rows.append({"id_student": student, "event": int(student == week), "week": week})
    splits = student_group_splits(pd.DataFrame(rows), n_splits=spec["n_splits"])
    assert len(splits) == 5


def test_catalogs_drop_numeric_targets_and_match_the_eight_gaps():
    indicators = indicator_catalog(ROOT / "baselines" / "a8_g2c2_dev_targets.csv")
    contrasts = bootstrap_catalog(ROOT / "baselines" / "a8_g2c2_bootstrap_targets.csv")
    assert indicators["n"] == 99 and indicators["unavailable"] == 8 and indicators["scheduled"] == 91
    assert contrasts["n"] == 12
    assert "value" not in indicators["rows"][0]
    assert "point" not in contrasts["rows"][0]
    decision = preflight_decision()
    assert decision["decision"] == "STOP"
    assert decision["g2c2_numeric_pass"] == "NO-GO"


def test_entrypoint_refuses_fit_and_leaves_the_historical_runner_alone():
    try:
        main(["--fit"])
    except Exception as exc:
        assert type(exc).__name__ == "FitForbidden"
    else:
        raise AssertionError("fit deveria ser recusado")
    assert main(["--plan"]) == 0
    assert main(["--preflight"]) == 0
    source = (ROOT / "orquestrator.py").read_text(encoding="utf-8")
    assert "g2c2" not in source
