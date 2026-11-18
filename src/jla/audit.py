# Auditorias A3–A5 em funções puras. Não leem o diretório pessoal nem o OULAD.

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .science import (
    ALPHA_FIRST,
    ALPHA_SECOND,
    CATEGORICAL,
    DELTA,
    EPS,
    FEATURES,
    KEYS,
    NUMERIC,
    active_from_recency,
    attach_s_star,
    censoring_g,
    gap,
    response_plan,
    rewritten_features,
    toy_active_ignores_event,
    toy_response_window,
)

def unique_columns(columns: list[str]) -> list[str]:
    seen = []
    for column in columns:
        if column not in seen:
            seen.append(column)
    return seen


SCORE_COLUMNS = unique_columns(
    KEYS
    + [
        "week",
        "event",
        "recency",
        "gender",
        "total_clicks",
        "streak",
        "submitted_this_week",
        "s_star",
        "hazard_hat",
        *NUMERIC,
        *CATEGORICAL,
    ]
)


def assert_score_contract(frame: pd.DataFrame) -> None:
    missing = [column for column in SCORE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"contrato de escore incompleto: {missing}")


def tie_key(frame: pd.DataFrame) -> pd.Series:
    text = frame["id_student"].astype(str) + "|" + frame["code_module"].astype(str) + "|" + frame["code_presentation"].astype(str)
    return text.map(lambda value: hashlib.sha256(value.encode()).hexdigest())


def record(results: list[dict], name: str, criterion: str, passed: bool, evidence: str) -> None:
    results.append({"test": name, "criterion": criterion, "result": "PASS" if passed else "FAIL", "evidence": evidence})


def landmark_roles(enr: pd.DataFrame, landmark: int = 8, horizon: int = 18) -> pd.DataFrame:
    """Mesma regra do P2: caso em (L, T], controle observado além de T, resto excluído."""
    out = enr.copy()
    event = out["event_withdrawn"].astype(int).eq(1)
    t_event = pd.to_numeric(out["t_event_week"], errors="coerce")
    t_final = out["t_final_week"].astype(int)
    at_risk = (t_final >= landmark) & (~event | t_event.gt(landmark))
    is_case = event & t_event.gt(landmark) & t_event.le(horizon)
    is_control = t_final.gt(horizon) & ~(event & t_event.fillna(np.inf).le(horizon))
    out["at_risk"] = at_risk.to_numpy()
    out["y"] = np.where(is_case, 1, np.where(is_control, 0, -1))
    out.loc[~at_risk, "y"] = -1
    return out


def ipcw_weights(case_weeks: np.ndarray, g: dict[int, float], horizon: int, n_controls: int) -> tuple[np.ndarray, np.ndarray]:
    w_case = np.array([1.0 / g[int(week)] for week in case_weeks], dtype=float)
    w_control = np.full(n_controls, 1.0 / g[horizon], dtype=float)
    return w_case, w_control


