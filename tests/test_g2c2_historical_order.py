import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from g2c2_historical_order import cluster_ids, historical_snapshot, sequence_fingerprint  # noqa: E402
from jla.science import clustered_auc  # noqa: E402


def test_fingerprint_uses_explicit_int64_bytes() -> None:
    ids = np.array([2, 10], dtype=np.int32)
    encoded = np.asarray(ids, dtype=np.int64)
    assert sequence_fingerprint(ids) == hashlib.sha256(encoded.tobytes()).hexdigest()
    assert sequence_fingerprint(ids) != hashlib.sha256(np.asarray(ids, dtype=np.int32).tobytes()).hexdigest()


def test_historical_keys_differ_from_id_only_order() -> None:
    frame = pd.DataFrame(
        [
            {"id_student": 2, "code_module": "CCC", "code_presentation": "2014J", "y": 1, "hazard_hat": 0.2},
            {"id_student": 1, "code_module": "BBB", "code_presentation": "2013J", "y": 0, "hazard_hat": 0.8},
            {"id_student": 2, "code_module": "AAA", "code_presentation": "2014J", "y": 0, "hazard_hat": 0.4},
        ]
    )
    ordered = historical_snapshot(frame)
    assert list(ordered["code_module"]) == ["AAA", "BBB", "CCC"]
    assert list(cluster_ids(ordered)) == [2, 1]
    by_student = frame.sort_values("id_student", kind="mergesort")
    assert list(cluster_ids(by_student)) == [1, 2]
    assert sequence_fingerprint(cluster_ids(ordered)) != sequence_fingerprint(cluster_ids(by_student))


def test_keys_order_keeps_point_and_can_move_quantiles() -> None:
    rows = []
    for student in range(30):
        module = "AAA" if student % 2 == 0 else "BBB"
        rows.append(
            {
                "id_student": student,
                "code_module": module,
                "code_presentation": "2014J",
                "y": int(student % 2 == 0),
                "hazard_hat": ((student * 17) % 100) / 100,
            }
        )
    frame = pd.DataFrame(rows)
    historical = historical_snapshot(frame).rename(columns={"y": "event"})
    by_student = frame.sort_values("id_student", kind="mergesort").rename(columns={"y": "event"}).reset_index(drop=True)
    left = clustered_auc(historical[["id_student", "event", "hazard_hat"]], draws=200)
    right = clustered_auc(by_student[["id_student", "event", "hazard_hat"]], draws=200)
    assert left["auc"] == right["auc"]
    assert (left["ci_lo"], left["ci_hi"]) != (right["ci_lo"], right["ci_hi"])
