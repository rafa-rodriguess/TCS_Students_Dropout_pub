import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jla.audit import compare_baseline  # noqa: E402


def _row(found, baseline, metric):
    rows = compare_baseline(found, baseline)
    return next(row for row in rows if row["metric"] == metric)


def test_scalar_10dp_pass_and_fail():
    passed = _row({"delta_gap_shock_10dp": -3.451326577386116e-05}, {"delta_gap_shock_10dp": -3.45133e-05}, "delta_gap_shock_10dp")
    failed = _row({"delta_gap_shock_10dp": -3.4514e-05}, {"delta_gap_shock_10dp": -3.45133e-05}, "delta_gap_shock_10dp")
    assert passed["status"] == "PASS" and passed["tolerance"] == "10dp"
    assert failed["status"] == "FAIL" and failed["tolerance"] == "10dp"


def test_ci_10dp_matches_each_rounded_bound():
    expected = [-0.0000930654, 0.000017181]
    observed = [-0.00009306538999666047, 0.000017180974929287262]
    row = _row({"delta_gap_shock_ci_10dp": observed}, {"delta_gap_shock_ci_10dp": expected}, "delta_gap_shock_ci_10dp")
    assert row["status"] == "PASS"
    assert row["tolerance"] == "10dp"


def test_ci_10dp_rejects_a_bound_that_changes_rounding():
    expected = [-0.0000930654, 0.000017181]
    shifted = [-0.0000930654 + 1e-9, 0.000017181]
    row = _row({"delta_gap_shock_ci_10dp": shifted}, {"delta_gap_shock_ci_10dp": expected}, "delta_gap_shock_ci_10dp")
    assert row["status"] == "FAIL"
    assert row["tolerance"] == "10dp"
    assert round(shifted[0], 10) != round(expected[0], 10)


def test_ci_10dp_rejects_order_length_and_non_list():
    expected = [-0.0000930654, 0.000017181]
    observed = [-0.00009306538999666047, 0.000017180974929287262]
    reversed_row = _row({"delta_gap_shock_ci_10dp": list(reversed(observed))}, {"delta_gap_shock_ci_10dp": expected}, "delta_gap_shock_ci_10dp")
    short = _row({"delta_gap_shock_ci_10dp": observed[:1]}, {"delta_gap_shock_ci_10dp": expected}, "delta_gap_shock_ci_10dp")
    scalar = _row({"delta_gap_shock_ci_10dp": observed[0]}, {"delta_gap_shock_ci_10dp": expected}, "delta_gap_shock_ci_10dp")
    assert reversed_row["status"] == "FAIL"
    assert short["status"] == "FAIL"
    assert scalar["status"] == "FAIL"
    assert reversed_row["tolerance"] == short["tolerance"] == scalar["tolerance"] == "10dp"


def test_plain_list_keeps_absolute_tolerance():
    inside = _row({"delta_s_shock_ci": [0.0, 5e-13]}, {"delta_s_shock_ci": [0.0, 0.0]}, "delta_s_shock_ci")
    outside = _row({"delta_s_shock_ci": [0.0, 2e-12]}, {"delta_s_shock_ci": [0.0, 0.0]}, "delta_s_shock_ci")
    assert inside["status"] == "PASS" and inside["tolerance"] == 1e-12
    assert outside["status"] == "FAIL" and outside["tolerance"] == 1e-12


def test_nan_and_inf_never_pass():
    for bad in (math.nan, math.inf, -math.inf):
        rounded = _row({"delta_gap_shock_ci_10dp": [bad, 0.0]}, {"delta_gap_shock_ci_10dp": [0.0, 0.0]}, "delta_gap_shock_ci_10dp")
        absolute = _row({"delta_s_shock_ci": [bad, 0.0]}, {"delta_s_shock_ci": [bad, 0.0]}, "delta_s_shock_ci")
        assert rounded["status"] == "FAIL"
        assert absolute["status"] == "FAIL"


def test_unconfirmed_stays_blocked_and_missing_fails():
    blocked = _row({"delta_gap_shock_full_float": 1.0}, {"delta_gap_shock_full_float": "A CONFIRMAR"}, "delta_gap_shock_full_float")
    missing = _row({}, {"n_enrollments": 32593}, "n_enrollments")
    exact = _row({"n_enrollments": 32593}, {"n_enrollments": 32593}, "n_enrollments")
    off_by_one = _row({"n_enrollments": 32594}, {"n_enrollments": 32593}, "n_enrollments")
    assert blocked["status"] == "BLOCKED" and blocked["expected"] == "A CONFIRMAR"
    assert missing["status"] == "FAIL" and missing["observed"] is None
    assert exact["status"] == "PASS" and exact["tolerance"] == "exato"
    assert off_by_one["status"] == "FAIL"
