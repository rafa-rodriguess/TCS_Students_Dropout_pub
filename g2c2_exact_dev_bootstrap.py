#!/usr/bin/env python3
"""Replay único da ordem DEV: aluno, módulo, apresentação e semana.

Não reordena o bloco IPCW depois de concatenar casos e controles.
Não ajusta modelo e não testa outra permutação.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from jla.audit import ipcw_weights, landmark_roles  # noqa: E402
from jla.g2c2 import clock_frame  # noqa: E402
from jla.g2c2_gates import load_enrollments  # noqa: E402
from jla.landmark import g_from_train_at_risk  # noqa: E402
from jla.science import KEYS, clustered_auc, ess, student_disjoint_split  # noqa: E402

ORDER = ["id_student", "code_module", "code_presentation", "week"]
EXPECTED_CLUSTERS = {"A": 6256, "B": 7165, "B-9": 7164}
EXPECTED_FINGERPRINTS = {
    ("A", "landmark"): "14406b63104b5d40f5ae4ed659656c7fa7aa5532c416e2a7973e8398bf2f3a18",
    ("A", "ipcw"): "49f43dbb276754a1a937ed2c66688d768c207a22f57ac88bd31dc487ef9311d3",
    ("B", "landmark"): "83d8d2ea470caa1963a59517a5079115740bbf8c4865ea6b878d44e12134528c",
    ("B", "ipcw"): "19f47bb7ad9ae4c23f467869edbb98c1f33e6635e6f78fc30acffd791f4eeba2",
    ("B-9", "landmark"): "1d260d1f5f7d023c839e39e5f7d03078a9b8b69b36bcdb0c35a48c7188471276",
    ("B-9", "ipcw"): "952bb9588bbb19f2b796d63f53dfda0d973a614362a7c0178738180ebb89a155",
}
CORRECTED_B9 = {
    "G18": 0.9995014572725653,
    "ess_casos": 575.9999905762434,
    "auc_ipcw": 0.6609101511265063,
    "auc_ipcw_ci": (0.6374116319344114, 0.6840490660573272),
}
TOLERANCE = 1e-9


def _outside(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != ROOT and ROOT not in resolved.parents


def cluster_ids(frame: pd.DataFrame) -> np.ndarray:
    positions = frame.reset_index(drop=True).groupby("id_student", sort=False).indices
    return np.asarray(list(positions), dtype=np.int64)


def sequence_fingerprint(ids: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(ids, dtype=np.int64).tobytes()).hexdigest()


def exact_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["week"] = 8
    return work.sort_values(ORDER, kind="mergesort").reset_index(drop=True)


def _within(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= TOLERANCE


def replay_exact(raw: Path, scores: Path, arm: str) -> dict:
    enrollments, presentations = load_enrollments(raw)
    clock_a = clock_frame(enrollments, "A")
    is_test, _strata = student_disjoint_split(clock_a)
    train_ids = set(clock_a.loc[~is_test.to_numpy(), "id_student"])
    clock = clock_frame(enrollments, arm)
    roles = landmark_roles(clock)
    week9 = pd.read_csv(scores, usecols=KEYS + ["week", "hazard_hat"])
    week9 = week9.loc[week9["week"] == 9, KEYS + ["hazard_hat"]]
    if week9.duplicated(KEYS).any():
        raise RuntimeError("há mais de um escore na semana 9 para a mesma matrícula")
    labeled = roles.merge(week9, on=KEYS, how="left")
    labeled = labeled.loc[labeled["at_risk"]].copy()
    test = labeled.loc[~labeled["id_student"].isin(train_ids)].copy()
    missing = int(((test["y"] >= 0) & test["hazard_hat"].isna()).sum())
    if missing:
        raise RuntimeError(f"há {missing} casos ou controles sem escore fixo")
    snap = exact_snapshot(test)
    observed = snap.loc[snap["y"] >= 0, ["id_student", "hazard_hat", "y"]].rename(columns={"y": "event"})
    cases = snap.loc[snap["y"] == 1, ["id_student", "hazard_hat", "t_event_week"]]
    controls = snap.loc[snap["y"] == 0, ["id_student", "hazard_hat"]]
    g = g_from_train_at_risk(clock, train_ids)
    w_case, w_control = ipcw_weights(cases["t_event_week"].astype(int).to_numpy(), g, 18, int(len(controls)))
    ordered = pd.concat(
        [cases[["id_student", "hazard_hat"]].assign(event=1), controls.assign(event=0)],
        ignore_index=True,
    )
    weight = np.concatenate([w_case, w_control])
    landmark = clustered_auc(observed)
    ipcw = clustered_auc(ordered, weight)
    observed_clusters = cluster_ids(observed)
    ordered_clusters = cluster_ids(ordered)
    hazards = observed["hazard_hat"].to_numpy(dtype=float)
    return {
        "arm": arm,
        "stages": {
            "cohort": {"presentations": int(presentations), "enrollments": int(len(enrollments)), "test_at_risk": int(len(test))},
            "snapshot": {"n_cases": int((snap["y"] == 1).sum()), "n_controls": int((snap["y"] == 0).sum()), "n_excluded": int((snap["y"] < 0).sum())},
            "labels": {"observed_rows": int(len(observed)), "ordered_rows": int(len(ordered))},
            "predictions": {"missing": missing, "n_unique_hazard": int(pd.Series(hazards).nunique()), "hazard_min": float(hazards.min()), "hazard_max": float(hazards.max())},
            "weights": {"G18": g.get(18), "ess_cases": float(ess(w_case)), "weight_min": float(weight.min()), "weight_max": float(weight.max())},
            "order": {
                "n_clusters_observed": int(len(observed_clusters)),
                "n_clusters_ordered": int(len(ordered_clusters)),
                "landmark_fingerprint": sequence_fingerprint(observed_clusters),
                "ipcw_fingerprint": sequence_fingerprint(ordered_clusters),
            },
            "draws": {
                "landmark": {"auc": landmark["auc"], "ci_lo": landmark["ci_lo"], "ci_hi": landmark["ci_hi"], "n_valid": int(landmark["n_valid"])},
                "ipcw": {"auc": ipcw["auc"], "ci_lo": ipcw["ci_lo"], "ci_hi": ipcw["ci_hi"], "n_valid": int(ipcw["n_valid"])},
            },
        },
    }


def judge(report: dict, targets: pd.DataFrame) -> dict:
    rows = []
    passed = True
    for arm_report in report["arms"]:
        arm = arm_report["arm"]
        stages = arm_report["stages"]
        for kind, indicator in (("landmark", "auc_landmark"), ("ipcw", "auc_ipcw")):
            fingerprint = stages["order"][f"{kind}_fingerprint"]
            expected_fp = EXPECTED_FINGERPRINTS[(arm, kind)]
            draws = stages["draws"][kind]
            if arm == "B-9" and kind == "ipcw":
                expected_lo, expected_hi = CORRECTED_B9["auc_ipcw_ci"]
                comparator = "corrected_b9_ipcw"
            else:
                target = targets[(targets["indicator"] == indicator) & (targets["arm"] == arm)].iloc[0]
                expected_lo, expected_hi = float(target["ci_lo"]), float(target["ci_hi"])
                comparator = "historical_target"
            fp_ok = fingerprint == expected_fp
            lo_ok = _within(draws["ci_lo"], expected_lo)
            hi_ok = _within(draws["ci_hi"], expected_hi)
            clusters_ok = stages["order"]["n_clusters_observed"] == EXPECTED_CLUSTERS[arm] and stages["order"]["n_clusters_ordered"] == EXPECTED_CLUSTERS[arm]
            draws_ok = draws["n_valid"] == 500
            ok = fp_ok and lo_ok and hi_ok and clusters_ok and draws_ok
            passed = passed and ok
            rows.append(
                {
                    "arm": arm,
                    "indicator": indicator,
                    "comparator": comparator,
                    "fingerprint_match": fp_ok,
                    "ci_lo_diff": float(draws["ci_lo"]) - expected_lo,
                    "ci_hi_diff": float(draws["ci_hi"]) - expected_hi,
                    "n_valid": draws["n_valid"],
                    "pass": ok,
                }
            )
        if arm == "B-9":
            point_ok = _within(stages["draws"]["ipcw"]["auc"], CORRECTED_B9["auc_ipcw"])
            g_ok = _within(stages["weights"]["G18"], CORRECTED_B9["G18"])
            ess_ok = _within(stages["weights"]["ess_cases"], CORRECTED_B9["ess_casos"])
            passed = passed and point_ok and g_ok and ess_ok
            rows.append(
                {
                    "arm": arm,
                    "indicator": "b9_points",
                    "auc_ipcw_diff": float(stages["draws"]["ipcw"]["auc"]) - CORRECTED_B9["auc_ipcw"],
                    "G18_diff": float(stages["weights"]["G18"]) - CORRECTED_B9["G18"],
                    "ess_cases_diff": float(stages["weights"]["ess_cases"]) - CORRECTED_B9["ess_casos"],
                    "pass": point_ok and g_ok and ess_ok,
                }
            )
    return {"technical_diagnostic": "PASS" if passed else "STOP", "rows": rows}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="replay exato da ordem DEV no bootstrap do marco")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not _outside(args.data_dir) or not _outside(args.output_dir):
        print("dados e saída precisam ficar fora do checkout", file=sys.stderr)
        return 2
    private = args.output_dir / "private"
    if not all((private / arm / "test_scores.csv").is_file() for arm in ("A", "B", "B-9")):
        print(json.dumps({"technical_diagnostic": "STOP", "reason": "escores fixos da R1 ausentes"}))
        return 1
    report = {"fit": False, "order": ORDER, "arms": []}
    for arm in ("A", "B", "B-9"):
        report["arms"].append(replay_exact(args.data_dir, private / arm / "test_scores.csv", arm))
    report["judgment"] = judge(report, pd.read_csv(ROOT / "baselines" / "a8_g2c2_dev_targets.csv"))
    print(json.dumps(report))
    return 0 if report["judgment"]["technical_diagnostic"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
