#!/usr/bin/env python3
"""Reexecução R7: ajusta A, B e B−9, grava o modelo e só então mede.

Não usa --fit do entrypoint histórico. Não apaga a saída da R1.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from jla.g2c2_execute import run_approved  # noqa: E402
from jla.g2c2_gates import measure, structural_report  # noqa: E402
from jla.landmark import score_ordered_landmark  # noqa: E402
import jla.landmark as landmark  # noqa: E402

EXPECTED_RAW = {
    "studentInfo.csv": "815fbc3e2de29f79900bc63f0345a35db62c9146afaa1d86e7107b8b3beffc60",
    "studentRegistration.csv": "bbc87a0de1fe2a9ec6decce1ca6c1a02cf17b54ad3bdcc673fc6413b41c61d47",
    "studentVle.csv": "52668253d876c5becbcb72185977152700cecab2942aca807fecc3dd54b937f0",
    "studentAssessment.csv": "b1839e17618a5de36b6d189a242d3123f7939a56c8c9ccef0c17b9199c614a6b",
    "assessments.csv": "9ce92381e4a0ac457f8e251b2eb2c179ed51e023ab30d1d671a0268bd62316ba",
    "courses.csv": "4f16eee7454b15e109b0a21a0e43be820e6846ed6f9301bb7feb5ab5ad737a75",
    "vle.csv": "d7a146497edd0e47ef536144b58796c07b554002d3753e848b8e4cd8a56f4c38",
}
EXPECTED_FINGERPRINTS = {
    ("A", "landmark"): "14406b63104b5d40f5ae4ed659656c7fa7aa5532c416e2a7973e8398bf2f3a18",
    ("A", "ipcw"): "49f43dbb276754a1a937ed2c66688d768c207a22f57ac88bd31dc487ef9311d3",
    ("B", "landmark"): "83d8d2ea470caa1963a59517a5079115740bbf8c4865ea6b878d44e12134528c",
    ("B", "ipcw"): "19f47bb7ad9ae4c23f467869edbb98c1f33e6635e6f78fc30acffd791f4eeba2",
    ("B-9", "landmark"): "1d260d1f5f7d023c839e39e5f7d03078a9b8b69b36bcdb0c35a48c7188471276",
    ("B-9", "ipcw"): "952bb9588bbb19f2b796d63f53dfda0d973a614362a7c0178738180ebb89a155",
}
EXPECTED_CLUSTERS = {"A": 6256, "B": 7165, "B-9": 7164}
EXPECTED_COUNTS = {
    "A": (576, 6275, 435),
    "B": (576, 7283, 6),
    "B-9": (576, 7281, 6),
}
TOLERANCE = 1e-9
BOOT_FIELDS = ("point", "bootstrap_mean", "ci_lo_replay", "ci_hi_replay")


def _outside(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != ROOT and ROOT not in resolved.parents


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _empty(path: Path) -> bool:
    return not path.exists() or not any(path.iterdir())


def _precheck(raw: Path) -> dict:
    hashes = {name: _sha256(raw / name) for name in EXPECTED_RAW}
    mismatches = [name for name, digest in hashes.items() if digest != EXPECTED_RAW[name]]
    report = structural_report(measure(raw))
    observed = report["observed"]
    structural_ok = report["status"] == "PASS" and observed.get("rows_removed") == 348 and observed.get("rows_removed_test") == 77
    fail_ok = observed.get("fail9") == 9 and observed.get("fail9_train") == 7 and observed.get("fail9_test") == 2
    return {
        "raw_mismatches": mismatches,
        "structural_ok": structural_ok,
        "fail_ok": fail_ok,
        "fail9": {"n": observed.get("fail9"), "train": observed.get("fail9_train"), "test": observed.get("fail9_test")},
        "removed": observed.get("rows_removed"),
        "removed_test": observed.get("rows_removed_test"),
        "hashes": hashes,
    }


def _capture_fingerprints():
    captured = {}
    real = score_ordered_landmark

    def wrapper(test, g):
        scored = real(test, g)
        return scored

    def wrapped(test, g):
        scored = wrapper(test, g)
        captured["last"] = scored
        return scored

    landmark.score_ordered_landmark = wrapped
    return captured


def _cells(output: Path) -> dict[tuple[str, str], dict]:
    found = {}
    for arm in ("A", "B", "B-9"):
        payload = json.loads((output / "results" / f"{arm}.json").read_text(encoding="utf-8"))
        for cell in payload["cells"]:
            found[(cell["arm"], cell["indicator"])] = cell
    return found


def _compare(output: Path, r1_private: Path, captured: dict) -> dict:
    targets = list(csv.DictReader((ROOT / "baselines" / "a8_g2c2_dev_targets_v2.csv").open(encoding="utf-8")))
    cells = _cells(output)
    point_failures = []
    unavailable = 0
    for row in targets:
        key = (row["arm"], row["indicator"])
        if row["status"] == "UNAVAILABLE":
            unavailable += 1
            if key in cells and cells[key].get("value") not in (None, ""):
                point_failures.append({"arm": row["arm"], "indicator": row["indicator"], "reason": "unavailable preenchido"})
            continue
        cell = cells.get(key)
        if cell is None or cell.get("value") is None:
            point_failures.append({"arm": row["arm"], "indicator": row["indicator"], "reason": "ausente"})
            continue
        difference = abs(float(cell["value"]) - float(row["value"]))
        if difference > TOLERANCE:
            point_failures.append({"arm": row["arm"], "indicator": row["indicator"], "diff": difference})
        if row["ci_lo"] and row["ci_hi"] and cell.get("ci_lo") is not None:
            for edge, field in (("ci_lo", "ci_lo"), ("ci_hi", "ci_hi")):
                edge_diff = abs(float(cell[field]) - float(row[edge]))
                if edge_diff > TOLERANCE:
                    point_failures.append({"arm": row["arm"], "indicator": row["indicator"], "edge": edge, "diff": edge_diff})
    published = list(csv.DictReader((ROOT / "baselines" / "a8_g2c2_bootstrap_targets.csv").open(encoding="utf-8")))
    fresh = json.loads((output / "results" / "bootstrap.json").read_text(encoding="utf-8"))
    boot_failures = []
    for left, right in zip(published, fresh, strict=True):
        if left["arm"] != right["arm"] or left["estimand"] != right["estimand"]:
            boot_failures.append({"reason": "ordem", "arm": right["arm"], "estimand": right["estimand"]})
            continue
        for field in BOOT_FIELDS:
            difference = abs(float(left[field]) - float(right[field]))
            if difference > TOLERANCE:
                boot_failures.append({"arm": right["arm"], "estimand": right["estimand"], "field": field, "diff": difference})
        if int(right["draws"]) != 500 or int(right["seed"]) != 42 or int(right["n_valid"]) != 500:
            boot_failures.append({"arm": right["arm"], "estimand": right["estimand"], "reason": "draws"})
    fingerprints = []
    counts = {}
    recorded = json.loads((output / "results" / "fingerprints.json").read_text(encoding="utf-8"))
    for arm, scored in zip(("A", "B", "B-9"), recorded, strict=True):
        payload = json.loads((output / "results" / f"{arm}.json").read_text(encoding="utf-8"))
        for kind in ("landmark", "ipcw"):
            ok = scored[f"{kind}_fingerprint"] == EXPECTED_FINGERPRINTS[(arm, kind)]
            fingerprints.append({"arm": arm, "kind": kind, "match": ok})
        counts[arm] = {
            "clusters": scored["n_clusters"],
            "cases": next(cell["value"] for cell in payload["cells"] if cell["indicator"] == "landmark_casos"),
            "controls": next(cell["value"] for cell in payload["cells"] if cell["indicator"] == "landmark_controles"),
            "excluded": next(cell["value"] for cell in payload["cells"] if cell["indicator"] == "landmark_excluidos"),
        }
    models = []
    for arm in ("A", "B", "B-9"):
        payload = json.loads((output / "results" / f"{arm}.json").read_text(encoding="utf-8"))
        persistence = payload.get("persistence") or {}
        calls = payload.get("predict_proba_calls")
        models.append(
            {
                "arm": arm,
                "sha256": persistence.get("sha256"),
                "sha256_after": persistence.get("sha256_after"),
                "bytes": persistence.get("bytes"),
                "predict_max_abs": persistence.get("predict_max_abs"),
                "post_pipeline_max_abs": persistence.get("post_pipeline_max_abs"),
                "predict_proba_calls": calls,
                "snapshot_gap": payload.get("snapshot_gap"),
                "n_without_week9": payload.get("n_without_week9"),
            }
        )
    model_ok = all(
        item["sha256"] and item["sha256"] == item["sha256_after"] and item["predict_max_abs"] <= TOLERANCE and item["post_pipeline_max_abs"] <= TOLERANCE and item["predict_proba_calls"] >= 3 and item["snapshot_gap"] is not None and item["snapshot_gap"] <= 1e-10
        for item in models
    )
    n_valid_ok = all(item["n_valid"] == 500 for item in recorded)
    score_gaps = []
    for arm in ("A", "B", "B-9"):
        import pandas as pd

        fresh_scores = pd.read_csv(output / "private" / arm / "test_scores.csv")
        old_scores = pd.read_csv(r1_private / arm / "test_scores.csv")
        keys = ["id_student", "code_module", "code_presentation", "week"]
        merged = fresh_scores.merge(old_scores, on=keys, suffixes=("_r7", "_r1"))
        gap = None if merged.empty else float((merged["hazard_hat_r7"] - merged["hazard_hat_r1"]).abs().max())
        score_gaps.append(
            {
                "arm": arm,
                "r7_rows": int(len(fresh_scores)),
                "r1_rows": int(len(old_scores)),
                "matched_rows": int(len(merged)),
                "max_abs": gap,
            }
        )
    count_ok = all(counts.get(arm, {}).get("clusters") == EXPECTED_CLUSTERS[arm] and (counts[arm]["cases"], counts[arm]["controls"], counts[arm]["excluded"]) == EXPECTED_COUNTS[arm] for arm in EXPECTED_COUNTS)
    fingerprint_ok = len(fingerprints) == 6 and all(item.get("match") for item in fingerprints)
    score_ok = all(item["matched_rows"] == item["r7_rows"] == item["r1_rows"] and item["max_abs"] is not None and item["max_abs"] <= TOLERANCE for item in score_gaps)
    return {
        "pass": not point_failures and not boot_failures and fingerprint_ok and count_ok and score_ok and unavailable == 8 and model_ok and n_valid_ok,
        "point_failures": point_failures[:20],
        "point_failure_n": len(point_failures),
        "bootstrap_failures": boot_failures[:20],
        "bootstrap_failure_n": len(boot_failures),
        "fingerprints": fingerprints,
        "counts": counts,
        "score_gaps": score_gaps,
        "models": models,
        "unavailable": unavailable,
        "captured": captured.get("last") is not None,
    }


def _remember(payload: dict, scored: dict) -> dict:
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R7 ajusta, grava e recarrega os três braços")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--r1-private", type=Path, required=True)
    args = parser.parse_args(argv)
    if not _outside(args.data_dir) or not _outside(args.output_dir) or not _outside(args.r1_private):
        print("dados, saída e escores da R1 precisam ficar fora do checkout", file=sys.stderr)
        return 2
    if not _empty(args.output_dir):
        print("saída R7 já contém arquivos; não será limpa", file=sys.stderr)
        return 2
    precheck = _precheck(args.data_dir)
    if precheck["raw_mismatches"] or not precheck["structural_ok"] or not precheck["fail_ok"]:
        print(json.dumps({"decision": "STOP", "stage": "precheck", "precheck": precheck}))
        return 1
    captured = []
    real = score_ordered_landmark

    def wrapped(test, g):
        scored = real(test, g)
        captured.append(
            {
                "landmark_fingerprint": scored["landmark_fingerprint"],
                "ipcw_fingerprint": scored["ipcw_fingerprint"],
                "n_clusters": scored["n_clusters"],
                "n_valid": scored["unweighted"]["n_valid"],
            }
        )
        return scored

    landmark.score_ordered_landmark = wrapped
    try:
        run_approved(args.data_dir, args.output_dir, persist=True)
    finally:
        landmark.score_ordered_landmark = real
    (args.output_dir / "results" / "fingerprints.json").write_text(json.dumps(captured), encoding="utf-8")
    versions = {
        "python": platform.python_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
    }
    for name in ("numpy", "pandas", "sklearn", "joblib"):
        module = __import__(name)
        versions[name] = getattr(module, "__version__", None)
    manifest = {"precheck": {key: precheck[key] for key in ("fail9", "removed", "removed_test")}, "versions": versions, "raw": precheck["hashes"]}
    (args.output_dir / "results" / "r7_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    gate = _compare(args.output_dir, args.r1_private, {"last": bool(captured)})
    print(json.dumps({"decision": "PASS_E2E_R7" if gate["pass"] else "STOP", "gate": gate, "versions": versions}))
    return 0 if gate["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
