from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from .audit import choose_examples, classify_hashes, mechanism_respects_clock, policy_contrasts, public_example, record
from .paths import PACKAGE_ROOT
from .protocol import load_protocol
from .science import DELTA, EPS, FEATURES, KEYS, active_from_recency, response_plan, rewritten_features, sha256_file, survival_at_18

def t4_evaluate(response, forced_recency, original_recency, forced_clicks, action) -> dict:
    """Predicado T4. Não usa o clique da própria semana de resposta."""
    forced_moves = bool(response.any() and not np.allclose(forced_recency[response], original_recency[response]))
    identity = (not bool(response.any())) or bool(np.allclose(forced_clicks[response], action[response]))
    action_zero = response & np.isfinite(action) & (action == 0.0)
    zero_ok = (not bool(action_zero.any())) or bool(np.allclose(forced_clicks[action_zero], 0.0))
    return {
        "ok": bool(forced_moves and identity and zero_ok),
        "forced_moves": forced_moves,
        "identity": identity,
        "zero_action_stays_zero": zero_ok,
        "response_any": bool(response.any()),
    }


def t4_clock_predicate(frame: pd.DataFrame) -> dict:
    """T4 com alpha zero: recência forçada e clique igual ao da semana anterior."""
    plan = response_plan(frame)
    forced = rewritten_features(frame, plan, 0.0, 0.0, enabled=True)
    response = plan["first_response"].to_numpy(dtype=bool) | plan["second_response"].to_numpy(dtype=bool)
    return t4_evaluate(
        response,
        forced["recency_lag"].to_numpy(dtype=float),
        frame["recency_lag"].to_numpy(dtype=float),
        forced["total_clicks_lag"].to_numpy(dtype=float),
        plan["clicks_action"].to_numpy(dtype=float),
    )


PRIVATE_FILES = ("pp_test_scores.csv", "scenario_rows.csv", "r18.csv", "hazard.joblib")
FROZEN_R18 = {"n_r18_enrollments": 6369, "n_r18_students": 5894}
SCORE_TOLERANCE = 1e-8
P3_FIELDS = (
    "n_r18_enrollments",
    "n_r18_students",
    "delta_s_shock",
    "delta_s_shock_ci",
    "delta_gap_shock",
    "delta_gap_shock_ci",
    "delta_s_mechanism",
    "delta_s_mechanism_ci",
    "delta_gap_mechanism",
    "delta_gap_mechanism_ci",
)
SURVIVAL_COLUMNS = ("S_base", "S_shock", "S_mech")


def population_report(both: pd.DataFrame, *, require_frozen: bool) -> dict:
    duplicate = bool(both.duplicated(KEYS).any())
    n_enrollments = int(len(both))
    n_students = int(both["id_student"].nunique()) if n_enrollments else 0
    shared = {"S_base", "S_shock", "S_mech"} <= set(both.columns) and not both[KEYS].isna().any().any()
    frozen_ok = (not require_frozen) or (n_enrollments == FROZEN_R18["n_r18_enrollments"] and n_students == FROZEN_R18["n_r18_students"])
    return {
        "duplicate_keys": duplicate,
        "shared_population": shared,
        "n_enrollments": n_enrollments,
        "n_students": n_students,
        "frozen_ok": frozen_ok,
        "ok": (not duplicate) and shared and frozen_ok and n_enrollments > 0,
    }


def _ready(ctx) -> bool:
    private = ctx.results / "private"
    return all((private / name).exists() for name in PRIVATE_FILES[:3]) and (ctx.models / "hazard.joblib").exists() and (private / "scenario_hashes.json").exists()


def _drop_public(ctx) -> None:
    path = ctx.results / "public_examples.json"
    if path.exists():
        path.unlink()


def _private_hashes_match(ctx) -> bool:
    private = ctx.results / "private"
    expected = json.loads((private / "scenario_hashes.json").read_text(encoding="utf-8"))
    actual = {
        "pp_test_scores.csv": sha256_file(private / "pp_test_scores.csv"),
        "scenario_rows.csv": sha256_file(private / "scenario_rows.csv"),
        "r18.csv": sha256_file(private / "r18.csv"),
        "hazard.joblib": sha256_file(ctx.models / "hazard.joblib"),
    }
    return actual == {name: expected.get(name) for name in PRIVATE_FILES}


