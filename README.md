# TCS — Reprodução numérica do estudo JLA / OULAD

Repositório público do pacote científico usado para reproduzir os resultados do estudo de risco temporal de evasão estudantil com dados OULAD. O ponto de entrada é `orquestrator.py` (etapas **00–10**, comentadas e sequenciais). Este runner científico é distinto do software de comunicação entre LLMs em `orchestration/ia_orquestrator/`.

## Resultado da reprodução independente (18/11/2026)

**A6.6 concluída e aceita pela orquestradora por equivalência numérica:** a executora independente `pub` baixou o conjunto oficial, treinou o modelo e passou nas etapas científicas 00–09, incluindo T4/T5/T6. A etapa 10 produziu os materiais editoriais (`PASS_EDITORIAL`). A rodada R5 aplicou em memória o comparador corrigido aos agregados científicos preservados da execução R4: **23 das 23 métricas com referência numérica PASS, 0 FAIL**, nas precisões/tolerâncias especificadas; **74 testes automatizados PASS**. Resultado e decisões estão documentados na [Issue #2](https://github.com/rafa-rodriguess/TCS_Students_Dropout_pub/issues/2) e as correções foram integradas pela [PR #4](https://github.com/rafa-rodriguess/TCS_Students_Dropout_pub/pull/4).

**Escopo preciso:** o `--compare-baseline` oficial da R4, rodado *antes* da correção do comparador de listas `_Ndp`, apresentou 1 FAIL artificial devido à tolerância errada do intervalo `delta_gap_shock_ci_10dp`. A matriz corrigida de 23/23 foi apurada **sem reexecutar treinamento** e **sem alterar os arquivos históricos da R4**. Não foi executado `PASS_REPRODUCTION` da CLI com o fingerprint atualizado. O aceite é **científico por equivalência numérica**, não uma alegação de aprovação desse status automático.

O protocolo mantém `courses.csv`, `vle.csv` e ZIP sem âncoras de hash bruto e `delta_gap_shock_full_float = A CONFIRMAR`. Essas quatro observações **não são divergências numéricas** e não impedem o aceite científico acordado. Os indicadores automáticos `publication_status=BLOCKED` refletem o controle administrativo legado: não significam reprovação da reprodução numérica, nem determinam exigências de submissão do periódico. A adequação do manuscrito é a etapa A7, separada deste pacote.

## Dados e licenças

Fonte oficial: [Open University Learning Analytics Dataset (UCI #349)](https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset).
Download pelo runner: `https://archive.ics.uci.edu/static/public/349/open+university+learning+analytics+dataset.zip`.
Dataset sob CC BY 4.0: atribuir Kuzilek, Hlosta e Zdrahal / Open University. Código deste repositório licenciado em MIT (veja `LICENSE`). A licença do dataset não é a licença dos scripts. **CSV, ZIP, matrículas, modelos e escores individuais não são versionados**.

O arquivo `config/protocol.yaml` contém os parâmetros e referências congelados. O gate `SEMANTIC_CANONICAL_V1` permite apenas equivalência documentada de marcação de ausentes (`?` versus vazio) nas colunas elegíveis: isso **não** altera os dados usados cientificamente nem substitui os hashes brutos. Consulte `docs/csv_equivalence_v1.md`.

## Instalação e testes

O ambiente que executou a reprodução independente reportou Python 3.14.3, NumPy 2.4.4, pandas 2.3.3, scikit-learn 1.8.0 e joblib 1.5.3; conferir `requirements.lock` e não alterar versões silenciosamente.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python orquestrator.py --help
.venv/bin/python orquestrator.py --plan
```

`--help`, `--plan` e os testes por fixtures não baixam dados nem treinam modelos.

## Execução do estudo

Escolha um diretório **novo e vazio, fora do checkout**, para conter dados, modelos, resultados, figuras, logs e checkpoints:

```bash
python orquestrator.py --all --allow-download --output-dir /diretorio/externo/tcs_oulad_novo
```

O runner valida o ambiente, baixa o OULAD autorizado, constrói o painel e split por estudante, treina/calibra o modelo, calcula censura, simulações, auditorias, equidade e produtos editoriais. Resumo das etapas: 00 ambiente; 01 download; 02 dados; 03 coorte/features; 04 split; 05 modelo; 06 censura; 07 políticas; 08 operador; 09 equidade; 10 produtos e comparações.

Para verificar **formalmente** uma execução existente, o comando abaixo só aceita saída com fingerprint de código e checkpoint compatíveis:

```bash
python orquestrator.py --compare-baseline --output-dir /diretorio/externo/tcs_oulad_novo
```

A CLI pode retornar `BLOCKED` por marcadores formais ainda sem referência, mesmo com métricas numéricas coincidentes. `PASS_EDITORIAL` não é prova de reprodução; o resultado aceito para A6.6 consta do relatório da executora e da decisão da orquestradora em #2. Para saídas criadas com código anterior, **não falsificar o fingerprint, editar checkpoints ou usar `--resume` incompatível**.

## Estrutura e continuidade

- `src/jla/`: scripts científicos e funções da auditoria.
- `tests/`: testes offline.
- `baselines/aggregates.json`: resultados congelados para comparação; não substituí-los pelos observados.
- `docs/csv_equivalence_v1.md`: equivalência de marcação dos valores ausentes.
- `orchestration/ia_orquestrator/`: software separado de comunicação/orquestração LLM, UTIL_VERSION 3.08; não executa o modelo.
- `rearme.md`: estado e instruções para retomada.

Se falhar, preserve o diretório de saída para diagnóstico. Não publique `data/`, `results/private/`, `models/`, ZIP ou qualquer identificador de estudante.