def toy_forced_response() -> dict:
    frame = pd.DataFrame(
        {
            "id_student": [7, 7, 7, 7],
            "code_module": ["AAA"] * 4,
            "code_presentation": ["2013J"] * 4,
            "week": [0, 1, 2, 3],
            "recency": [1, 0, 0, 0],
            "total_clicks": [0.0, 0.0, 0.0, 0.0],
            "streak": [0, 0, 0, 0],
            "submitted_this_week": [0, 0, 0, 0],
            "event": [0, 0, 0, 0],
            "lag_available": [0, 1, 1, 1],
            "total_clicks_lag": [0.0, 0.0, 0.0, 0.0],
            "recency_lag": [0.0, 4.0, 4.0, 4.0],
            "streak_lag": [0.0, 0.0, 0.0, 0.0],
            "submitted_lag": [0.0, 0.0, 0.0, 0.0],
            "studied_credits": [60] * 4,
            "num_of_prev_attempts": [0] * 4,
            "highest_education": ["A Level or Equivalent"] * 4,
            "age_band": ["0-35"] * 4,
            "gender": ["M"] * 4,
            "s_star": [0, 0, 0, 0],
        }
    )

    class _Constant:
        def predict_proba(self, rows):
            ones = np.full(len(rows), 0.1)
            return np.column_stack([1.0 - ones, ones])

    base = np.full(len(frame), 0.2)
    clock = mechanism_respects_clock(frame, base, _Constant())
    shock = base.copy()
    shock[frame["week"].to_numpy() == 1] = 0.2 * (1.0 - DELTA)
    public = public_rows(frame, base, shock, clock["mech"], 0)
    return {
        "action_unchanged": clock["action_unchanged"],
        "response_changed": bool(clock["response"].any() and not np.allclose(clock["mech"][clock["response"]], base[clock["response"]])),
        "hazards_in_unit": bool(np.all((clock["mech"] >= 0.0) & (clock["mech"] <= 1.0))),
        "shock_raises_survival": public["rows"][1]["S_shock"] > public["rows"][1]["S_base"],
        "public_has_no_id": "id_student" not in public and all("id_student" not in row for row in public["rows"]),
    }


def synthetic_clock(results: list[dict]) -> None:
    toy_active_ignores_event()
    toy_response_window()
    rows = []
    for week, recency, clicks in ((0, 1, 0.0), (1, 0, 10.0), (2, 0, 0.0), (3, 0, 4.0), (4, 0, 1.0), (5, 1, 3.0), (6, 0, 2.0), (7, 0, 2.0)):
        rows.append(
            {
                "id_student": 1,
                "code_module": "AAA",
                "code_presentation": "2013J",
                "week": week,
                "recency": recency,
                "total_clicks": clicks,
                "streak": 0,
                "submitted_this_week": 0,
                "event": 0,
                "lag_available": int(week > 0),
                "total_clicks_lag": 0.0,
                "recency_lag": 4.0,
                "streak_lag": 0.0,
                "submitted_lag": 0.0,
                "studied_credits": 60,
                "num_of_prev_attempts": 0,
                "highest_education": "A Level or Equivalent",
                "age_band": "0-35",
                "gender": "M",
            }
        )
    toy = attach_s_star(pd.DataFrame(rows))
    record(results, "T1", "uma ativação", int(toy["s_star"].iloc[0]) == 0, "s* único")
    active = active_from_recency(toy)
    record(results, "T2", "ação em {s*+1, s*+2}", active.tolist() == [False, True, True, False, False, False, False, False], "janela")
    base = np.full(len(toy), 0.2)
    shock = np.clip(base * (1.0 - DELTA * active.astype(float)), EPS, 1.0 - EPS)
    record(results, "T3", "choque só na ação", abs(shock[1] - 0.184) < 1e-12 and abs(shock[0] - 0.2) < 1e-12, "h(1)=0.184")
    plan = response_plan(toy)
    on = rewritten_features(toy, plan, ALPHA_FIRST, ALPHA_SECOND, enabled=True)
    off = rewritten_features(toy, plan, ALPHA_FIRST, ALPHA_SECOND, enabled=False)
    forced = rewritten_features(toy, plan, 0.0, 0.0, enabled=True)
    response = plan["first_response"].to_numpy() | plan["second_response"].to_numpy()
    zero_stays = float(on.loc[toy["week"] == 3, "total_clicks_lag"].iloc[0]) == 0.0
    forced_moves = not np.allclose(forced.loc[response, "recency_lag"], toy.loc[response, "recency_lag"])
    record(results, "T4", "identidade e clique zero", off[FEATURES].equals(toy[FEATURES]) and forced_moves and zero_stays, "semana 3")
    second = float(on.loc[toy["week"] == 3, "total_clicks_lag"].iloc[0])
    action_same = on.loc[toy["week"] == 1, FEATURES].equals(toy.loc[toy["week"] == 1, FEATURES])
    record(results, "T5", "ação não altera a própria semana", action_same and second == 0.0 and response.tolist() == [False, False, True, True, False, False, False, False], "estado observado")
    quiet = toy.drop(columns=["s_star"]).copy()
    quiet["recency"] = 0
    record(results, "T1b", "sem gatilho", not active_from_recency(quiet).any(), "recência 0")


