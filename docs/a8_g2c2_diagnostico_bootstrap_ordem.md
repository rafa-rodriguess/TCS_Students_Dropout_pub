# Diagnóstico da ordem no intervalo do marco

O intervalo oficial da R1 não foi substituído. Nenhum modelo foi reajustado. `clustered_auc` permanece com `groupby(id_student, sort=False)`, semente 42 e 500 draws. O checkout público não contém `PAPERS_BACKUP/paper/revisao_jla/a8_b_quantitativo_runner.py`; a comparação usa só `src/jla/science.py` e `src/jla/landmark.py`.

## O que a ordem altera

O ponto da AUC não depende da ordem das linhas. O percentil depende da ordem em que os clusters entram na lista sorteada: a semente percorre posições, e a posição aponta para o aluno conforme a primeira aparição. `evaluate_landmark` monta duas ordens. `observed` segue a ordem do relógio e alimenta `auc_landmark`. `ordered` concatena casos e depois controles e alimenta `auc_ipcw`. As duas listas de clusters não coincidem.

O teste sintético em `tests/test_g2c2_bootstrap_order.py` separa esses fatos: as mesmas linhas em ordem invertida conservam a AUC e mudam os quantis; a passagem de `observed` para `ordered` muda a impressão digital da ordem.

## Replay com escore fixo

Os escores da semana 9 da R1 ainda estavam disponíveis. O replay usa esse escore, o mesmo relógio, o mesmo split e a mesma curva `G` do próprio braço. Há 500 draws válidos em todos os intervalos. Os doze extremos oficiais reproduzem, com diferença 0, os extremos já publicados na R1.

| Braço | Clusters | `auc_landmark` oficial | `auc_ipcw` oficial |
| --- | ---: | --- | --- |
| A | 6256 | 0.6793513747608213 – 0.7272064730202157 | 0.6775766561168993 – 0.7252970000332699 |
| B | 7165 | 0.6361974690820635 – 0.6849010289110501 | 0.6390070554737672 – 0.6836578224167843 |
| B−9 | 7164 | 0.6364787607203767 – 0.6878244462093588 | 0.637323415668671 – 0.6837559171552294 |

As contagens do marco também fecham: A tem 576 casos, 6275 controles e 435 excluídos; B tem 576, 7283 e 6; B−9 tem 576, 7281 e 6.

## Contrafactual canônico

Ordenar os clusters por `id_student` antes do mesmo `clustered_auc` é só diagnóstico. Nesses dados, os seis extremos de `auc_landmark` ficam iguais aos extremos congelados do alvo. A ordem de primeira aparição explica o intervalo público; a ordem crescente do identificador explica o intervalo congelado sem peso.

O mesmo contrafactual não explica `auc_ipcw`. Também não explica o intervalo IPCW quando os pesos acompanham a ordem de clusters de `observed`. As diferenças absolutas desses dois contrafactuais frente ao alvo continuam entre cerca de 2e-4 e 4e-3. A ordem usada no intervalo IPCW congelado fica por identificar. Não houve varredura de permutações para forçá-la.

## Três pontos de B−9

A ordem não move o ponto. O replay de `G(18)` reproduz o valor salvo: B fica em 0.9995016505823404 e B−9 em 0.9995014572725653. A curva de B−9 continua a ser a do próprio treino em risco, depois da retirada de Fail9. A diferença de `G` acompanha `ess_casos` e `auc_ipcw`. O `G` de B não foi copiado.

## Decisão

O intervalo sem peso está isolado: PUB é a ordem de aparição e o alvo congelado coincide com a ordem crescente do identificador. O intervalo IPCW público está reproduzido a partir de `ordered`, mas a ordem correspondente no alvo não foi identificada. O PASS numérico de G2c.2 continua NO-GO. A tolerância de `1e-9` não foi alterada.

Impressões SHA-256 da ordem de clusters, sem identificadores:

| Braço | `observed` | `ordered` | canônica |
| --- | --- | --- | --- |
| A | `395628c7dc1e5b5a54951f9694a7bb2b56dda85cea1d68305d3e01925c17466e` | `af4b7e5d6e7d673df14ec36d3b9f0a7077e64e3aa2a68d125b14dee42fd55322` | `a3bd3d0154a526fc6b5fa55f25979b94d1034b435751e82729203c2e57d7a8c8` |
| B | `662b382d5a660fc5e79334fdf47156998a6ceea405fa79276298c40833c4beb5` | `e4e2f4a429eb71fbe9e2bf550c2c1a840ac510b273d877a7d4b49a4534bdfb07` | `f2e1bc1500505cbd8622bb11d84ccd9f173c7ac339398e638915be4b5797d9a5` |
| B−9 | `001c984c7778bb01628eb9f5fa489430ec20f8ad8ee2fe0a92083bc6e0512932` | `df2abac8a31b833bf0ad9104528d6478685eb654c337c8fd3ede32e12f5580b8` | `d17f6cd628a426884c044e74aa77d057cf415ec591c8d17c1b70f3ba11829618` |
