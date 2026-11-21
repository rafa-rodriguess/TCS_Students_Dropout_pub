# Ordem histórica por KEYS no intervalo IPCW

A ordem testada foi uma só: `code_module`, `code_presentation`, `id_student`, `week`. O painel foi ordenado assim antes de separar casos e controles. O IPCW recebeu casos e depois controles, com os pesos na mesma sequência. Não houve refit, nem busca de outra permutação. A constante pública `KEYS` continua `id_student`, `code_module`, `code_presentation` e não foi usada nesta ordenação.

## Replay

Os escores fixos da semana 9 reproduzem as contagens do marco: A tem 576 casos, 6275 controles e 435 excluídos; B tem 576, 7283 e 6; B−9 tem 576, 7281 e 6. Cada intervalo teve 500 draws válidos. `G(18)` permanece 0.9398387446094816 em A, 0.9995016505823404 em B e 0.9995014572725653 em B−9.

A ordem de clusters depois dessa ordenação é a mesma da ordem de matrículas usada na R1. Por isso os doze extremos reproduzem a R1 com diferença 0. `observed` e `ordered` continuam com sequências de clusters diferentes entre si.

| Braço | `auc_landmark` | `auc_ipcw` |
| --- | --- | --- |
| A | 0.6793513747608213 – 0.7272064730202157 | 0.6775766561168993 – 0.7252970000332699 |
| B | 0.6361974690820635 – 0.6849010289110501 | 0.6390070554737672 – 0.6836578224167843 |
| B−9 | 0.6364787607203767 – 0.6878244462093588 | 0.637323415668671 – 0.6837559171552294 |

## Comparação

Os doze extremos não coincidem com os alvos originais. As diferenças são as já vistas na R1, da ordem de 1e-4 a 5e-3. A banda IPCW corrigida de B−9, 0.6374116319344114 – 0.6840490660573272, também não é atingida: as diferenças são −8.821626574040398e-05 e −0.0002931489020977507. O ponto de `auc_ipcw` em B−9 continua −2.5945472437172157e-09 abaixo do alvo original; a ordem não move ponto.

A ordem só por `id_student`, que na R2 coincidiu com o intervalo sem peso do alvo, diverge desta ordem histórica. A primeira posição diferente é o índice 1. Em A, 6255 de 6256 posições diferem; em B, 7162 de 7165; em B−9, 7161 de 7164.

## Impressões int64

O SHA-256 é `np.asarray(ids, dtype=int64).tobytes()`. São sequências de clusters, sem a lista de identificadores.

| Braço | `observed` | `ordered` | só `id_student` |
| --- | --- | --- | --- |
| A | `d0a8222fcd1565a4ad9f50c622fbebc0ea85ec976bc738227cfa63cd40b62c7f` | `c16a6e57c2dd27a1242b3d1a334e92706ae611c01097c90975ac999ca071228d` | `14406b63104b5d40f5ae4ed659656c7fa7aa5532c416e2a7973e8398bf2f3a18` |
| B | `2e00636d5911080ea6d8ad53e96d3ec8eafa93019159c993930e76c6cad700e0` | `5d41f78991456382aed1b06fc38aec37893f2ae2f0d9f7af72665de86499fd18` | `83d8d2ea470caa1963a59517a5079115740bbf8c4865ea6b878d44e12134528c` |
| B−9 | `b88674e9cc103a546a0fd318ff640497686ac3ed883dea1be6ebc1f55f2a8b61` | `806d6501950b28977b81773da5f0e918f99c8bd727bedd0b023f67170827db12` | `1d260d1f5f7d023c839e39e5f7d03078a9b8b69b36bcdb0c35a48c7188471276` |

## Decisão

STOP. A ordenação histórica por KEYS reproduz o intervalo público e não reproduz o intervalo IPCW do alvo, nem a banda corrigida de B−9. A divergência agregada já aparece na ordem dos clusters, no índice 1, antes do bootstrap. O PASS numérico de G2c.2 não foi declarado.
