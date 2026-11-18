import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.audit import assemble_found, classify_hashes, compare_baseline, mechanism_respects_clock, policy_contrasts, verdict  # noqa: E402
from jla.paths import Context  # noqa: E402
from jla.protocol import load_protocol  # noqa: E402
from jla.science import (  # noqa: E402
    EPS,
    KEYS,
    active_from_recency,
    observed_week_table,
    sha256_file,
    survival_at_18,
)
from jla.stage08_operator import population_report  # noqa: E402
from jla.stage08_operator import run as audit  # noqa: E402
import jla.stage08_operator as operator  # noqa: E402


class ConstantHazard:
    def __init__(self, value=0.2):
        self.value = float(value)

    def predict_proba(self, frame):
        p = np.full(len(frame), self.value)
        return np.column_stack([1.0 - p, p])


ConstantHazard.__module__ = "jla.stage08_operator"
operator.ConstantHazard = ConstantHazard


def _frame() -> pd.DataFrame:
    specs = [(1, "AAA", 4, 0, "M"), (2, "AAA", 8, 5, "F"), (3, "AAA", 3, None, "M"), (4, "AAA", 18, 1, "M"), (5, "AAA", 18, 2, "F"), (5, "BBB", 18, 2, "F")]
    rows = []
    for student, module, last, trigger, gender in specs:
        for week in range(last + 1):
            rows.append(
                {
                    "id_student": student,
                    "code_module": module,
                    "code_presentation": "2013J",
                    "week": week,
                    "event": 0,
                    "gender": gender,
                    "recency": 0 if trigger is None else int(week == trigger),
                    "total_clicks": 0.0,
                    "streak": 0,
                    "submitted_this_week": 0,
                    "s_star": np.nan if trigger is None else trigger,
                    "hazard_hat": 0.2,
                    "lag_available": int(week > 0),
                    "total_clicks_lag": 0.0,
                    "studied_credits": 60,
                    "num_of_prev_attempts": 0,
                    "recency_lag": 4.0,
                    "streak_lag": 0.0,
                    "submitted_lag": 0.0,
                    "highest_education": "A Level or Equivalent",
                    "age_band": "0-35",
                }
            )
    return pd.DataFrame(rows)


def _write_mock(tmp_path, *, bad_curve: bool = False) -> Context:
    frame = _frame()
    model = ConstantHazard()
    predicted = model.predict_proba(frame)[:, 1]
    shock = predicted.copy()
    active = active_from_recency(frame)
    shock[active] = np.clip(predicted[active] * (1.0 - 0.08), EPS, 1.0 - EPS)
    mech = mechanism_respects_clock(frame, predicted, model)["mech"]
    base_s = survival_at_18(frame, predicted)
    shock_s = survival_at_18(frame, shock)
    mech_s = survival_at_18(frame, mech)
    both = base_s.merge(shock_s[KEYS + ["S"]], on=KEYS, suffixes=("_base", "_shock"))
    both = both.merge(mech_s[KEYS + ["S"]].rename(columns={"S": "S_mech"}), on=KEYS)
    both["female"] = both["gender"].astype(str).eq("F")
    both["dS_shock"] = both["S_shock"] - both["S_base"]
    both["dS_mech"] = both["S_mech"] - both["S_base"]
    ctx = Context(output_dir=tmp_path)
    ctx.ensure_dirs()
    private = ctx.results / "private"
    private.mkdir(parents=True, exist_ok=True)
    frame.to_csv(private / "pp_test_scores.csv", index=False)
    scenario = frame[KEYS + ["week", "s_star"]].copy()
    scenario["h_base"] = predicted
    scenario["h_shock"] = shock
    scenario["h_mech"] = mech
    scenario.to_csv(private / "scenario_rows.csv", index=False)
    both.to_csv(private / "r18.csv", index=False)
    (ctx.results / "p3_metrics.json").write_text(json.dumps(policy_contrasts(both)), encoding="utf-8")
    model_path = ctx.models / "hazard.joblib"
    joblib.dump(model, model_path)
    hashes = {
        "pp_test_scores.csv": sha256_file(private / "pp_test_scores.csv"),
        "scenario_rows.csv": sha256_file(private / "scenario_rows.csv"),
        "r18.csv": sha256_file(private / "r18.csv"),
        "hazard.joblib": sha256_file(model_path),
    }
    (private / "scenario_hashes.json").write_text(json.dumps(hashes), encoding="utf-8")
    (private / "MOCK").write_text("fixture\n", encoding="utf-8")
    curve = observed_week_table(frame, predicted)
    if bad_curve:
        curve = curve.drop(columns=["n_enrollments", "prohibition", "interpretation"])
    curve.to_csv(ctx.curves / "survival_week.csv", index=False)
    return ctx


def _rehash(ctx) -> None:
    private = ctx.results / "private"
    hashes = {
        "pp_test_scores.csv": sha256_file(private / "pp_test_scores.csv"),
        "scenario_rows.csv": sha256_file(private / "scenario_rows.csv"),
        "r18.csv": sha256_file(private / "r18.csv"),
        "hazard.joblib": sha256_file(ctx.models / "hazard.joblib"),
    }
    (private / "scenario_hashes.json").write_text(json.dumps(hashes), encoding="utf-8")


def test_missing_private_inputs_do_not_pass(tmp_path):
    stale = tmp_path / "results"
    stale.mkdir(parents=True)
    (stale / "public_examples.json").write_text("{}", encoding="utf-8")
    result = audit(Context(output_dir=tmp_path))
    assert result["status"] == "NOT_RUN_SCIENCE"
    assert result["status"] != "PASS"
    assert not (tmp_path / "results" / "public_examples.json").exists()


