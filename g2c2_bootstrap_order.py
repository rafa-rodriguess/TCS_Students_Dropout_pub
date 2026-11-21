#!/usr/bin/env python3
"""Diagnóstico da ordem dos clusters no intervalo do marco.

Não ajusta modelo, não grava escore e não altera `clustered_auc`.
A ordem canônica é só um contrafactual: não substitui o intervalo oficial.
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

from jla.g2c2 import clock_frame  # noqa: E402
from jla.g2c2_gates import load_enrollments  # noqa: E402
from jla.landmark import g_from_train_at_risk  # noqa: E402
from jla.audit import ipcw_weights, landmark_roles  # noqa: E402
from jla.science import KEYS, clustered_auc, student_disjoint_split  # noqa: E402


def _outside(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != ROOT and ROOT not in resolved.parents


def cluster_ids(frame: pd.DataFrame) -> np.ndarray:
    positions = frame.reset_index(drop=True).groupby("id_student", sort=False).indices
    return np.array(list(positions))


def order_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for student in cluster_ids(frame):
        digest.update(str(int(student)).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def resample_fingerprint(frame: pd.DataFrame, seed: int = 42, draws: int = 500) -> str:
    positions = frame.reset_index(drop=True).groupby("id_student", sort=False).indices
    ids = list(positions)
    rng = np.random.default_rng(seed)
    chosen = rng.choice(len(ids), size=(draws, len(ids)), replace=True)
    digest = hashlib.sha256()
    for draw in chosen:
        digest.update(np.concatenate([positions[ids[int(slot)]] for slot in draw]).tobytes())
    return digest.hexdigest()


def canonical_frame(frame: pd.DataFrame, weight: np.ndarray | None = None) -> tuple[pd.DataFrame, np.ndarray | None]:
    work = frame.copy()
    if weight is not None:
        work["_w"] = weight
    work = work.sort_values("id_student", kind="mergesort").reset_index(drop=True)
    ordered_weight = None if weight is None else work["_w"].to_numpy(dtype=float)
    if weight is not None:
        work = work.drop(columns="_w")
    return work, ordered_weight


def _auc_public(result: dict) -> dict:
    return {
        "auc": result["auc"],
        "ci_lo": result["ci_lo"],
        "ci_hi": result["ci_hi"],
        "n_valid": result["n_valid"],
        "draws": result["draws"],
    }


def replay_landmark(raw: Path, scores: Path, arm: str) -> dict:
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
    usable = test["y"] >= 0
    missing = int((usable & test["hazard_hat"].isna()).sum())
    if missing:
        raise RuntimeError(f"há {missing} casos ou controles sem escore fixo na semana 9")
    observed = test.loc[usable, ["id_student", "hazard_hat", "y"]].rename(columns={"y": "event"})
    case_rows = test.loc[test["y"] == 1, ["id_student", "hazard_hat", "t_event_week"]]
    control_rows = test.loc[test["y"] == 0, ["id_student", "hazard_hat"]]
    g = g_from_train_at_risk(clock, train_ids)
    w_case, w_control = ipcw_weights(case_rows["t_event_week"].astype(int).to_numpy(), g, 18, int(len(control_rows)))
    cases = case_rows[["id_student", "hazard_hat"]].assign(event=1, w=w_case)
    controls = control_rows.assign(event=0, w=w_control)
    ordered = pd.concat([cases, controls], ignore_index=True)
    weight = ordered["w"].to_numpy(dtype=float)
    ordered_score = ordered[["id_student", "hazard_hat", "event"]]
    canon_observed, _none = canonical_frame(observed)
    canon_ordered, canon_weight = canonical_frame(ordered_score, weight)
    appearance = {int(student): position for position, student in enumerate(cluster_ids(observed))}
    same_order = ordered_score.assign(_rank=ordered_score["id_student"].map(appearance), _w=weight)
    same_order = same_order.sort_values("_rank", kind="mergesort").reset_index(drop=True)
    official_landmark = clustered_auc(observed)
    official_ipcw = clustered_auc(ordered_score, weight)
    diagnostic_landmark = clustered_auc(canon_observed)
    diagnostic_ipcw = clustered_auc(canon_ordered, canon_weight)
    diagnostic_ipcw_observed_order = clustered_auc(
        same_order[["id_student", "hazard_hat", "event"]],
        same_order["_w"].to_numpy(dtype=float),
    )
    return {
        "arm": arm,
        "n_cases": int((test["y"] == 1).sum()),
        "n_controls": int((test["y"] == 0).sum()),
        "n_excluded": int((test["y"] < 0).sum()),
        "G18": g.get(18),
        "observed": {
            "n_rows": int(len(observed)),
            "n_clusters": int(len(cluster_ids(observed))),
            "order_fingerprint": order_fingerprint(observed),
            "resample_fingerprint": resample_fingerprint(observed),
            "official": _auc_public(official_landmark),
        },
        "ordered": {
            "n_rows": int(len(ordered_score)),
            "n_clusters": int(len(cluster_ids(ordered_score))),
            "order_fingerprint": order_fingerprint(ordered_score),
            "resample_fingerprint": resample_fingerprint(ordered_score),
            "official": _auc_public(official_ipcw),
        },
        "canonical_diagnostic_not_official": {
            "landmark": _auc_public(diagnostic_landmark),
            "ipcw": _auc_public(diagnostic_ipcw),
            "ipcw_on_observed_cluster_order": _auc_public(diagnostic_ipcw_observed_order),
            "landmark_order_fingerprint": order_fingerprint(canon_observed),
            "ipcw_order_fingerprint": order_fingerprint(canon_ordered),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="replay do bootstrap do marco com escore fixo")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not _outside(args.data_dir) or not _outside(args.output_dir):
        print("dados e saída precisam ficar fora do checkout", file=sys.stderr)
        return 2
    report = {"fit": False, "official_interval_replaced": False, "arms": []}
    for arm in ("A", "B", "B-9"):
        report["arms"].append(replay_landmark(args.data_dir, args.output_dir / "private" / arm / "test_scores.csv", arm))
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