def mechanism_respects_clock(frame: pd.DataFrame, base: np.ndarray, model) -> dict:
    attached = frame if "s_star" in frame.columns else attach_s_star(frame)
    plan = response_plan(attached)
    features = rewritten_features(attached, plan, ALPHA_FIRST, ALPHA_SECOND, enabled=True)
    response = plan["first_response"].to_numpy() | plan["second_response"].to_numpy()
    first_action = np.isfinite(attached["s_star"].to_numpy(dtype=float)) & (attached["week"].to_numpy() == attached["s_star"].to_numpy() + 1)
    mech = base.copy()
    changed = response & ~(
        np.isclose(features["total_clicks_lag"], attached["total_clicks_lag"])
        & np.isclose(features["recency_lag"], attached["recency_lag"])
        & np.isclose(features["streak_lag"], attached["streak_lag"])
        & np.isclose(features["submitted_lag"], attached["submitted_lag"])
    )
    if changed.any():
        mech[changed] = model.predict_proba(features.loc[changed, FEATURES])[:, 1]
    action_unchanged = float(np.max(np.abs(mech[first_action] - base[first_action]))) == 0.0 if first_action.any() else True
    outside = float(np.max(np.abs(mech[~response] - base[~response]))) == 0.0 if (~response).any() else True
    return {"mech": mech, "action_unchanged": action_unchanged, "outside_unchanged": outside, "response": response}


def public_rows(frame: pd.DataFrame, base: np.ndarray, shock: np.ndarray, mech: np.ndarray, s_star) -> dict:
    sub = frame.sort_values("week").copy()
    hazard = np.clip(np.column_stack([base, shock, mech]), EPS, 1.0 - EPS)
    survival = np.exp(np.cumsum(np.log1p(-hazard), axis=0))
    rows = []
    for i, week in enumerate(sub["week"].astype(int)):
        rows.append(
            {
                "week": int(week),
                "h_base": round(float(hazard[i, 0]), 4),
                "h_shock": round(float(hazard[i, 1]), 4),
                "h_mech": round(float(hazard[i, 2]), 4),
                "S_base": round(float(survival[i, 0]), 5),
                "S_shock": round(float(survival[i, 1]), 5),
                "S_mech": round(float(survival[i, 2]), 5),
            }
        )
    return {"s_star": None if s_star is None or (isinstance(s_star, float) and np.isnan(s_star)) else int(s_star), "rows": rows}


def gender_on_r18(table: pd.DataFrame) -> dict:
    if not {"dS", "female"} <= set(table.columns):
        raise RuntimeError("R18 sem dS ou sexo")
    overall = float(table["dS"].mean())
    female = table["female"].astype(bool)
    weighted = float((table.loc[female, "dS"].sum() + table.loc[~female, "dS"].sum()) / len(table))
    return {
        "delta_s": overall,
        "female_mean": float(table.loc[female, "dS"].mean()) if female.any() else None,
        "male_mean": float(table.loc[~female, "dS"].mean()) if (~female).any() else None,
        "weighted_matches": abs(overall - weighted) < 1e-12,
        "disability": "NOT_SUPPORTED",
        "causal_claim": False,
    }


def _decimal_places(key: str) -> int | None:
    if "dp" not in key:
        return None
    digits = key.rsplit("_", 1)[-1]
    if digits.endswith("dp") and digits[:-2].isdigit():
        return int(digits[:-2])
    return None


def verdict(rows: list[dict]) -> str:
    if not rows or any(row["status"] != "PASS" for row in rows):
        return "FAIL"
    return "PASS"


