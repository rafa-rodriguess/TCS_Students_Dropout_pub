# G2c.2 R1 — resultados públicos

A execução aprovada correu no ramo `a8/g2c2-reproducao-independente`, no PR #7 em draft, sem merge. Os escores e os modelos ficaram fora do Git. Este documento só traz agregados.

## R1.0

Os gates estruturais passaram antes do ajuste: 22 apresentações, 32593 matrículas, split 22855/9738, sobreposição de alunos 0, Fail9 = 9 com sinais 2/6/1 e split 7/2. O painel B tem 928604 linhas e o painel A 775295, diferença 153309. O teste B tem 278056 linhas e o teste B−9 tem 277979. Excluir Fail9 retira 348 linhas pessoa-semana, das quais 77 estão no teste. R18 fica em 6369 / 7337 / 7335. A saída do comando foi `structural PASS mismatches 0 removed 348 removed_test 77`.

## R1.1

Os três braços foram ajustados em separado com `LogisticRegression(liblinear, C=1, max_iter=4000, class_weight=balanced, random_state=42)`, `StandardScaler`, `OneHotEncoder` e `CalibratedClassifierCV(method=sigmoid, ensemble=False)` em `GroupKFold` de 5 folds por `id_student`, só no treino. Não houve busca de hiperparâmetros.

O marco A reproduz as contagens congeladas: 576 casos, 6275 controles e 435 excluídos. `G(18)` de A é 0.9398387446094816. B e B−9 não usam essa trava. Nenhum braço teve `G(18) < 0.05`.

As 99 células estão em `baselines/a8_g2c2_pub_metrics.csv`: 91 calculadas e 8 `UNAVAILABLE`, sem valor. Os 12 contrastes, com média de 500 draws, percentis 2.5/97.5, semente 42 e cluster por `id_student`, estão em `baselines/a8_g2c2_pub_bootstrap.csv`. O modelo desses contrastes é o já ajustado. R18 é ex-post, não uma política prospectiva.

## Decisão numérica

A reprodução numérica fica em STOP. Três valores de B−9 ultrapassam a tolerância predefinida de `1e-9`, e os intervalos do marco não reproduzem os extremos congelados. A comparação está em `docs/a8_g2c2_comparacao_dev_pub.md`. Os números públicos não foram alterados para forçar PASS. `publication_status` e o PASS numérico de G2c.2 continuam bloqueados.
