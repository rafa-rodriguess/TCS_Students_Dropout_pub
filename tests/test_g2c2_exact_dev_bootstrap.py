import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from g2c2_exact_dev_bootstrap import cluster_ids, exact_snapshot, sequence_fingerprint  # noqa: E402


def test_fingerprint_is_int64_groupby_bytes() -> None:
    ids = np.array([4, 4, 1], dtype=np.int64)
    assert sequence_fingerprint(ids) == hashlib.sha256(np.asarray(ids, dtype=np.int64).tobytes()).hexdigest()


def test_case_control_concat_is_not_a_full_id_sort() -> None:
    frame = pd.DataFrame(
        [
            {"id_student": 1, "code_module": "AAA", "code_presentation": "2013J", "y": 0, "hazard_hat": 0.2},
            {"id_student": 2, "code_module": "AAA", "code_presentation": "2014J", "y": 1, "hazard_hat": 0.8},
        ]
    )
    snap = exact_snapshot(frame)
    cases = snap.loc[snap["y"] == 1]
    controls = snap.loc[snap["y"] == 0]
    ordered = pd.concat([cases, controls], ignore_index=True)
    mixed = ordered.sort_values("id_student", kind="mergesort")
    assert list(cluster_ids(ordered)) == [2, 1]
    assert list(cluster_ids(mixed)) == [1, 2]
    assert sequence_fingerprint(cluster_ids(snap.loc[snap["y"] >= 0])) == sequence_fingerprint(np.array([1, 2], dtype=np.int64))