def compare_baseline(found: dict, baseline: dict, tolerance: float = 1e-12) -> list[dict]:
    rows = []
    for key, expected in baseline.items():
        if key in {"source", "legacy_not_targets", "absolute_tolerance"}:
            continue
        if expected == "A CONFIRMAR":
            rows.append({"metric": key, "status": "BLOCKED", "expected": expected, "observed": found.get(key), "tolerance": None})
            continue
        if key not in found:
            rows.append({"metric": key, "status": "FAIL", "expected": expected, "observed": None, "tolerance": None})
            continue
        observed = found[key]
        if observed == "A CONFIRMAR":
            rows.append({"metric": key, "status": "BLOCKED", "expected": expected, "observed": observed, "tolerance": None})
            continue
        if isinstance(expected, list):
            ok = isinstance(observed, list) and len(observed) == len(expected) and all(abs(float(a) - float(b)) <= tolerance for a, b in zip(observed, expected))
            rows.append({"metric": key, "status": "PASS" if ok else "FAIL", "expected": expected, "observed": observed, "tolerance": tolerance})
            continue
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            places = _decimal_places(str(key))
            if places is not None:
                ok = round(float(observed), places) == round(float(expected), places)
                used = f"{places}dp"
            elif isinstance(expected, int):
                ok = int(observed) == expected
                used = "exato"
            else:
                ok = abs(float(observed) - float(expected)) <= tolerance
                used = tolerance
            rows.append({"metric": key, "status": "PASS" if ok else "FAIL", "expected": expected, "observed": observed, "tolerance": used})
            continue
        rows.append({"metric": key, "status": "PASS" if observed == expected else "FAIL", "expected": expected, "observed": observed, "tolerance": None})
    return rows


def write_svg(path: Path, series: list[float]) -> None:
    if not series:
        raise RuntimeError("curva vazia")
    width, height = 120, 40
    coords = []
    last = len(series) - 1 or 1
    for i, value in enumerate(series):
        x = 4 + (width - 8) * i / last
        y = 4 + (height - 8) * (1.0 - min(max(float(value), 0.0), 1.0))
        coords.append(f"{x:.1f},{y:.1f}")
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><polyline fill="none" stroke="#222" points="{" ".join(coords)}"/></svg>\n', encoding="utf-8")


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def policy_contrasts(both: pd.DataFrame) -> dict:
    from .science import bootstrap

    def one(column: str, scenario: str) -> dict:
        work = both.copy()
        work["dS"] = work[column]
        work["S_scenario"] = work[scenario]
        boot_s, boot_g = bootstrap(work, "dS")
        female = work["female"].to_numpy()
        point_gap = gap(work[scenario].to_numpy(), female) - gap(work["S_base"].to_numpy(), female)
        return {
            "delta_s": float(work["dS"].mean()),
            "delta_s_ci": [float(np.quantile(boot_s, 0.025)), float(np.quantile(boot_s, 0.975))],
            "delta_gap": point_gap,
            "delta_gap_ci": [float(np.quantile(boot_g, 0.025)), float(np.quantile(boot_g, 0.975))] if len(boot_g) else None,
        }

    shock = one("dS_shock", "S_shock")
    mechanism = one("dS_mech", "S_mech")
    return {
        "n_r18_enrollments": int(len(both)),
        "n_r18_students": int(both["id_student"].nunique()),
        "delta_s_shock": shock["delta_s"],
        "delta_s_shock_ci": shock["delta_s_ci"],
        "delta_gap_shock": shock["delta_gap"],
        "delta_gap_shock_ci": shock["delta_gap_ci"],
        "delta_s_mechanism": mechanism["delta_s"],
        "delta_s_mechanism_ci": mechanism["delta_s_ci"],
        "delta_gap_mechanism": mechanism["delta_gap"],
        "delta_gap_mechanism_ci": mechanism["delta_gap_ci"],
        "causal_claim": False,
    }