def test_mock_fixture_runs_the_real_interface_and_says_so(tmp_path):
    before = (ROOT / "config" / "protocol.yaml").read_text(encoding="utf-8")
    result = audit(_write_mock(tmp_path))
    assert result["status"] == "PASS_MOCK"
    assert result["scope"] == "MOCK"
    assert result["publication_status"] == "BLOCKED"
    public = json.loads((tmp_path / "results" / "public_examples.json").read_text(encoding="utf-8"))
    assert public["scope"] == "PASS_MOCK"
    assert [item["label"] for item in public["examples"]] == ["A", "B", "C", "D"]
    assert "id_student" not in json.dumps(public["examples"])
    tests = json.loads((tmp_path / "results" / "operator_tests.json").read_text(encoding="utf-8"))
    assert all(item["result"] == "PASS" for item in tests)
    t8 = next(item for item in tests if item["test"] == "T8")
    assert "n_enrollments=3" in t8["evidence"] and "n_students=2" in t8["evidence"]
    t0 = next(item for item in tests if item["test"] == "T0")
    assert "PENDING" in t0["evidence"] and "HASH_VERIFIED" not in t0["evidence"]
    assert (ROOT / "config" / "protocol.yaml").read_text(encoding="utf-8") == before


def test_unlabeled_weekly_mean_fails(tmp_path):
    result = audit(_write_mock(tmp_path, bad_curve=True))
    assert result["status"] == "FAIL"
    tests = json.loads((tmp_path / "results" / "operator_tests.json").read_text(encoding="utf-8"))
    assert any(item["test"] == "T7b" and item["result"] == "FAIL" for item in tests)


def test_distinct_denominators_and_duplicate_keys():
    table = pd.DataFrame(
        {
            "id_student": [5, 5],
            "code_module": ["AAA", "BBB"],
            "code_presentation": ["2013J", "2013J"],
            "S_base": [0.5, 0.4],
            "S_shock": [0.6, 0.5],
            "S_mech": [0.55, 0.45],
        }
    )
    report = population_report(table, require_frozen=False)
    assert report["ok"]
    assert report["n_enrollments"] > report["n_students"]
    frozen = population_report(table, require_frozen=True)
    assert not frozen["ok"]
    duplicated = pd.concat([table, table.iloc[[0]]], ignore_index=True)
    assert population_report(duplicated, require_frozen=False)["duplicate_keys"]


def test_tampered_score_fails_even_after_rehash(tmp_path):
    ctx = _write_mock(tmp_path)
    scores = pd.read_csv(ctx.results / "private" / "pp_test_scores.csv")
    scores["hazard_hat"] = 0.9
    scores.to_csv(ctx.results / "private" / "pp_test_scores.csv", index=False)
    _rehash(ctx)
    result = audit(ctx)
    assert result["status"] == "FAIL"
    assert not (tmp_path / "results" / "public_examples.json").exists()
    tests = json.loads((tmp_path / "results" / "operator_tests.json").read_text(encoding="utf-8"))
    assert any(item["test"] == "T_model" and item["result"] == "FAIL" for item in tests)


def test_tampered_shock_fails_the_parameter_check(tmp_path):
    ctx = _write_mock(tmp_path)
    scenario = pd.read_csv(ctx.results / "private" / "scenario_rows.csv")
    scenario["h_shock"] = scenario["h_base"]
    scenario.to_csv(ctx.results / "private" / "scenario_rows.csv", index=False)
    _rehash(ctx)
    result = audit(ctx)
    assert result["status"] == "FAIL"
    tests = json.loads((tmp_path / "results" / "operator_tests.json").read_text(encoding="utf-8"))
    assert any(item["test"] == "T9" and item["result"] == "FAIL" for item in tests)


def test_hash_pending_is_not_invented(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "studentInfo.csv").write_text("id\n", encoding="utf-8")
    protocol = load_protocol()
    before = dict(protocol["hashes"])
    rows = classify_hashes(raw, protocol["hashes"])
    assert protocol["hashes"] == before
    assert any(row["status"] == "PENDING" and row["expected"] is None and "observed" not in row for row in rows)
    known = next(row for row in rows if row["file"] == "studentInfo.csv")
    assert known["status"] == "FAIL"
    assert known["observed"] != known["expected"]


def test_baseline_uses_only_the_declared_source():
    parts = {
        "p1": {"n_enrollments": 32593},
        "p2": {"n_enrollments": 1, "n_test_rows": 232509, "weekly_auc_4dp": 0.81424},
        "p3": {"delta_s_shock": 0.0013356553564737824, "delta_gap_shock": -0.00003451331},
    }
    found = assemble_found(parts)
    assert found["n_enrollments"] == 32593
    assert "n_enrollments" not in found or found["n_enrollments"] != 1
    rows = compare_baseline(found, {"n_enrollments": 32593, "weekly_auc_4dp": 0.8142, "delta_gap_shock_10dp": -0.0000345133, "delta_gap_shock_full_float": "A CONFIRMAR"})
    assert verdict(rows) == "FAIL"
    assert any(row["status"] == "BLOCKED" for row in rows)
    passed = compare_baseline(found, {"n_enrollments": 32593, "n_test_rows": 232509, "weekly_auc_4dp": 0.8142})
    assert verdict(passed) == "PASS"
