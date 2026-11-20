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
    bootstrap_catalog,
    clock_frame,
    contract_checklist,
    fail9_mask,
    indicator_catalog,
    model_specification,
    panel,
    post_nominal_diagnosis,
    preflight_decision,
    student_group_splits,
)
from jla.g2c2_metrics import landmark_gate, synthetic_end_to_end  # noqa: E402
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
    clock = clock_frame(_enrollments(), "B")
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
    clock = clock_frame(_enrollments(), "A")
    passed = clock.loc[clock["code_module"].eq("BBB")].iloc[0]
    assert int(passed["t_final_week"]) == 0
    assert passed["clock_reason"] == "last_vle"


def test_silent_weeks_partial_final_row_and_lag():
    frame = panel(_enrollments(), _clicks(), _empty_submissions(), "B")
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


def test_fail9_keeps_every_numeric_sign_and_drops_only_that_enrollment():
    sample = pd.DataFrame(
        {
            "id_student": [9, 9, 9, 9],
            "code_module": ["AAA", "BBB", "CCC", "DDD"],
            "code_presentation": ["2014J"] * 4,
            "final_result": ["Fail", "Fail", "Fail", "Pass"],
            "date_unregistration": [-4, 0, 12, np.nan],
        }
    )
    mask = fail9_mask(sample)
    assert mask.tolist() == [True, True, True, False]
    blank = sample.copy()
    blank["date_unregistration"] = [np.nan, "NA", "", None]
    assert fail9_mask(blank).tolist() == [False, False, False, False]
    mixed = _enrollments()
    extra = mixed.iloc[[1]].copy()
    extra["id_student"] = 3
    extra["code_module"] = "CCC"
    extra["final_result"] = "Pass"
    extra["date_unregistration"] = np.nan
    cohort = pd.concat([mixed, extra], ignore_index=True)
    kept = clock_frame(cohort, "B-9")
    assert not ((kept["id_student"].eq(3)) & (kept["code_module"].eq("AAA"))).any()
    assert ((kept["id_student"].eq(3)) & (kept["code_module"].eq("CCC"))).any()


def test_activity_after_nominal_stays_out_of_the_risk_set():
    cohort = _enrollments()
    cohort.loc[cohort["code_module"].eq("BBB"), "t_last_obs_week"] = 6
    clicks = pd.concat(
        [
            _clicks(),
            pd.DataFrame(
                {
                    "id_student": [1, 1],
                    "code_module": ["BBB", "BBB"],
                    "code_presentation": ["2014J", "2014J"],
                    "week": [2, 6],
                    "total_clicks": [4.0, 9.0],
                }
            ),
        ],
        ignore_index=True,
    )
    submitted = _empty_submissions()
    raw_rows = len(clicks)
    clock = clock_frame(cohort, "B")
    passed = clock.loc[clock["code_module"].eq("BBB")].iloc[0]
    assert int(passed["t_final_week"]) == 2
    assert passed["clock_reason"] == "nominal"
    frame = panel(cohort, clicks, submitted, "B")
    weeks = frame.loc[frame["code_module"].eq("BBB"), "week"].tolist()
    assert weeks == [0, 1, 2]
    assert 6 not in weeks
    assert len(clicks) == raw_rows
    diagnosis = post_nominal_diagnosis(cohort, clicks, submitted)
    assert diagnosis["late_click_rows"] == 1
    assert diagnosis["late_enrollments"] == 1


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
    assert decision["decision"] == "GO"
    assert decision["execution"] == "STOP"
    assert decision["r1_execution"] == "NO-GO"
    assert decision["g2c2_numeric_pass"] == "NO-GO"
    checklist = contract_checklist()
    assert [item["code"] for item in checklist] == [f"B{number:02d}" for number in range(1, 17)]
    assert {item["status"] for item in checklist} <= {"PASS", "LIMITAÇÃO", "STOP"}
    assert all(item["proof"] for item in checklist)


def test_synthetic_metrics_do_not_fit_oulad_or_read_targets():
    proof = synthetic_end_to_end()
    assert proof["oulad_fit"] is False and proof["targets_used"] is False and proof["source"] == "synthetic"
    assert proof["bootstrap_draws"] == 500 and proof["bootstrap_model"] == "fixed" and proof["bootstrap_n_valid"] >= 50
    assert 0.0 < proof["auc"] < 1.0
    assert proof["brier"] >= 0.0 and proof["ece15"] >= 0.0
    assert proof["landmark_cases"] == 1 and proof["landmark_controls"] == 2 and proof["landmark_excluded"] == 1
    assert proof["landmark_status"] == "PASS"
    assert proof["ess_cases"] > 0 and proof["ess_controls"] > 0
    assert proof["shock_changes_active_weeks"] is True
    assert proof["mechanism_changes_response_only"] is True
    assert proof["fixed_cohort_nonincreasing"] is True
    assert "coorte fixa" in proof["variable_composition_label"]
    assert landmark_gate(0.04) == "NO-GO"


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