def scenario_gender(table: pd.DataFrame, scenario: str, contrast: str) -> dict:
    female = table["female"].astype(bool)
    base_gap = gap(table["S_base"].to_numpy(), female.to_numpy())
    scenario_gap = gap(table[scenario].to_numpy(), female.to_numpy())
    overall = float(table[contrast].mean())
    female_mean = float(table.loc[female, contrast].mean()) if female.any() else None
    male_mean = float(table.loc[~female, contrast].mean()) if (~female).any() else None
    return {
        "n_enrollments": int(len(table)),
        "n_students": int(table["id_student"].nunique()) if "id_student" in table.columns else None,
        "n_female_enrollments": int(female.sum()),
        "n_male_enrollments": int((~female).sum()),
        "n_female_students": int(table.loc[female, "id_student"].nunique()) if "id_student" in table.columns and female.any() else None,
        "n_male_students": int(table.loc[~female, "id_student"].nunique()) if "id_student" in table.columns and (~female).any() else None,
        "base_gap": base_gap,
        "scenario_gap": scenario_gap,
        "delta_gap": scenario_gap - base_gap,
        "delta_s": overall,
        "female_mean": female_mean,
        "male_mean": male_mean,
        "female_minus_global": None if female_mean is None else female_mean - overall,
        "male_minus_global": None if male_mean is None else male_mean - overall,
        "disability": "NOT_SUPPORTED",
        "causal_claim": False,
    }


def choose_examples(test: pd.DataFrame, both: pd.DataFrame) -> pd.DataFrame:
    enroll = test.groupby(KEYS, as_index=False).agg(s_star=("s_star", "min"), week_max=("week", "max"), n_events=("event", "sum"))
    enroll["tie"] = tie_key(enroll)
    enroll["enrollment"] = enroll["id_student"].astype(str) + "|" + enroll["code_module"].astype(str) + "|" + enroll["code_presentation"].astype(str)
    known = enroll["s_star"].notna()
    enroll["has_action"] = known & enroll["week_max"].ge(enroll["s_star"] + 1)
    enroll["has_response"] = known & enroll["week_max"].ge(enroll["s_star"] + 2)
    enroll["has_full"] = known & enroll["week_max"].ge(enroll["s_star"] + 3)
    early_pool = enroll.loc[enroll["has_full"]]
    if early_pool.empty:
        raise RuntimeError("não há matrícula com as duas respostas para o exemplo A")
    early = early_pool.loc[early_pool["s_star"] == early_pool["s_star"].min()].sort_values("tie").iloc[0]
    late_pool = enroll.loc[enroll["has_response"] & ~enroll["enrollment"].eq(early["enrollment"])]
    if late_pool.empty:
        raise RuntimeError("não há segunda matrícula com resposta para o exemplo B")
    late = late_pool.sort_values(["s_star", "tie"], ascending=[False, True]).iloc[0]
    never_pool = enroll.loc[~enroll["has_action"] & ~enroll["enrollment"].isin([early["enrollment"], late["enrollment"]])]
    if never_pool.empty:
        raise RuntimeError("não há matrícula sem ação para o exemplo C")
    no_trigger = never_pool.loc[never_pool["s_star"].isna()]
    never = (no_trigger if len(no_trigger) else never_pool).sort_values("tie").iloc[0]
    never_note = "sem gatilho" if pd.isna(never["s_star"]) else "gatilho sem semana de ação"
    ranked = both.copy()
    ranked["tie"] = tie_key(ranked)
    ranked["enrollment"] = ranked["id_student"].astype(str) + "|" + ranked["code_module"].astype(str) + "|" + ranked["code_presentation"].astype(str)
    ranked["abs_gap"] = (ranked["S_scenario"] - ranked["S_base"]).abs()
    used = {early["enrollment"], late["enrollment"], never["enrollment"]}
    extreme_pool = ranked.loc[~ranked["enrollment"].isin(used)]
    if extreme_pool.empty:
        raise RuntimeError("não há matrícula restante em R18 para o exemplo D")
    extreme = extreme_pool.sort_values(["abs_gap", "tie"], ascending=[False, True]).iloc[0]
    chosen = [
        ("A", "ativação precoce", early, "menor s* com as duas respostas observadas"),
        ("B", "ativação tardia", late, "maior s* com resposta observada"),
        ("C", "nunca ativado", never, never_note),
        ("D", "contraste absoluto máximo em R18", extreme, "maior |S_mech-S_base| em R18, não um caso típico"),
    ]
    out = []
    for label, kind, row, note in chosen:
        s_value = row["s_star"] if "s_star" in row.index else None
        out.append(
            {
                "label": label,
                "kind": kind,
                "note": note,
                "id_student": int(row["id_student"]),
                "code_module": row["code_module"],
                "code_presentation": row["code_presentation"],
                "s_star": None if pd.isna(s_value) else int(s_value),
            }
        )
    return pd.DataFrame(out)


