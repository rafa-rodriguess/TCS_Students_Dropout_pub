# Validação ponta a ponta com modelo congelado

O preflight parou antes da inferência. `score_arm` ajusta o modelo na hora e grava somente `private/{A,B,B-9}/test_scores.csv`. Não há `joblib.dump` dos três braços de G2c.2.

A saída privada da R1 contém, em cada braço, apenas esse CSV de escores. Não há modelo serializado de A, de B nem de B−9. As saídas anteriores do fluxo A6 têm um único `models/hazard.joblib`. Esse arquivo não identifica os três modelos da R1 e não foi carregado.

Nenhum braço tem modelo congelado utilizável. O código é `FROZEN_R1_MODELS_UNAVAILABLE`.

Não houve `fit_one`, `predict_proba`, download nem modelo substituto. `evaluate_landmark` não foi reexecutado sobre o OULAD nesta rodada. Os CSV v2, as baselines e `science.py` permanecem como estavam. O PASS E2E não foi declarado.
