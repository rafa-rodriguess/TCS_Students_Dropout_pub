# Comparação DEV–PUB da G2c.2

A tolerância foi fixada antes da leitura dos resultados: inteiros exatos e valores contínuos com diferença absoluta máxima de `1e-9`. Não houve identidade de bytes como critério. Os alvos congelados não entraram no ajuste.

## Células

Das 91 células calculadas, 88 passam no ponto. As oito `UNAVAILABLE` permanecem vazias, com a razão publicada. Falham três pontos, todos em B−9:

| Indicador | Diferença PUB − alvo |
| --- | ---: |
| `G18` | −1.9330977507614477e-07 |
| `ess_casos` | −7.323706086026505e-09 |
| `auc_ipcw` | −2.5945472437172157e-09 |

`G(18)` de B coincide com o alvo. `G(18)` de B−9 é calculado no treino em risco desse braço, depois de retirar as matrículas Fail9. A diferença de `G` desloca o peso IPCW e, com ele, o ESS dos casos e a AUC IPCW. Não se reutilizou o `G` de B.

## Intervalos

Dos 23 intervalos publicados no alvo, 17 extremos ficam dentro de `1e-9`. Os seis intervalos do marco, `auc_landmark` e `auc_ipcw` em A, B e B−9, não. A maior diferença absoluta entre extremos é 0.0047808222389060795, no limite superior de `auc_landmark` em B−9. Os pontos desses AUC, salvo `auc_ipcw` de B−9, passam. O intervalo depende da ordem dos clusters no bootstrap de 500 draws. A ordem não foi reorganizada para aproximar o alvo.

Os intervalos de `auc_semanal`, do suporte comum e dos quatro contrastes ΔS/ΔGap passam.

## Bootstrap

As 12 linhas passam em `population_n`, ponto, média bootstrap, viés absoluto, extremos 2.5/97.5, `n_valid`, draws e semente. Todas têm 500 draws válidos, semente 42, unidade `id_student` e modelo fixo.

## Decisão

STOP numérico. O relatório não converte essa divergência em PASS. Não houve novo ajuste, mudança de tolerância nem edição dos alvos.