def public_example(test: pd.DataFrame, base: np.ndarray, shock: np.ndarray, mech: np.ndarray, spec: pd.Series) -> dict:
    mask = test["id_student"].eq(spec["id_student"]) & test["code_module"].eq(spec["code_module"]) & test["code_presentation"].eq(spec["code_presentation"])
    sub = test.loc[mask, ["week", "event", "s_star"]].copy()
    sub["h_base"] = base[mask.to_numpy()]
    sub["h_shock"] = shock[mask.to_numpy()]
    sub["h_mech"] = mech[mask.to_numpy()]
    sub = sub.sort_values("week")
    hazard = np.clip(sub[["h_base", "h_shock", "h_mech"]].to_numpy(dtype=float), EPS, 1.0 - EPS)
    survival = np.exp(np.cumsum(np.log1p(-hazard), axis=0))
    if (np.diff(survival, axis=0) > 1e-9).any():
        raise RuntimeError(f"exemplo {spec['label']} teve sobrevida crescente")
    sub["S_base"], sub["S_shock"], sub["S_mech"] = survival[:, 0], survival[:, 1], survival[:, 2]
    s_star = None if pd.isna(spec["s_star"]) else int(spec["s_star"])
    if spec["note"] == "sem gatilho":
        if float(np.max(np.abs(sub["h_shock"] - sub["h_base"]))) > 1e-12 or float(np.max(np.abs(sub["h_mech"] - sub["h_base"]))) > 1e-12:
            raise RuntimeError("exemplo sem gatilho alterou um hazard")
    weeks = set(sub["week"].astype(int))
    show = set()
    if s_star is None:
        show.update([int(sub["week"].min()), int(sub["week"].max())])
    else:
        for week in (s_star - 1, s_star, s_star + 1, s_star + 2, s_star + 3):
            if week in weeks:
                show.add(week)
    event_weeks = sub.loc[sub["event"].eq(1), "week"]
    event_week = None if event_weeks.empty else int(event_weeks.iloc[0])
    if event_week is not None:
        show.add(event_week)
    if 18 in weeks:
        show.add(18)
    rows = []
    indexed = sub.set_index("week")
    for week in sorted(show):
        row = indexed.loc[week]
        roles = []
        if s_star is None:
            roles.append("sem gatilho")
        else:
            if week < s_star + 1:
                roles.append("antes")
            if week == s_star:
                roles.append("gatilho")
            if week in {s_star + 1, s_star + 2}:
                roles.append("ação")
            if week in {s_star + 2, s_star + 3}:
                roles.append("resposta")
            if week > s_star + 3:
                roles.append("depois")
        if int(row["event"]) == 1:
            roles.append("evento")
        rows.append(
            {
                "week": int(week),
                "role": "+".join(roles),
                "h_base": round(float(row["h_base"]), 4),
                "h_shock": round(float(row["h_shock"]), 4),
                "h_mech": round(float(row["h_mech"]), 4),
                "S_base": round(float(row["S_base"]), 5),
                "S_shock": round(float(row["S_shock"]), 5),
                "S_mech": round(float(row["S_mech"]), 5),
            }
        )
    if s_star is not None:
        before = sub["week"].lt(s_star + 1)
        if before.any():
            deviation = np.abs(sub.loc[before, ["h_shock", "h_mech"]].to_numpy(dtype=float) - sub.loc[before, ["h_base"]].to_numpy(dtype=float))
            if float(np.max(deviation)) > 1e-12:
                raise RuntimeError(f"exemplo {spec['label']} mudou uma semana anterior à ação")
    public = {"label": spec["label"], "kind": spec["kind"], "note": spec["note"], "s_star": s_star, "n_weeks": int(len(sub)), "event_week": event_week, "rows": rows}
    if "id_student" in public:
        raise RuntimeError("exemplo público contém identificador")
    return public


