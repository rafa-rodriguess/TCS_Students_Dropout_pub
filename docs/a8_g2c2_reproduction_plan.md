# G2c.2 — plano de reprodução numérica

Este plano não contém resultados. A comparação com `baselines/a8_g2c2_dev_targets.csv` e `baselines/a8_g2c2_bootstrap_targets.csv` só pode ocorrer depois de uma R1 autorizada. Esses arquivos são alvos congelados. Não entram no ajuste nem na escolha de coeficientes.

O comando opcional é `g2c2_reproduction.py`. Ele não substitui `orquestrator.py`. Em R0 aceita `--plan` e `--preflight` e recusa `--fit` e `--allow-download`. Qualquer saída real precisa de um diretório fora do checkout.

## Etapas futuras

00. Conferir Python 3.14.3 e os pins numpy 2.4.4, pandas 2.3.3, scikit-learn 1.8.0 e joblib 1.5.3.
01. Usar o ZIP oficial da UCI já identificado no protocolo, ou o extrato cuja integridade tenha sido registrada. Não usar espelho nem arquivo de outro repositório.
02. Repetir o gate de hash. Hash bruto igual ao protocolo é PASS_RAW. Equivalência semântica só nas colunas já publicadas, só em memória. courses.csv, vle.csv e o ZIP permanecem PENDING enquanto o protocolo não tiver hash.
03. Braço A: relógio histórico até o último VLE, semana zero inclusive, evento apenas para Withdrawn com data não negativa. Preservar o runner 00–10 como linha de base A6, sem misturar a grade B no resultado antigo.
04. Braço B: Pass, Fail e Distinction sem evento seguem até `floor(module_presentation_length/7)`, inclusive a semana parcial. Semana sem registro recebe clique zero e `absent_record`. Observação real além da semana nominal permanece. Withdrawn sem evento V6 não é estendido até a semana nominal.
05. Braço B−9: mesmas regras, depois de excluir exatamente as matrículas da máscara explícita. Sem a máscara confirmada pela orquestradora, a etapa para.
06. Lag `t−1` para cliques, recência, sequência e submissão. A matriz X usa a whitelist numérica e categórica da família P2. Ficam de fora `final_result`, `date_unregistration`, `date_registration`, `event` e os atributos da própria semana.
07. Especificação, ainda sem executar neste R0: `LogisticRegression(liblinear, C=1, max_iter=4000, class_weight=balanced, random_state=42)` e `CalibratedClassifierCV(method=sigmoid, ensemble=False)` com os splits reais de `GroupKFold(n_splits=5)` por `id_student`. Nenhum índice de teste entra no treino. É proibido substituir isso por `cv=5`.
08. Indicadores semanais na própria grade: AUC, Brier e ECE15. Suporte comum só onde o alvo não está UNAVAILABLE.
09. Landmark L8–T18: risco `h(9)` no fechamento da semana 8; casos com evento nas semanas 9–18; controles observados depois de 18 sem evento antes de 18; censurados antes de 18 não são controles. `G` sai só do treino. IPCW usa `G(t_event)` nos casos e `G(18)` nos controles. Sem identificação ou positividade, a célula correspondente para.
10. R18 é a população de teste que tem linha na semana 18. Ela difere entre braços e não representa elegibilidade de uma política. Choque `delta=0.08` em `s*+1` e `s*+2` quando `r*=1`. Mecanismo `alpha_first=0.35` e `alpha_second=0.10` em `s*+2` e `s*+3`, em quatro features defasadas, sem alterar a hazard da semana da ação.
11. Bootstrap de 500 draws por `id_student`, seed 42, estimador fixo, mesma população e o mesmo relógio para o ponto e o intervalo. A curva individual e a média em coorte fixa precisam ser não crescentes. A média sobre a composição que muda a cada semana leva outro rótulo. ΔS não é eficácia causal e o intervalo do gap não é equidade validada.
12. Comparar status, denominador, N, valor e intervalo. Inteiros exatos. Demais números na tolerância declarada; a referência pré-fixada é `1e-9` quando algoritmo e versões coincidem. Divergência encerra a rodada. Não se altera meta, baseline A6 nem hiperparâmetro para obter PASS.

## Entradas e saídas

Entradas da R1: os sete CSV oficiais e os dois catálogos agregados deste branch, lidos só na comparação final. Saídas: agregados, hashes de entrada e saída, e o log das etapas, em diretório novo fora do checkout e fora do diretório da orquestração. Não saem matrícula, escore individual, modelo serializado nem CSV bruto.

Contagens que a R1 deve conferir, sem gravá-las agora como resultado: coorte 32.593; split 22.855/9.738; A com 232.509 pessoa-semanas de teste e R18 6.369; B com 278.056 e R18 7.337; B−9 com 277.979 pessoa-semanas, 9.736 matrículas de teste e R18 7.335.

## O que este R0 já deixou executável

`src/jla/g2c2.py` constrói o relógio, a ausência, o lag e a especificação. `g2c2_reproduction.py --plan` lista as etapas. Os testes sintéticos não usam OULAD real. Não há métrica nova neste documento.
