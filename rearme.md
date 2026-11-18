# Rearme

Estado: candidato preparado para auditoria de exportação. A repo `rafa-rodriguess/TCS_Students_Dropout_pub` existe, está pública, em `main`, e vazia. Não contém este pacote. Não houve reprodução FULL nem download. Nenhum código foi transferido.

Código científico-base: `92d242688b468d610b688192a1707c92dd6669c5`. Esta rodada acrescenta a licença MIT do código, o `.gitignore` de `data/`, `models/`, `results/` e `figures/`, e a recusa de saída na raiz do checkout.

O que não rodou: download, treino e a auditoria sobre o OULAD. Sem as entradas privadas, a etapa 08 devolve NOT_RUN_SCIENCE. PASS_MOCK não é PASS real. PASS_EDITORIAL não é PASS_REPRODUCTION. A etapa 03 preserva `person_period.csv`. A etapa 04 grava `person_period_split.csv`.

Retomar só num diretório que já tenha checkpoint com o mesmo fingerprint:

`python orquestrator.py --resume --stage 00 --output-dir /caminho/fora/do/checkout`

Um commit novo invalida o fingerprint. O resume não apaga a pasta. Não usar `~/.ia_orchestrator` nem `content/` da repo privada.

Baseline: `baselines/aggregates.json`. O float longo do ΔGap do choque está marcado `A CONFIRMAR`.

Bloqueios abertos: lock sem venv limpo; hashes de `courses.csv`, `vle.csv` e do ZIP; titularidade do copyright além da conta `rafa-rodriguess`; a repo pública existe e está vazia, sem o pacote; orquestração LLM ainda não copiada.