def _brackets(point: float, interval: list[float] | None) -> bool:
    return interval is not None and len(interval) == 2 and interval[0] <= point <= interval[1] and np.isfinite(interval).all()


def example_study() -> dict:
    from .science import survival_at_18

    rows = []
    specs = [(1, 0, 4, "M"), (2, 5, 8, "F"), (3, None, 3, "M"), (4, 1, 18, "M"), (5, 2, 18, "F")]
    for student, s_star, last, gender in specs:
        for week in range(last + 1):
            rows.append(
                {
                    "id_student": student,
                    "code_module": "AAA",
                    "code_presentation": "2013J",
                    "week": week,
                    "event": 0,
                    "gender": gender,
                    "s_star": np.nan if s_star is None else s_star,
                }
            )
    frame = pd.DataFrame(rows)
    base = np.full(len(frame), 0.2)
    shock = base.copy()
    mech = base.copy()
    s_star = frame["s_star"].to_numpy(dtype=float)
    week = frame["week"].to_numpy(dtype=int)
    known = np.isfinite(s_star)
    shock[known & ((week == s_star + 1) | (week == s_star + 2))] = 0.2 * (1.0 - DELTA)
    response = known & ((week == s_star + 2) | (week == s_star + 3))
    mech[response] = 0.1
    mech[response & frame["id_student"].eq(4).to_numpy()] = 0.05
    base_s = survival_at_18(frame, base)
    mech_s = survival_at_18(frame, mech)
    both = base_s.merge(mech_s[KEYS + ["S"]], on=KEYS, suffixes=("_base", "_scenario"))
    specs_private = choose_examples(frame, both)
    again = choose_examples(frame, both)
    public = [public_example(frame, base, shock, mech, spec) for _, spec in specs_private.iterrows()]
    shock_s = survival_at_18(frame, shock).rename(columns={"S": "S_shock"})
    payload = both.merge(shock_s[KEYS + ["S_shock"]], on=KEYS).rename(columns={"S_scenario": "S_mech"})
    payload["dS_shock"] = payload["S_shock"] - payload["S_base"]
    payload["dS_mech"] = payload["S_mech"] - payload["S_base"]
    payload["female"] = payload["gender"].astype(str).eq("F")
    contrasts = policy_contrasts(payload)
    source = hashlib.sha256(frame.sort_values(KEYS + ["week"]).to_csv(index=False).encode()).hexdigest()
    results = []
    record(results, "T0", "hash da fonte usada nesta auditoria", source == hashlib.sha256(frame.sort_values(KEYS + ["week"]).to_csv(index=False).encode()).hexdigest(), source)
    labels_ok = specs_private["label"].tolist() == ["A", "B", "C", "D"] and specs_private["label"].tolist() == again["label"].tolist()
    record(results, "T8", "choque e mecanismo com IC e a mesma seleção", labels_ok and _brackets(contrasts["delta_s_shock"], contrasts["delta_s_shock_ci"]) and _brackets(contrasts["delta_s_mechanism"], contrasts["delta_s_mechanism_ci"]), "TEST_ONLY")
    record(results, "T7b", "exemplos públicos sem identificador", all("id_student" not in item and all("id_student" not in row for row in item["rows"]) for item in public), "A-D")
    return {"frame": frame, "base": base, "shock": shock, "mech": mech, "both": payload, "private": specs_private, "public": public, "contrasts": contrasts, "tests": results, "source_sha256": source}


