#!/usr/bin/env python3
"""Entrypoint opcional da reprodução G2c.2.

Etapas, nesta ordem, para uma execução futura autorizada:
00. Conferir Python e pins; não alterar o protocolo A6.
01. Inventariar os sete CSV oficiais; este comando não baixa.
02. Aplicar o gate de hash bruto ou a equivalência semântica já publicada, sem regravar CSV.
03. Construir o relógio A com as funções históricas.
04. Construir B e B−9 só com máscara explícita de conflito.
05. Aplicar lag t−1 e a proibição de vazamento.
06. Registrar a especificação do modelo; não ajustar.
07. Conferir o catálogo de 99 células e 12 contrastes; não calcular métricas.

Entrada: diretório externo com os sete CSV, nunca o checkout.
Saída: diretório externo de agregados, nunca o checkout.
R2 aceita --plan, --preflight e --synthetic-proof. --fit continua recusado.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from jla.g2c2 import bootstrap_catalog, contract_checklist, indicator_catalog, model_specification, preflight_decision, refuse_fit  # noqa: E402
from jla.g2c2_execute import run_approved  # noqa: E402
from jla.g2c2_gates import measure, structural_report  # noqa: E402
from jla.g2c2_metrics import synthetic_end_to_end  # noqa: E402


def _outside(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != ROOT and ROOT not in resolved.parents


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="reprodução G2c.2; R0 não ajusta nem baixa")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--synthetic-proof", action="store_true")
    parser.add_argument("--structural-gates", action="store_true")
    parser.add_argument("--run-approved", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--fit", action="store_true")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.fit or args.allow_download:
        refuse_fit()
    if args.data_dir is not None and not _outside(args.data_dir):
        print("dados dentro do checkout", file=sys.stderr)
        return 2
    if args.output_dir is not None and not _outside(args.output_dir):
        print("saída dentro do checkout", file=sys.stderr)
        return 2
    if args.plan:
        for line in __doc__.splitlines():
            if line[:2].isdigit():
                print(line)
        return 0
    if args.preflight:
        decision = preflight_decision()
        spec = model_specification()
        indicators = indicator_catalog(ROOT / "baselines" / "a8_g2c2_dev_targets.csv")
        contrasts = bootstrap_catalog(ROOT / "baselines" / "a8_g2c2_bootstrap_targets.csv")
        print(f"decisão {decision['decision']}")
        print(f"indicadores {indicators['n']} unavailable {indicators['unavailable']} scheduled {indicators['scheduled']}")
        print(f"contrastes {contrasts['n']} draws {spec['bootstrap_draws']} seed {spec['bootstrap_seed']}")
        print("g2c2_numeric_pass NO-GO")
        for item in contract_checklist():
            print(f"{item['code']} {item['status']}")
        return 0
    if args.synthetic_proof:
        proof = synthetic_end_to_end()
        print(f"source {proof['source']} oulad_fit {proof['oulad_fit']} targets_used {proof['targets_used']}")
        print(f"auc {proof['auc']:.6f} brier {proof['brier']:.6f} ece15 {proof['ece15']:.6f}")
        print(f"landmark {proof['landmark_status']} bootstrap {proof['bootstrap_draws']} valid {proof['bootstrap_n_valid']}")
        return 0
    if args.structural_gates:
        if args.data_dir is None:
            print("gates exigem --data-dir externo", file=sys.stderr)
            return 2
        report = structural_report(measure(args.data_dir))
        print(f"structural {report['status']} mismatches {len(report['mismatches'])}")
        for row in report["mismatches"]:
            print(f"{row['gate']} expected {row['expected']} observed {row['observed']}")
        return 0 if report["status"] == "PASS" else 1
    if args.run_approved:
        if args.data_dir is None or args.output_dir is None:
            print("execução exige --data-dir e --output-dir externos", file=sys.stderr)
            return 2
        report = structural_report(measure(args.data_dir))
        if report["status"] != "PASS":
            print(f"structural STOP mismatches {len(report['mismatches'])}")
            return 1
        run_approved(args.data_dir, args.output_dir)
        print("run-approved finished")
        return 0
    print("informe --plan ou --preflight", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