def _close(found: float | list, expected: float | list) -> bool:
    if isinstance(expected, list):
        return isinstance(found, list) and len(found) == len(expected) and all(abs(float(a) - float(b)) <= 1e-12 for a, b in zip(found, expected))
    return abs(float(found) - float(expected)) <= 1e-12


def _survival_match(rebuilt: pd.DataFrame, saved: pd.DataFrame) -> bool:
    if not set(SURVIVAL_COLUMNS) <= set(rebuilt.columns) or not set(SURVIVAL_COLUMNS) <= set(saved.columns):
        return False
    try:
        aligned = rebuilt[KEYS + list(SURVIVAL_COLUMNS)].merge(saved[KEYS + list(SURVIVAL_COLUMNS)], on=KEYS, how="outer", validate="1:1", suffixes=("_hat", "_file"), indicator=True)
    except pd.errors.MergeError:
        return False
    if not bool(aligned["_merge"].eq("both").all()):
        return False
    return all(bool(np.allclose(aligned[f"{column}_hat"], aligned[f"{column}_file"], atol=SCORE_TOLERANCE, equal_nan=False)) for column in SURVIVAL_COLUMNS)


def _p3_matches(ctx, rebuilt: pd.DataFrame, shock_gap: float, base_gap: float, mech_gap: float) -> tuple[bool, str]:
    path = ctx.results / "p3_metrics.json"
    hazards_ok = shock_gap <= SCORE_TOLERANCE and base_gap <= SCORE_TOLERANCE and mech_gap <= SCORE_TOLERANCE
    if not path.exists():
        return False, "p3_metrics.json ausente"
    saved = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in P3_FIELDS if key not in saved]
    if missing or "gender" not in rebuilt.columns:
        return False, "campos ausentes: " + ",".join(missing or ["gender"])
    work = rebuilt.copy()
    work["female"] = work["gender"].astype(str).eq("F")
    work["dS_shock"] = work["S_shock"] - work["S_base"]
    work["dS_mech"] = work["S_mech"] - work["S_base"]
    found = policy_contrasts(work)
    ok = hazards_ok and not missing and all(_close(found[key], saved[key]) for key in P3_FIELDS)
    return ok, f"delta={DELTA}; shock_gap={shock_gap}; mech_gap={mech_gap}; campos={len(P3_FIELDS)}"