BASELINE_FIELDS = (
    ("n_enrollments", "p1", "n_enrollments"),
    ("n_students", "p1", "n_students"),
    ("n_events", "p1", "n_events"),
    ("n_test_students", "p1", "n_test_students"),
    ("n_test_enrollments", "p1", "n_test_enrollments"),
    ("n_test_events", "p1", "n_test_events"),
    ("overlap_students", "p1", "overlap_students"),
    ("n_test_rows", "p2", "n_test_rows"),
    ("weekly_auc_4dp", "p2", "weekly_auc_4dp"),
    ("weekly_brier_6dp", "p2", "weekly_brier_6dp"),
    ("landmark_ipcw_auc_4dp", "landmark", "landmark_ipcw_auc_4dp"),
    ("landmark_unweighted_auc_4dp", "landmark", "landmark_unweighted_auc_4dp"),
    ("g18_4dp", "a3", "g18_4dp"),
    ("n_r18_enrollments", "p3", "n_r18_enrollments"),
    ("n_r18_students", "p3", "n_r18_students"),
    ("delta_s_shock", "p3", "delta_s_shock"),
    ("delta_s_shock_ci", "p3", "delta_s_shock_ci"),
    ("delta_s_mechanism", "p3", "delta_s_mechanism"),
    ("delta_s_mechanism_ci", "p3", "delta_s_mechanism_ci"),
    ("delta_gap_mechanism", "p3", "delta_gap_mechanism"),
    ("delta_gap_mechanism_ci", "p3", "delta_gap_mechanism_ci"),
    ("delta_gap_shock_10dp", "p3", "delta_gap_shock"),
    ("delta_gap_shock_ci_10dp", "p3", "delta_gap_shock_ci"),
)


def baseline_map() -> list[dict]:
    rows = []
    for baseline_key, source, field in BASELINE_FIELDS:
        places = _decimal_places(baseline_key)
        tolerance = f"{places}dp" if places is not None else "1e-12" if baseline_key.startswith("delta_") else "exato"
        rows.append({"baseline": baseline_key, "source": source, "field": field, "tolerance": tolerance})
    rows.append({"baseline": "delta_gap_shock_full_float", "source": None, "field": None, "tolerance": "A CONFIRMAR"})
    return rows


def assemble_found(parts: dict) -> dict:
    found = {}
    for baseline_key, source, field in BASELINE_FIELDS:
        part = parts.get(source)
        if isinstance(part, dict) and field in part:
            found[baseline_key] = part[field]
    return found


def classify_hashes(raw: Path, hashes: dict) -> list[dict]:
    from .csv_canonical import CONTROL_PENDING, decide

    rows = []
    for name, expected in hashes.items():
        path = raw / str(name)
        if expected in (None, "null"):
            if name in CONTROL_PENDING and path.exists():
                decision = decide(path, name, None)
                if decision["status"] == "FAIL":
                    rows.append({"file": name, "status": "FAIL", "expected": None, "observed": decision.get("observed")})
                    continue
            rows.append({"file": name, "status": "PENDING", "expected": None})
            continue
        if not path.exists():
            rows.append({"file": name, "status": "ABSENT", "expected": expected})
            continue
        decision = decide(path, name, expected)
        row = {"file": name, "status": decision["status"], "expected": expected, "observed": decision.get("observed")}
        if decision.get("validation_mode"):
            row["validation_mode"] = decision["validation_mode"]
        rows.append(row)
    return rows
