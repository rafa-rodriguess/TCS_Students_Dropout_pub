# Reconciliação final da ordem no bootstrap do marco

O replay usou uma única ordem: `id_student`, `code_module`, `code_presentation`, `week`. O intervalo sem peso sai das linhas com rótulo de caso ou controle nessa ordem. O IPCW concatena os casos e depois os controles, sem reordenar o bloco. Os escores são os da R1. Não houve ajuste.

A R3 tinha invertido a chave, começando por módulo. Essa ordem não foi repetida.

## Gate

Os seis SHA-256 da primeira aparição de cada aluno coincidem com a proveniência informada. Os doze extremos ficam a diferença 0 dos comparadores corretos. A, B e B−9 têm 6256, 7165 e 7164 clusters, com 500 draws válidos. Em B−9, `G(18)`, o ESS dos casos e o ponto da AUC IPCW também ficam a diferença 0 dos valores corrigidos. A banda IPCW corrigida de B−9 é 0.6374116319344114 – 0.6840490660573272.

| Braço | Intervalo | Extremos |
| --- | --- | --- |
| A | sem peso | 0.6809356084516514 – 0.7239366039461059 |
| A | IPCW | 0.6789912148108949 – 0.7267283656821232 |
| B | sem peso | 0.6384464951900828 – 0.6812849612720163 |
| B | IPCW | 0.6382216262957512 – 0.6839177863773168 |
| B−9 | sem peso | 0.6363269119250804 – 0.6830436239704527 |
| B−9 | IPCW corrigido | 0.6374116319344114 – 0.6840490660573272 |

As contagens do marco permanecem 576/6275/435 em A, 576/7283/6 em B e 576/7281/6 em B−9.

## Impressões

| Braço | Sem peso | IPCW |
| --- | --- | --- |
| A | `14406b63104b5d40f5ae4ed659656c7fa7aa5532c416e2a7973e8398bf2f3a18` | `49f43dbb276754a1a937ed2c66688d768c207a22f57ac88bd31dc487ef9311d3` |
| B | `83d8d2ea470caa1963a59517a5079115740bbf8c4865ea6b878d44e12134528c` | `19f47bb7ad9ae4c23f467869edbb98c1f33e6635e6f78fc30acffd791f4eeba2` |
| B−9 | `1d260d1f5f7d023c839e39e5f7d03078a9b8b69b36bcdb0c35a48c7188471276` | `952bb9588bbb19f2b796d63f53dfda0d973a614362a7c0178738180ebb89a155` |

## Decisão

PASS técnico deste diagnóstico. Os doze contrastes de política publicados na R1 não foram recalculados. `science.py`, `landmark.py`, o runner, os alvos e as baselines não foram editados. Este relatório não declara o PASS numérico de G2c.2: isso continua dependente da revisão da orquestradora e do aceite do autor.
