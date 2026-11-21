import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from g2c2_bootstrap_order import cluster_ids, order_fingerprint  # noqa: E402
from jla.science import clustered_auc  # noqa: E402


def _frame(order: list[int]) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    score = {student: float(rng.random()) for student in range(len(order))}
    rows = []
    for student in order:
        event = int(student % 2 == 0)
        rows.append({"id_student": student, "event": event, "hazard_hat": score[student]})
        if student % 4 == 0:
            rows.append({"id_student": student, "event": event, "hazard_hat": min(score[student] + 0.05, 0.99)})
    return pd.DataFrame(rows)


def test_same_rows_keep_point_auc_and_move_quantiles() -> None:
    students = list(range(40))
    forward = _frame(students)
    backward = _frame(list(reversed(students)))
    left = clustered_auc(forward, draws=200)
    right = clustered_auc(backward, draws=200)
    assert left["auc"] == right["auc"]
    assert left["n_valid"] == 200
    assert (left["ci_lo"], left["ci_hi"]) != (right["ci_lo"], right["ci_hi"])
    assert order_fingerprint(forward) != order_fingerprint(backward)


def test_observed_and_ordered_change_cluster_order() -> None:
    rng = np.random.default_rng(11)
    rows = []
    for student in range(36):
        event = int(student < 12)
        rows.append({"id_student": student, "event": event, "hazard_hat": float(rng.random())})
    observed = pd.DataFrame(rows).sample(frac=1, random_state=3).reset_index(drop=True)
    cases = observed.loc[observed["event"] == 1]
    controls = observed.loc[observed["event"] == 0]
    ordered = pd.concat([cases, controls], ignore_index=True)
    assert list(cluster_ids(observed)) != list(cluster_ids(ordered))
    assert order_fingerprint(observed) != order_fingerprint(ordered)
    plain = clustered_auc(observed, draws=200)
    rearranged = clustered_auc(ordered, draws=200)
    assert plain["auc"] == rearranged["auc"]
    assert (plain["ci_lo"], plain["ci_hi"]) != (rearranged["ci_lo"], rearranged["ci_hi"])
    weights = np.where(ordered["event"].to_numpy() == 1, 3.0, 0.4)
    ipcw = clustered_auc(ordered, weights, draws=200)
    assert ipcw["auc"] != plain["auc"]
