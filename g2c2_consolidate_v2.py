#!/usr/bin/env python3
"""Consolida a v2 com a rotina normal e os escores fixos da R1.

Não ajusta modelo. Só grava os CSV v2 se o gate fechar.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from jla.audit import landmark_roles  # noqa: E402
from jla.g2c2 import clock_frame  # noqa: E402
from jla.g2c2_gates import load_enrollments, measure  # noqa: E402
from jla.landmark import g_from_train_at_risk, score_ordered_landmark  # noqa: E402
from jla.science import KEYS, student_disjoint_split  # noqa: E402

EXPECTED_CLUSTERS = {"A": 6256, "B": 7165, "B-9": 7164}
EXPECTED_FINGERPRINTS = {
    ("A", "landmark"): "14406b63104b5d40f5ae4ed659656c7fa7aa5532c416e2a7973e8398bf2f3a18",
    ("A", "ipcw"): "49f43dbb276754a1a937ed2c66688d768c207a22f57ac88bd31dc487ef9311d3",
    ("B", "landmark"): "83d8d2ea470caa1963a59517a5079115740bbf8c4865ea6b878d44e12134528c",
    ("B", "ipcw"): "19f47bb7ad9ae4c23f467869edbb98c1f33e6635e6f78fc30acffd791f4eeba2",
    ("B-9", "landmark"): "1d260d1f5f7d023c839e39e5f7d03078a9b8b69b36bcdb0c35a48c7188471276",
    ("B-9", "ipcw"): "952bb9588bbb19f2b796d63f53dfda0d973a614362a7c0178738180ebb89a155",
}
B9_POINTS = {
    "G18": "0.9995014572725653",
    "auc_ipcw": "0.6609101511265063",
    "ess_casos": "575.9999905762434",
    "ess_controles": "7280.9999999999945",
}
B9_IPCW_CI = ("0.6374116319344114", "0.6840490660573272")
TOLERANCE = 1e-9
POINT_FIELDS = ("G18", "auc_ipcw", "ess_casos", "ess_controles")


def _outside(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != ROOT and ROOT not in resolved.parents


def _labeled_test(raw: Path, scores: Path, arm: str) -> tuple[pd.DataFrame, dict]:
    enrollments, _presentations = load_enrollments(raw)
    clock_a = clock_frame(enrollments, "A")
    is_test, _strata = student_disjoint_split(clock_a)
    train_ids = set(clock_a.loc[~is_test.to_numpy(), "id_student"])
    clock = clock_frame(enrollments, arm)
    roles = landmark_roles(clock)
    week9 = pd.read_csv(scores, usecols=KEYS + ["week", "hazard_hat"])
    week9 = week9.loc[week9["week"] == 9, KEYS + ["hazard_hat"]]
    labeled = roles.merge(week9, on=KEYS, how="left")
    labeled = labeled.loc[labeled["at_risk"]].copy()
    test = labeled.loc[~labeled["id_student"].isin(train_ids)].copy()
    return test, g_from_train_at_risk(clock, train_ids)


def _float_or_blank(text: str) -> float | None:
    if text == "":
        return None
    return float(text)


def _write_versions(replay: dict[tuple[str, str], dict]) -> None:
    original = list(csv.DictReader((ROOT / "baselines" / "a8_g2c2_dev_targets.csv").open(encoding="utf-8")))
    published = list(csv.DictReader((ROOT / "baselines" / "a8_g2c2_pub_metrics.csv").open(encoding="utf-8")))
    fields = list(original[0].keys())
    dev_rows = []
    for row in original:
        copied = dict(row)
        if copied["arm"] == "B-9" and copied["indicator"] in B9_POINTS:
            copied["value"] = B9_POINTS[copied["indicator"]]
        if copied["arm"] == "B-9" and copied["indicator"] == "auc_ipcw":
            copied["ci_lo"], copied["ci_hi"] = B9_IPCW_CI
        dev_rows.append(copied)
    pub_rows = []
    for row in published:
        copied = dict(row)
        key = (copied["arm"], copied["indicator"])
        if copied["arm"] == "B-9" and copied["indicator"] in B9_POINTS:
            copied["value"] = B9_POINTS[copied["indicator"]]
        if key in replay:
            copied["ci_lo"] = replay[key]["ci_lo"]
            copied["ci_hi"] = replay[key]["ci_hi"]
        pub_rows.append(copied)
    for name, rows in (
        ("a8_g2c2_dev_targets_v2.csv", dev_rows),
        ("a8_g2c2_pub_metrics_v2.csv", pub_rows),
    ):
        with (ROOT / "baselines" / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def _gates(replay_rows: list[dict], observed: dict) -> dict:
    original = pd.read_csv(ROOT / "baselines" / "a8_g2c2_dev_targets.csv")
    dev = pd.read_csv(ROOT / "baselines" / "a8_g2c2_dev_targets_v2.csv")
    pub = pd.read_csv(ROOT / "baselines" / "a8_g2c2_pub_metrics_v2.csv")
    changed = []
    for left, right in zip(original.itertuples(index=False), dev.itertuples(index=False), strict=True):
        value_changed = not (pd.isna(left.value) and pd.isna(right.value)) and left.value != right.value
        ci_changed = (str(left.ci_lo) != str(right.ci_lo) and not (pd.isna(left.ci_lo) and pd.isna(right.ci_lo))) or (
            str(left.ci_hi) != str(right.ci_hi) and not (pd.isna(left.ci_hi) and pd.isna(right.ci_hi))
        )
        if value_changed or ci_changed:
            changed.append({"indicator": right.indicator, "arm": right.arm, "value": value_changed, "ci": ci_changed})
    point_changes = [(item["indicator"], item["arm"]) for item in changed if item["value"]]
    unavailable = int((dev["status"] == "UNAVAILABLE").sum())
    empty_unavailable = bool(dev.loc[dev["status"] == "UNAVAILABLE", "value"].isna().all())
    point_mismatches = []
    for left, right in zip(dev.itertuples(index=False), pub.itertuples(index=False), strict=True):
        if left.status != "computed":
            continue
        if abs(float(left.value) - float(right.value)) > TOLERANCE:
            point_mismatches.append((left.indicator, left.arm, float(right.value) - float(left.value)))
    interval_mismatches = [row for row in replay_rows if not row["pass"]]
    boot_pub = pd.read_csv(ROOT / "baselines" / "a8_g2c2_pub_bootstrap.csv")
    boot_target = pd.read_csv(ROOT / "baselines" / "a8_g2c2_bootstrap_targets.csv")
    boot_fail = 0
    for left, right in zip(boot_pub.itertuples(index=False), boot_target.itertuples(index=False), strict=True):
        for field in ("point", "bootstrap_mean", "ci_lo_replay", "ci_hi_replay"):
            if abs(float(getattr(left, field)) - float(getattr(right, field))) > TOLERANCE:
                boot_fail += 1
        if int(left.draws) != 500 or int(left.seed) != 42 or int(left.n_valid) != 500:
            boot_fail += 1
    ok = (
        point_changes == [("auc_ipcw", "B-9"), ("G18", "B-9"), ("ess_casos", "B-9"), ("ess_controles", "B-9")]
        and len(dev) == 99
        and len(pub) == 99
        and unavailable == 8
        and empty_unavailable
        and not point_mismatches
        and not interval_mismatches
        and boot_fail == 0
        and observed["fail9"] == 9
        and observed["fail9_train"] == 7
        and observed["fail9_test"] == 2
    )
    return {
        "pass": ok,
        "point_changes": point_changes,
        "ci_changes": [item for item in changed if item["ci"]],
        "unavailable": unavailable,
        "point_mismatches": point_mismatches,
        "interval_failures": interval_mismatches,
        "bootstrap_failures": boot_fail,
        "fail9": {"n": observed["fail9"], "train": observed["fail9_train"], "test": observed["fail9_test"]},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="gate v2 com a rotina normal")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not _outside(args.data_dir) or not _outside(args.output_dir):
        print("dados e saída precisam ficar fora do checkout", file=sys.stderr)
        return 2
    rows = []
    replay_ci = {}
    for arm in ("A", "B", "B-9"):
        test, g = _labeled_test(args.data_dir, args.output_dir / "private" / arm / "test_scores.csv", arm)
        scored = score_ordered_landmark(test, g)
        for kind, indicator in (("landmark", "auc_landmark"), ("ipcw", "auc_ipcw")):
            fingerprint = scored[f"{kind}_fingerprint"]
            draws = scored["unweighted" if kind == "landmark" else "ipcw"]
            if arm == "B-9" and kind == "ipcw":
                expected = (float(B9_IPCW_CI[0]), float(B9_IPCW_CI[1]))
            else:
                target = pd.read_csv(ROOT / "baselines" / "a8_g2c2_dev_targets.csv")
                match = target[(target["indicator"] == indicator) & (target["arm"] == arm)].iloc[0]
                expected = (float(match["ci_lo"]), float(match["ci_hi"]))
            replay_ci[(arm, indicator)] = {"ci_lo": repr(draws["ci_lo"]), "ci_hi": repr(draws["ci_hi"])}
            rows.append(
                {
                    "arm": arm,
                    "indicator": indicator,
                    "fingerprint_match": fingerprint == EXPECTED_FINGERPRINTS[(arm, kind)],
                    "clusters": scored["n_clusters"],
                    "n_valid": draws["n_valid"],
                    "ci_lo_diff": float(draws["ci_lo"]) - expected[0],
                    "ci_hi_diff": float(draws["ci_hi"]) - expected[1],
                    "pass": fingerprint == EXPECTED_FINGERPRINTS[(arm, kind)]
                    and scored["n_clusters"] == EXPECTED_CLUSTERS[arm]
                    and draws["n_valid"] == 500
                    and abs(float(draws["ci_lo"]) - expected[0]) <= TOLERANCE
                    and abs(float(draws["ci_hi"]) - expected[1]) <= TOLERANCE,
                }
            )
        if arm == "B-9":
            rows.append(
                {
                    "arm": arm,
                    "indicator": "b9_points",
                    "G18_diff": float(g.get(18)) - float(B9_POINTS["G18"]),
                    "ess_cases_diff": float(scored["ess_cases"]) - float(B9_POINTS["ess_casos"]),
                    "ess_controls_diff": float(scored["ess_controls"]) - float(B9_POINTS["ess_controles"]),
                    "auc_diff": float(scored["ipcw"]["auc"]) - float(B9_POINTS["auc_ipcw"]),
                    "pass": abs(float(g.get(18)) - float(B9_POINTS["G18"])) <= TOLERANCE
                    and abs(float(scored["ess_cases"]) - float(B9_POINTS["ess_casos"])) <= TOLERANCE
                    and abs(float(scored["ess_controls"]) - float(B9_POINTS["ess_controles"])) <= TOLERANCE
                    and abs(float(scored["ipcw"]["auc"]) - float(B9_POINTS["auc_ipcw"])) <= TOLERANCE,
                }
            )
    if any(not row["pass"] for row in rows):
        print(json.dumps({"technical_diagnostic": "STOP", "rows": rows}))
        return 1
    _write_versions(replay_ci)
    gate = _gates(rows, measure(args.data_dir))
    print(json.dumps({"technical_diagnostic": "PASS" if gate["pass"] else "STOP", "fit": False, "rows": rows, "gate": gate}))
    return 0 if gate["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
