#!/usr/bin/env python3
"""Runner do estudo JLA. Não baixa nem treina sem as flags e os arquivos desta rodada."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from jla import stage00_env, stage01_download, stage02_validate, stage03_cohort, stage04_split  # noqa: E402
from jla import stage05_model, stage06_censoring, stage07_policy, stage08_operator, stage09_equity, stage10_report  # noqa: E402
from jla.checkpoint import append_log, fingerprint, input_token, invalidate_from, load_state, now, output_token, reusable, save_state  # noqa: E402
from jla.paths import Context  # noqa: E402

# ETAPA 00 — Pré-checagens do ambiente
# Objetivo: conferir o lock e recusar caminho pessoal.
# Módulo: stage00_env.run. Pré-condição: requirements.lock legível.
# Entrada: versões instaladas. Saída: status PASS ou FAIL. Parâmetro: pins do lock.
# Checkpoint: fingerprint do código e das bibliotecas.
STAGE_00 = ("00", stage00_env.run)

# ETAPA 01 — Download do OULAD
# Objetivo: obter o ZIP da UCI só com --allow-download.
# Módulo: stage01_download.run. Pré-condição: URL no protocolo.
# Entrada: nenhum arquivo local. Saída: data/raw/*.csv. Parâmetro: oulad_url.
# Checkpoint: sem rede, o status é DOWNLOAD_NOT_AUTHORIZED.
STAGE_01 = ("01", stage01_download.run)

# ETAPA 02 — Validação dos dados
# Objetivo: schema e hashes conhecidos. Hash divergente não é reescrito.
# Módulo: stage02_validate.run. Pré-condição: sete CSV.
# Entrada: data/raw. Saída: status e lista de hashes ainda nulos.
STAGE_02 = ("02", stage02_validate.run)

# ETAPA 03 — Coorte, endpoint e features defasadas
# Objetivo: Withdrawn com data válida e atraso de uma semana.
# Módulo: stage03_cohort.run. Pré-condição: CSV validados.
# Saída: data/processed/person_period.csv, sem a coluna split. A etapa 04 não reescreve este arquivo.
STAGE_03 = ("03", stage03_cohort.run)

# ETAPA 04 — Split P1
# Objetivo: estudante inteiro de um lado só, semente 42.
# Módulo: stage04_split.run. Saída: person_period_split.csv e chaves locais, não publicadas.
STAGE_04 = ("04", stage04_split.run)

# ETAPA 05 — Treino P2
# Objetivo: um logístico calibrado. Sem segundo ajuste.
# Módulo: stage05_model.run. Entrada: person_period_split.csv. Saída: models/hazard.joblib e escores privados.
STAGE_05 = ("05", stage05_model.run)

# ETAPA 06 — Censura A3
# Objetivo: G(t) no último VLE. Não alonga o painel.
# Módulo: stage06_censoring.run. Saída: results/curves/censoring_g.csv.
STAGE_06 = ("06", stage06_censoring.run)

# ETAPA 07 — Simulações P3
# Objetivo: shock_window. O mecanismo completo depende do estado observado.
# Módulo: stage07_policy.run. Saída: results/p3_metrics.json sem chave publicada.
STAGE_07 = ("07", stage07_policy.run)

# ETAPA 08 — Testes do operador
# Objetivo: reconstruir h(t) e o R18 e confrontar S_base, S_shock e S_mech.
# Módulo: stage08_operator.run. Sem entradas privadas devolve NOT_RUN_SCIENCE.
# MOCK devolve PASS_MOCK e não é auditoria do estudo.
STAGE_08 = ("08", stage08_operator.run)

# ETAPA 09 — Equidade descritiva
# Objetivo: agregados por sexo. Deficiência não é estimada.
# Módulo: stage09_equity.run.
STAGE_09 = ("09", stage09_equity.run)

# ETAPA 10 — Tabelas, figuras e comparação
# Objetivo: matriz do que tem fonte e do que é legado. Sem número do .tex.
# Módulo: stage10_report.run. Saída: results/product_matrix.json.
STAGE_10 = ("10", stage10_report.run)

STAGES = [STAGE_00, STAGE_01, STAGE_02, STAGE_03, STAGE_04, STAGE_05, STAGE_06, STAGE_07, STAGE_08, STAGE_09, STAGE_10]
ORDER = [name for name, _ in STAGES]
STOP = {"FAIL", "NOT_RUN_SCIENCE", "DOWNLOAD_NOT_AUTHORIZED", "NOT_SUPPORTED", "PASS_MOCK"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runner JLA, etapas 00 a 10.")
    parser.add_argument("--all", action="store_true", help="percorre as etapas em ordem e para no primeiro bloqueio")
    parser.add_argument("--stage", choices=ORDER, help="executa uma etapa; exige as anteriores PASS")
    parser.add_argument("--resume", action="store_true", help="pula etapa PASS com o mesmo fingerprint")
    parser.add_argument("--output-dir", type=Path, help="diretorio dedicado fora do checkout; obrigatorio para executar")
    parser.add_argument("--compare-baseline", action="store_true", help="sozinho, compara apenas saídas já existentes")
    parser.add_argument("--allow-download", action="store_true", help="autoriza a rede na etapa 01; fora desta rodada")
    parser.add_argument("--plan", action="store_true", help="lista as etapas e sai sem escrever PASS")
    return parser.parse_args(argv)


def run_one(ctx: Context, name: str, fn, state: dict) -> dict:
    current = fingerprint()
    inputs = input_token(ctx, name)
    if reusable(state, name, current, inputs, output_token(ctx, name)):
        return {"status": "PASS", "message": "retomada; fingerprint igual"}
    started = now()
    result = fn(ctx)
    record = {"stage": name, "started": started, "finished": now(), "fingerprint": current, "input_token": inputs, "output_token": output_token(ctx, name), **result}
    append_log(ctx, record)
    if result.get("status") == "PASS":
        state.setdefault("stages", {})[name] = record
    else:
        invalidate_from(state, name, ORDER)
    save_state(ctx, state)
    return result


def _git_top(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _outside_checkout(path: Path) -> bool:
    resolved = path.resolve()
    top = _git_top(ROOT)
    if top is not None and (resolved == top or top in resolved.parents):
        return False
    root = ROOT.resolve()
    return resolved != root and root not in resolved.parents


def _has_artifacts(path: Path) -> bool:
    return path.exists() and any((path / name).exists() for name in ("data", "models", "results", "figures", "logs", "checkpoints"))


def _resume_block(path: Path) -> str | None:
    state_path = path / "checkpoints" / "state.json"
    if not state_path.is_file():
        return "retomada sem checkpoint valido"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("fingerprint") != fingerprint():
        return "retomada com fingerprint invalido; diretorio preservado"
    stages = state.get("stages") or {}
    if not any(isinstance(row, dict) and row.get("status") == "PASS" for row in stages.values()):
        return "retomada sem etapa PASS"
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.plan:
        for name, _ in STAGES:
            print(f"ETAPA {name}")
        return 0
    if not args.all and not args.stage and not args.compare_baseline:
        print("informe --all, --stage, --plan ou --compare-baseline", file=sys.stderr)
        return 1
    if args.output_dir is None:
        print("execução real exige --output-dir explícito", file=sys.stderr)
        return 1
    output = args.output_dir.resolve()
    if not _outside_checkout(output):
        print("output na raiz ou dentro do checkout do codigo", file=sys.stderr)
        return 1
    compare_only = args.compare_baseline and not args.all and not args.stage
    if not compare_only and _has_artifacts(output):
        if not args.resume:
            print("pasta preexistente com artefatos", file=sys.stderr)
            return 1
        blocked = _resume_block(output)
        if blocked:
            print(blocked, file=sys.stderr)
            return 1
    if not compare_only and args.resume:
        blocked = _resume_block(output)
        if blocked:
            print(blocked, file=sys.stderr)
            return 1
    ctx = Context(output_dir=output, allow_download=args.allow_download, compare_baseline=args.compare_baseline, compare_only=compare_only)
    if compare_only:
        ctx.ensure_dirs()
        last = stage10_report.run(ctx)
        print(f"ETAPA 10 {last.get('status')} {last.get('message', '')}")
        return 0 if last.get("status") == "PASS_REPRODUCTION" else 1
    ctx.ensure_dirs()
    state = load_state(ctx)
    if fingerprint() != state.get("fingerprint"):
        state["stages"] = {}
        state["fingerprint"] = fingerprint()
    selected = STAGES if args.all else [item for item in STAGES if item[0] == args.stage]
    if args.stage:
        index = ORDER.index(args.stage)
        for previous in ORDER[:index]:
            if not reusable(state, previous, fingerprint(), input_token(ctx, previous), output_token(ctx, previous)):
                invalidate_from(state, previous, ORDER)
                save_state(ctx, state)
                print(f"pré-condição: etapa {previous} não está PASS", file=sys.stderr)
                return 1
    last = {"status": "PASS"}
    for name, fn in selected:
        last = run_one(ctx, name, fn, state)
        print(f"ETAPA {name} {last.get('status')} {last.get('message', '')}")
        if last.get("status") in STOP:
            return 2 if last.get("status") != "FAIL" else 1
    return 0 if last.get("status") in {"PASS", "PASS_EDITORIAL", "PASS_REPRODUCTION"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
