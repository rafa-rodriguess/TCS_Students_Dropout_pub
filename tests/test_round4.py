import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jla.audit import (  # noqa: E402
    SCORE_COLUMNS,
    assemble_found,
    compare_baseline,
    example_study,
    policy_contrasts,
    scenario_gender,
    verdict,
)
from jla.checkpoint import fingerprint, input_token, load_state, output_token, save_state  # noqa: E402
from jla.paths import Context  # noqa: E402


def test_score_header_roundtrip_has_no_repeated_column(tmp_path):
    assert len(SCORE_COLUMNS) == len(set(SCORE_COLUMNS))
    frame = pd.DataFrame([{column: "A" for column in SCORE_COLUMNS}])
    path = tmp_path / "scores.csv"
    frame.to_csv(path, index=False)
    loaded = pd.read_csv(path)
    assert list(loaded.columns) == SCORE_COLUMNS


def test_landmark_examples_and_both_contrasts_are_numeric():
    study = example_study()
    assert study["private"]["label"].tolist() == ["A", "B", "C", "D"]
    assert study["private"]["id_student"].nunique() == 4
    public = json.dumps(study["public"])
    assert "id_student" not in public
    assert all(item["result"] == "PASS" for item in study["tests"])
    contrasts = study["contrasts"]
    assert contrasts["n_r18_enrollments"] == contrasts["n_r18_students"] == 2
    for key in ("delta_s_shock", "delta_s_mechanism"):
        low, high = contrasts[f"{key}_ci"]
        assert low <= contrasts[key] <= high
    assert contrasts["delta_gap_shock_ci"] is not None
    assert contrasts["delta_gap_mechanism_ci"] is not None
    table = study["both"]
    shock = scenario_gender(table, "S_shock", "dS_shock")
    mechanism = scenario_gender(table, "S_mech", "dS_mech")
    assert shock["n_female_enrollments"] and shock["n_male_enrollments"]
    assert shock["base_gap"] != mechanism["scenario_gap"] or shock["delta_gap"] != mechanism["delta_gap"]
    assert shock["causal_claim"] is False and mechanism["disability"] == "NOT_SUPPORTED"
    again = policy_contrasts(table)
    assert again["delta_s_shock"] == contrasts["delta_s_shock"]


def test_baseline_pass_fail_and_unconfirmed_float():
    parts = {"p1": {"n_enrollments": 32593}, "p3": {"delta_s_shock": 0.0013356553564737824, "delta_gap_shock": -0.00003451331}}
    found = assemble_found(parts)
    passed = compare_baseline(found, {"n_enrollments": 32593, "delta_s_shock": 0.0013356553564737824, "delta_gap_shock_10dp": -0.0000345133})
    assert verdict(passed) == "PASS"
    missing = compare_baseline(found, {"n_students": 28785})
    assert verdict(missing) == "FAIL"
    blocked = compare_baseline(found, {"n_enrollments": 32593, "delta_gap_shock_full_float": "A CONFIRMAR"})
    assert verdict(blocked) == "FAIL"
    assert any(row["status"] == "BLOCKED" for row in blocked)


def test_missing_r18_invalidates_the_policy_stage(tmp_path):
    private = tmp_path / "results" / "private"
    private.mkdir(parents=True)
    r18 = private / "r18.csv"
    r18.write_text("id_student\n1\n", encoding="utf-8")
    ctx = Context(output_dir=tmp_path)
    ctx.ensure_dirs()
    current = fingerprint()
    state = {"fingerprint": current, "stages": {}}
    for name in ("00", "01", "02", "03", "04", "05", "06", "07"):
        state["stages"][name] = {"status": "PASS", "fingerprint": current, "input_token": input_token(ctx, name), "output_token": output_token(ctx, name)}
    save_state(ctx, state)
    r18.unlink()
    run = subprocess.run(
        [sys.executable, str(ROOT / "orquestrator.py"), "--stage", "08", "--output-dir", str(tmp_path), "--resume"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1
    saved = load_state(ctx)
    assert "07" not in saved["stages"]
    assert "06" in saved["stages"]
