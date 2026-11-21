# Consolidação v2 do marco, com a rotina normal

A ordem validada na R4 passou para `evaluate_landmark`. `sort_landmark_test` ordena o teste por `id_student`, `code_module` e `code_presentation` antes de separar observados, casos e controles. `score_ordered_landmark` calcula os dois intervalos e concatena casos e depois controles, sem um `sort_values` posterior. `evaluate_landmark` chama essa função. `clustered_auc` não mudou.

Os escores são os da R1. A prova congelada chama `score_ordered_landmark`, a mesma função do fluxo normal, sobre o teste rotulado da semana 9. Não houve ajuste, recálculo de predição nem chamada a `score_arm`.

Os CSV da R1 permanecem o registro daquela rodada. A comparação desta consolidação usa `baselines/a8_g2c2_dev_targets_v2.csv` e `baselines/a8_g2c2_pub_metrics_v2.csv`. O CSV antigo não é o padrão desta versão.

## O que mudou na tabela

Os alvos v2 têm 99 linhas, 91 valores calculados e 8 `UNAVAILABLE` vazios. Diante de `a8_g2c2_dev_targets.csv`, 87 pontos ficam iguais e quatro pontos de B−9 mudam:

| Indicador | Valor v2 |
| --- | --- |
| `auc_ipcw` | 0.6609101511265063 |
| `G18` | 0.9995014572725653 |
| `ess_casos` | 575.9999905762434 |
| `ess_controles` | 7280.9999999999945 |

A banda IPCW de B−9 passa a 0.6374116319344114 – 0.6840490660573272. Os outros dez extremos de AUC permanecem os alvos históricos. As métricas v2 do Público repetem os pontos calculados na R1 e substituem os doze extremos pelos que a função compartilhada reproduziu. Os 91 pontos ficam a no máximo 1e-9 dos alvos v2.

## Gate reproduzido pela função normal

As seis impressões SHA-256 da primeira aparição de `id_student` coincidem com a R4. Os doze extremos saem com diferença 0. Há 500 draws válidos e semente 42. Os clusters são 6256, 7165 e 7164. Casos, controles e excluídos são 576/6275/435, 576/7283/6 e 576/7281/6. Fail9 continua 9, com 7 no treino e 2 no teste. Os doze contrastes de política já gravados em `a8_g2c2_pub_bootstrap.csv` continuam dentro de 1e-9 dos alvos, com 500 draws; essa comparação só releu os CSV.

| Braço | Intervalo | Extremos |
| --- | --- | --- |
| A | sem peso | 0.6809356084516514 – 0.7239366039461059 |
| A | IPCW | 0.6789912148108949 – 0.7267283656821232 |
| B | sem peso | 0.6384464951900828 – 0.6812849612720163 |
| B | IPCW | 0.6382216262957512 – 0.6839177863773168 |
| B−9 | sem peso | 0.6363269119250804 – 0.6830436239704527 |
| B−9 | IPCW corrigido | 0.6374116319344114 – 0.6840490660573272 |

## Decisão

PASS técnico condicional desta integração: a rotina normal, alimentada com escores fixos, fecha os gates pedidos. `science.py` e os quatro CSV da R1 não foram editados. O script da R4 permanece o registro daquele replay. Este relatório não declara o PASS numérico de G2c.2. A revisão da orquestradora e o aceite do autor continuam pendentes.