def _audit(ctx, scope: str) -> tuple[list[dict], list[dict]]:
    private = ctx.results / "private"
    frame = pd.read_csv(private / "pp_test_scores.csv")
    scenario = pd.read_csv(private / "scenario_rows.csv")
    both = pd.read_csv(private / "r18.csv")
    results: list[dict] = []
    if frame.duplicated(KEYS + ["week"]).any() or both.duplicated(KEYS).any():
        record(results, "T8", "chaves de matricula unicas", False, "chave duplicada")
        return results, []
    merged = frame.merge(scenario[KEYS + ["week", "h_base", "h_shock", "h_mech"]], on=KEYS + ["week"], how="left", validate="1:1")
    if merged[["h_base", "h_shock", "h_mech"]].isna().any().any():
        raise RuntimeError("cenário sem hazard alinhado à matrícula")
    model = joblib.load(ctx.models / "hazard.joblib")
    predicted = model.predict_proba(merged[FEATURES])[:, 1]
    saved = merged["hazard_hat"].to_numpy(dtype=float)
    score_gap = float(np.max(np.abs(predicted - saved)))
    record(results, "T_model", "h_base reconstruido pelo modelo congelado", score_gap <= SCORE_TOLERANCE, f"gap={score_gap}")
    active = active_from_recency(merged)
    shock_hat = predicted.copy()
    shock_hat[active] = np.clip(predicted[active] * (1.0 - DELTA), EPS, 1.0 - EPS)
    clock = mechanism_respects_clock(merged, predicted, model)
    mech_hat = clock["mech"]
    shock_gap = float(np.max(np.abs(shock_hat - merged["h_shock"].to_numpy(dtype=float))))
    mech_gap = float(np.max(np.abs(mech_hat - merged["h_mech"].to_numpy(dtype=float))))
    base_gap = float(np.max(np.abs(predicted - merged["h_base"].to_numpy(dtype=float))))
    protocol_rows = classify_hashes(ctx.raw, load_protocol().get("hashes", {}))
    pending = [row["file"] for row in protocol_rows if row["status"] == "PENDING"]
    known_fail = [row["file"] for row in protocol_rows if row["status"] == "FAIL"]
    known_pass = [row["file"] for row in protocol_rows if row["status"] == "PASS"]
    known_absent = [row["file"] for row in protocol_rows if row["status"] == "ABSENT"]
    private_ok = _private_hashes_match(ctx)
    t0_ok = private_ok and not known_fail and (scope == "MOCK" or not known_absent)
    evidence = {
        "known_pass": known_pass,
        "known_absent": known_absent,
        "pending": pending,
        "pending_status": "PENDING",
        "private_match": private_ok,
        "publication_status": "BLOCKED",
    }
    record(results, "T0", "hashes conhecidos, pendentes e privados em separado", t0_ok, json.dumps(evidence))
    expected_star = merged.loc[merged["recency"] >= 1].groupby(KEYS, as_index=False)["week"].min().rename(columns={"week": "expected"})
    observed_star = merged.groupby(KEYS, as_index=False)["s_star"].first()
    stars = observed_star.merge(expected_star, on=KEYS, how="left")
    star_ok = bool(((stars["expected"].isna() & stars["s_star"].isna()) | np.isclose(stars["expected"].fillna(-1), stars["s_star"].fillna(-1))).all())
    record(results, "T1", "um s* por matricula, o primeiro recency>=1", star_ok, "frame privado")
    quiet = ~merged.groupby(KEYS, sort=False)["recency"].transform(lambda values: (values >= 1).any()).to_numpy(dtype=bool)
    record(results, "T1b", "sem gatilho o choque nao muda", (not quiet.any()) or bool(np.allclose(shock_hat[quiet], predicted[quiet])), "recencia 0")
    changed = ~np.isclose(shock_hat, predicted)
    record(results, "T2", "choque so na janela ativa", bool(np.array_equal(changed, active)), "s*+1 e s*+2")
    formula = np.clip(predicted * (1.0 - DELTA), EPS, 1.0 - EPS)
    record(results, "T3", "choque igual a h*(1-delta) na janela", (not active.any()) or bool(np.allclose(shock_hat[active], formula[active])), f"delta={DELTA}")
    rebuilt_base = survival_at_18(merged, predicted)
    rebuilt_shock = survival_at_18(merged, shock_hat)
    rebuilt_mech = survival_at_18(merged, mech_hat)
    rebuilt = rebuilt_base.merge(rebuilt_shock[KEYS + ["S"]], on=KEYS, suffixes=("_base", "_shock"))
    rebuilt = rebuilt.merge(rebuilt_mech[KEYS + ["S"]].rename(columns={"S": "S_mech"}), on=KEYS)
    same_keys = set(map(tuple, rebuilt[KEYS].to_numpy())) == set(map(tuple, both[KEYS].to_numpy()))
    values_match = _survival_match(rebuilt, both)
    record(results, "T3b", "choque nao reduz S no R18 reconstruido", bool((rebuilt["S_shock"] + 1e-12 >= rebuilt["S_base"]).all()) and same_keys, f"n={len(rebuilt)}")
    t4 = t4_clock_predicate(merged)
    record(results, "T4", "alpha zero força recência e copia o clique da semana anterior", t4["ok"], "features privadas")
    record(results, "T5", "acao nao reescreve o proprio hazard", bool(clock["action_unchanged"]), "s*+1")
    record(results, "T6", "mecanismo so na resposta e bate com o arquivo", bool(clock["outside_unchanged"] and mech_gap <= SCORE_TOLERANCE), f"gap={mech_gap}")
    bounded = bool(np.isfinite(predicted).all() and predicted.min() >= 0 and predicted.max() <= 1 and shock_hat.min() >= 0 and shock_hat.max() <= 1 and mech_hat.min() >= 0 and mech_hat.max() <= 1)
    record(results, "T7", "hazards reconstruidos em [0, 1]", bounded, "modelo congelado")
    curve_path = ctx.curves / "survival_week.csv"
    if not curve_path.exists():
        record(results, "T7b", "media semanal nao foi exportada como curva", True, "arquivo ausente")
    else:
        curve = pd.read_csv(curve_path)
        labeled = "prohibition" in curve.columns and curve["prohibition"].astype(str).str.contains("PROIBIDO").all() and "n_enrollments" in curve.columns
        counts = merged.groupby("week").size()
        same_n = labeled and all(int(row.n_enrollments) == int(counts.loc[row.week]) for row in curve.itertuples())
        record(results, "T7b", "serie observada tem n e proibicao de curva fixa", bool(same_n), "nao e coorte fixa")
    population = population_report(both, require_frozen=scope == "REAL")
    record(results, "T8", "S_base, S_shock e S_mech 1:1 por KEYS", bool(population["ok"] and values_match), f"n_enrollments={population['n_enrollments']}; n_students={population['n_students']}; scope={scope}")
    metrics_ok, metric_note = _p3_matches(ctx, rebuilt, shock_gap, base_gap, mech_gap)
    if scope == "REAL":
        baseline = json.loads((PACKAGE_ROOT / "baselines" / "aggregates.json").read_text(encoding="utf-8"))
        metrics_ok = metrics_ok and _close(population["n_enrollments"], baseline["n_r18_enrollments"]) and _close(population["n_students"], baseline["n_r18_students"])
    record(results, "T9", "P3 recomputado do R18 reconstruido", metrics_ok, metric_note)
    ranked = both.rename(columns={"S_mech": "S_scenario"})
    selected = choose_examples(merged, ranked)
    examples = [public_example(merged, predicted, shock_hat, mech_hat, row) for _, row in selected.iterrows()]
    public_text = json.dumps(examples, allow_nan=False)
    record(results, "T_public", "exemplos A-D sem identificador", "id_student" not in public_text and selected["label"].tolist() == ["A", "B", "C", "D"], scope)
    return results, examples


