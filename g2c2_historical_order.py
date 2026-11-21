#!/usr/bin/env python3
"""Replay diagnóstico da ordem histórica por KEYS, sem refit.

A ordem testada é uma só: code_module, code_presentation, id_student e week.
Não procura outra permutação.
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
from jla.science import KEYS, clustered_auc, student_disjoint_split  # noqa: E402

HISTORICAL_KEYS = ["code_module", "code_presentation", "id_student", "week"]
CORRECTED_B9_IPCW = (0.6374116319344114, 0.6840490660573272)


def _outside(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != ROOT and ROOT not in resolved.parents


def sequence_fingerprint(ids: np.ndarray) -> str:
    encoded = np.asarray(ids, dtype=np.int64)
    return hashlib.sha256(encoded.tobytes()).hexdigest()


def cluster_ids(frame: pd.DataFrame) -> np.ndarray:
    positions = frame.reset_index(drop=True).groupby("id_student", sort=False).indices
    return np.asarray(list(positions), dtype=np.int64)


def _public(result: dict) -> dict:
    return {"auc": result["auc"], "ci_lo": result["ci_lo"], "ci_hi": result["ci_hi"], "n_valid": int(result["n_valid"]), "draws": int(result["draws"])}


def historical_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["week"] = 8
    return work.sort_values(HISTORICAL_KEYS, kind="mergesort").reset_index(drop=True)


def replay_historical(raw: Path, scores: Path, arm: str) -> dict:
    enrollments, _presentations = load_enrollments(raw)
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
        raise RuntimeError(f"há {missing} casos ou controles sem escore fixo na semana 9")
    snap = historical_snapshot(test)
    observed = snap.loc[snap["y"] >= 0, ["id_student", "hazard_hat", "y"]].rename(columns={"y": "event"})
    id_sorted = observed.sort_values("id_student", kind="mergesort").reset_index(drop=True)
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
    id_clusters = cluster_ids(id_sorted)
    roles_observed = test.loc[test["y"] >= 0, ["id_student", "hazard_hat", "y"]].rename(columns={"y": "event"})
    roles_clusters = cluster_ids(roles_observed)
    mismatch = np.flatnonzero(observed_clusters != id_clusters)
    return {
        "arm": arm,
        "n_cases": int((snap["y"] == 1).sum()),
        "n_controls": int((snap["y"] == 0).sum()),
        "n_excluded": int((snap["y"] < 0).sum()),
        "G18": g.get(18),
        "n_clusters_observed": int(len(observed_clusters)),
        "n_clusters_ordered": int(len(ordered_clusters)),
        "landmark": _public(landmark),
        "ipcw": _public(ipcw),
        "fingerprints_int64": {
            "observed_rows": sequence_fingerprint(observed["id_student"].to_numpy()),
            "observed_clusters": sequence_fingerprint(observed_clusters),
            "ordered_rows": sequence_fingerprint(ordered["id_student"].to_numpy()),
            "ordered_clusters": sequence_fingerprint(ordered_clusters),
            "id_sorted_clusters": sequence_fingerprint(id_clusters),
            "roles_clusters": sequence_fingerprint(roles_clusters),
        },
        "cluster_order_equals_id_sort": bool(np.array_equal(observed_clusters, id_clusters)),
        "cluster_order_equals_roles": bool(np.array_equal(observed_clusters, roles_clusters)),
        "observed_cluster_equals_ordered": bool(np.array_equal(observed_clusters, ordered_clusters)),
        "first_cluster_index_differing_from_id_sort": None if len(mismatch) == 0 else int(mismatch[0]),
        "n_cluster_positions_differing_from_id_sort": int(len(mismatch)),
    }


def _diff(left: float, right: float) -> float:
    return float(left) - float(right)


def compare(report: dict, targets: pd.DataFrame, saved_dir: Path) -> dict:
    rows = []
    for arm_report in report["arms"]:
        arm = arm_report["arm"]
        saved = json.loads((saved_dir / f"{arm}.json").read_text(encoding="utf-8"))
        saved_cells = {cell["indicator"]: cell for cell in saved["cells"]}
        for indicator, key in (("auc_landmark", "landmark"), ("auc_ipcw", "ipcw")):
            got = arm_report[key]
            published = saved_cells[indicator]
            target = targets[(targets["indicator"] == indicator) & (targets["arm"] == arm)].iloc[0]
            item = {
                "arm": arm,
                "indicator": indicator,
                "ci_lo": got["ci_lo"],
                "ci_hi": got["ci_hi"],
                "n_valid": got["n_valid"],
                "versus_r1_lo": _diff(got["ci_lo"], published["ci_lo"]),
                "versus_r1_hi": _diff(got["ci_hi"], published["ci_hi"]),
                "versus_r1_point": _diff(got["auc"], published["value"]),
                "versus_target_lo": _diff(got["ci_lo"], target["ci_lo"]),
                "versus_target_hi": _diff(got["ci_hi"], target["ci_hi"]),
                "versus_target_point": _diff(got["auc"], target["value"]),
            }
            if arm == "B-9" and indicator == "auc_ipcw":
                item["versus_corrected_lo"] = _diff(got["ci_lo"], CORRECTED_B9_IPCW[0])
                item["versus_corrected_hi"] = _diff(got["ci_hi"], CORRECTED_B9_IPCW[1])
            rows.append(item)
    return {"intervals": rows}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="replay da ordem histórica por KEYS")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not _outside(args.data_dir) or not _outside(args.output_dir):
        print("dados e saída precisam ficar fora do checkout", file=sys.stderr)
        return 2
    report = {"fit": False, "historical_keys": HISTORICAL_KEYS, "arms": []}
    for arm in ("A", "B", "B-9"):
        report["arms"].append(replay_historical(args.data_dir, args.output_dir / "private" / arm / "test_scores.csv", arm))
    targets = pd.read_csv(ROOT / "baselines" / "a8_g2c2_dev_targets.csv")
    report["comparison"] = compare(report, targets, args.output_dir / "results")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
