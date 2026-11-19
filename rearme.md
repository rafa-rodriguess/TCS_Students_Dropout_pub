# Rearme — TCS, pacote científico público

**Estado verificado em 18/11/2026:** A6.6 **ACEITA por equivalência numérica**; A6.7 em finalização documental. GitHub: [Issue A6.6 #2 — completed](https://github.com/rafa-rodriguess/TCS_Students_Dropout_pub/issues/2) e [integração #4](https://github.com/rafa-rodriguess/TCS_Students_Dropout_pub/pull/4) (`f9c623f4c06e503c756737ed82fa292bc40372f1`). A branch histórica `reproduction_candidate` está preservada em `ff99bbcb30f53bac0e3e7d1f2720a682a5620f51`; a `main` integra as correções aprovadas.

## Evidência de reprodução

- Executora independente: `pub`, repo `rafa-rodriguess/TCS_Students_Dropout_pub`, sem acesso aos dados/artefatos privados da executora `TCS`.
- R4: execução REAL do OULAD oficial; etapas 00–09 PASS, T4/T5/T6 PASS, etapa 10 `PASS_EDITORIAL`; run exit 0.
- R5: correção mínima de `compare_baseline` e **74 testes PASS**; leitura apenas de agregados preservados da R4 produziu **23/23 referências numéricas PASS**, **0 FAIL**, um campo sem referência (`delta_gap_shock_full_float=A CONFIRMAR`) mantido como BLOCKED.
- Nenhum reprocessamento R6 foi realizado ou exigido. O status automático `PASS_REPRODUCTION` **não** foi emitido com o fingerprint novo; aceite científico foi feito pela orquestradora na Issue #2, com foco no resultado numérico e não na igualdade binária.

## Artefatos e arquitetura

- Ponto único `orquestrator.py`, etapas 00–10 comentadas, com módulos em `src/jla/`, testes `tests/`, configuração `config/protocol.yaml`, dependências `requirements.lock`, números congelados `baselines/aggregates.json`.
- O pacote `orchestration/ia_orquestrator/` é software de orquestração entre LLMs (0.1.5 / UTIL_VERSION 3.08), **separado** do runner científico.
- Git não contém OULAD bruto, `models/`, `results/private/`, predições por estudante ou arquivos secretos.
- R1/R2/R4: outputs privados históricos preservados **no ambiente isolado da executora**, não publicados no repositório. Não presumir caminhos absolutos nem reutilizar checkpoints de revisões diferentes.

## Comandos de instalação e execução

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python orquestrator.py --plan

# Usar saída NOVA fora do repositório:
.venv/bin/python orquestrator.py --all --allow-download --output-dir /diretorio/externo/novo

# Comparação formal somente se fingerprint/checkpoints dessa saída coincidirem:
.venv/bin/python orquestrator.py --compare-baseline --output-dir /diretorio/externo/novo
```

O `--resume` exige `state.json` e fingerprint exatamente compatível. **Nunca** reescrever checkpoint, trocar hashes ou importar artefatos da repo privada para obter PASS. Os hashes brutos de `courses.csv`, `vle.csv`, ZIP e o float completo sem referência são informações pendentes, **não** reprovações dos 23 números reproduzidos.

## Próximo grupo do projeto

A7 (manuscrito JLA): alinhar `paper5_jla.tex` e `paper5_jla_anon.tex` na repo de desenvolvimento, com as métricas auditadas; responder às 20 críticas e preparar cartas ao editor e pareceristas. Nenhum texto de manuscrito foi alterado por esta reprodução.

Fonte de verdade para status científico: [Issue #2](https://github.com/rafa-rodriguess/TCS_Students_Dropout_pub/issues/2); conferir commits e os resultados registrados antes de qualquer mudança adicional.
