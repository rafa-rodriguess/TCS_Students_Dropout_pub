# Manifesto da execução G2c.2 R1

O extrato oficial tem sete CSV e o ZIP. Os hashes abaixo são os observados nesta execução. `courses.csv`, `vle.csv` e o ZIP continuam PENDING no protocolo e não bloqueiam a ciência. Não se inventou hash bruto histórico para esses três.

| Arquivo | SHA-256 observado | Gate |
| --- | --- | --- |
| `studentInfo.csv` | `815fbc3e2de29f79900bc63f0345a35db62c9146afaa1d86e7107b8b3beffc60` | PASS semântico |
| `studentRegistration.csv` | `bbc87a0de1fe2a9ec6decce1ca6c1a02cf17b54ad3bdcc673fc6413b41c61d47` | PASS semântico |
| `studentVle.csv` | `52668253d876c5becbcb72185977152700cecab2942aca807fecc3dd54b937f0` | PASS bruto |
| `studentAssessment.csv` | `b1839e17618a5de36b6d189a242d3123f7939a56c8c9ccef0c17b9199c614a6b` | PASS semântico |
| `assessments.csv` | `9ce92381e4a0ac457f8e251b2eb2c179ed51e023ab30d1d671a0268bd62316ba` | PASS semântico |
| `courses.csv` | `4f16eee7454b15e109b0a21a0e43be820e6846ed6f9301bb7feb5ab5ad737a75` | PENDING |
| `vle.csv` | `d7a146497edd0e47ef536144b58796c07b554002d3753e848b8e4cd8a56f4c38` | PENDING |
| `oulad.zip` | `f2ed1902616c1fe8d2824d872c0b7d2d72be435bf0124d077044fe4be2c6d3e4` | PENDING |

O split é o P1 histórico, calculado no relógio A com semente 42 e aplicado por `id_student` a B e B−9. A saída e os escores ficaram fora do checkout e fora do repositório.

O comando aprovado foi `g2c2_reproduction.py --run-approved`, com diretórios externos de dados e de saída. A saída foi 0. Antes do ajuste, o log registrou `structural PASS mismatches 0 removed 348 removed_test 77` e, em seguida, o início e o fim de A, B e B−9. `pytest tests -q` passou em 85 testes. O ambiente foi Python 3.14.3, numpy 2.4.4, pandas 2.3.3, scikit-learn 1.8.0, joblib 1.5.3 e pytest 8.4.2.

`orquestrator.py`, `config/protocol.yaml`, `baselines/aggregates.json`, `src/jla/science.py`, os estágios históricos e os dois CSV de alvo DEV não foram modificados.