def run(ctx) -> dict:
    ctx.results.mkdir(parents=True, exist_ok=True)
    if not _ready(ctx):
        _drop_public(ctx)
        (ctx.results / "operator_tests.json").write_text(json.dumps([{"test": "T0", "result": "NOT_RUN_SCIENCE", "evidence": "entradas privadas ausentes"}]), encoding="utf-8")
        return {"status": "NOT_RUN_SCIENCE", "publication_status": "BLOCKED", "message": "auditoria real não executada; entradas privadas ausentes"}
    scope = "MOCK" if (ctx.results / "private" / "MOCK").exists() else "REAL"
    try:
        results, examples = _audit(ctx, scope)
    except RuntimeError as exc:
        _drop_public(ctx)
        return {"status": "FAIL", "publication_status": "BLOCKED", "message": str(exc)}
    (ctx.results / "operator_tests.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    if any(item["result"] == "FAIL" for item in results):
        _drop_public(ctx)
        return {"status": "FAIL", "scope": scope, "publication_status": "BLOCKED", "message": "auditoria do operador falhou", "tests": results}
    payload = {"scope": "PASS_MOCK" if scope == "MOCK" else "REAL", "publication_status": "BLOCKED", "examples": examples}
    (ctx.results / "public_examples.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    if scope == "MOCK":
        return {"status": "PASS_MOCK", "scope": "MOCK", "publication_status": "BLOCKED", "message": "interface exercitada com fixture; não é auditoria do OULAD"}
    return {"status": "PASS", "scope": "REAL", "publication_status": "BLOCKED", "message": "auditoria sobre os artefatos privados; publicação continua bloqueada"}
