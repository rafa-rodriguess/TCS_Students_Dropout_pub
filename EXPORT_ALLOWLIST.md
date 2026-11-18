# Allowlist de exportação

Candidato preparado. A repo `rafa-rodriguess/TCS_Students_Dropout_pub` existe, está pública, em `main`, e vazia. Não contém este pacote e não houve transferência de código. Não fazer fork, mirror nem enviar o `.git` da repo privada.

Código científico-base auditado: `92d242688b468d610b688192a1707c92dd6669c5`.

Cada caminho abaixo, relativo a `a6_public_candidate/`, iria para a mesma posição na raiz futura. Exportar só por esta lista. Não usar `git add .`.

## Incluir

Os 33 caminhos da auditoria, mais `LICENSE`, `requirements-test.txt` e `tests/test_round9.py`, exigidos por esta rodada. `EXPORT_ALLOWLIST.md` entra na lista e não é hasheado aqui, para não haver hash de si mesmo. Os identificadores abaixo são Git blob SHA-1, os mesmos de `git hash-object`, e não são SHA-256.

| Caminho | Git blob SHA-1 (40 hex) |
|---|---|
| `.gitignore` | `a7792466ca3f052df54c653286c307be24664cc2` |
| `README.md` | `e726a2704a2420c33c6621ffef0ad7a7e3e13ce6` |
| `rearme.md` | `8c4761024a772d8d1030f46e64b3eb09f4edcc7c` |
| `orquestrator.py` | `383d989c37eb7e3ab2551d6889ab21f2b4a7f6b2` |
| `requirements.lock` | `3256c1337d7636d35521ecac7cebcb621d32f078` |
| `requirements.txt` | `b1bb7edb897fa671b453c9a1cddf9493ee66e3ac` |
| `requirements-test.txt` | `34e627f3be061116773352a3860c56ec89ee2eb5` |
| `LICENSE` | `5aaafc01acf74a159541b3dfe938562a115cee8e` |
| `config/protocol.yaml` | `ec80f725d9b0de370e3859d61b51eb7782d68ee5` |
| `baselines/aggregates.json` | `97b7e6e071246a0d2a0f9cbb95604096a2d90a15` |
| `src/jla/__init__.py` | `f67b602813c8486a98736ba76b03b65fffe05f43` |
| `src/jla/audit.py` | `1c85ace58dffc7687544837c87c2e463ad4e016c` |
| `src/jla/checkpoint.py` | `f8fa8f12fef80e73b741903bc1f6cfe881ca9cbb` |
| `src/jla/landmark.py` | `f09f35917f24dfa314684004fa45c09fa0b72914` |
| `src/jla/paths.py` | `966c28458902d28a1db5d0bfba8de492a3abeb5c` |
| `src/jla/protocol.py` | `5e57f3ff5ffe81daae892f32480fce0e317b4d11` |
| `src/jla/science.py` | `c168e8716ac1be639ba72bbb81cef67d5c074b17` |
| `src/jla/stage00_env.py` | `9f5af61f41b7411b502770a7cc6c926e935c9d71` |
| `src/jla/stage01_download.py` | `018d5e14dcd25bd5665ceb1a6ffed3c565943d8f` |
| `src/jla/stage02_validate.py` | `46f7715f33e8fb1f815f8e388dbe048be9aa1444` |
| `src/jla/stage03_cohort.py` | `785170224b81ed02196ecf5eb1f393213e211d31` |
| `src/jla/stage04_split.py` | `e102b53426759a79c787f2078bf3db8fb2e9947e` |
| `src/jla/stage05_model.py` | `2232977fdf37186ad20c7b1c70dd36fd588184d9` |
| `src/jla/stage06_censoring.py` | `d41969f2a73f0b725ba0f9fcada242f76552cca1` |
| `src/jla/stage07_policy.py` | `c630920aa06d235ce8185b058aa4b1de4120a175` |
| `src/jla/stage08_operator.py` | `fb99e942c82ac0641d3a15fc3d5ed2004ebe1761` |
| `src/jla/stage09_equity.py` | `a7d846f64bea98e596f99fb2470742942c1c52ee` |
| `src/jla/stage10_report.py` | `39ec83c2d7c611c7ccc3e7029c4ad3051bb975e3` |
| `tests/test_structure.py` | `21424c72d67e6ab2d369ca1200de381eb3c9f30d` |
| `tests/test_round2.py` | `02a3b5d04acadd1303546cff5a41d0b47d7d2ef8` |
| `tests/test_round3.py` | `db08b80aa2fc9b541095b35867c5945af3084589` |
| `tests/test_round4.py` | `6583c3fb3e1decfbd51ef6a795598097e3a4530f` |
| `tests/test_round5.py` | `9cb4ac7e68fa6440795ba81f75493ab09c27b07e` |
| `tests/test_round7.py` | `72d272f54135f6583862f7c50edbff1398f0c187` |
| `tests/test_round8.py` | `a3bca74c9161b512472f3a05782c5db985415e3f` |
| `tests/test_round9.py` | `08159d8cae520c28c6b1dd4e2c342601b797335b` |

`.gitignore`, `README.md`, `rearme.md` e `orquestrator.py` foram alterados nesta rodada. `baselines/aggregates.json` não foi alterado. O copyright da MIT usa a conta `rafa-rodriguess`. A parte dos coautores do manuscrito continua pendente.

## Omitir

- `data/`, `models/`, `results/` inteiro, `figures/`, `logs/`, `checkpoints/`
- CSV, ZIP, `studentVle.csv`, `*.joblib` e escores
- `.env`, tokens, webhooks, `util/discord_msg/` e `util/ia_orquestrator/`
- o `.git` da repo privada e qualquer arquivo fora desta lista
- `A6_ORQUESTRACAO_PUBLICA_PROPOSTA.md` fica na repo privada, fora do pacote científico

Prova de exclusão: `git check-ignore` aponta `a6_public_candidate/.gitignore` para `results/p3_metrics.json`, `results/public_examples.json`, `figures/rascunho.svg`, `data/raw/studentVle.csv` e `models/hazard.joblib`. `baselines/`, `config/protocol.yaml`, `src/` e `tests/` continuam versionáveis.

## Bloqueios

Publicação BLOCKED. Hashes de `courses.csv`, `vle.csv` e do ZIP seguem PENDING. O float do ΔGap do choque segue `A CONFIRMAR`. O lock não foi provado em venv limpo. A orquestração LLM não foi copiada. A6.5, A6.6, A6.7 e A7 não foram iniciadas.
