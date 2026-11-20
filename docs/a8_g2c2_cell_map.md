# Mapa das 99 células

Noventa e uma células têm função. Oito permanecem UNAVAILABLE e não recebem valor inventado. Os números oficiais só existem depois de `--run-approved` passar os gates estruturais. Este mapa não copia os alvos congelados.

| Indicador | Fonte | Denominador | Braços |
| --- | --- | --- | --- |
| n_teste | matrículas de teste do split P1 | matrícula | A, B, B−9 |
| n_linhas_teste | linhas do painel de teste | linha | A, B, B−9 |
| n_eventos_teste | `event == 1` no teste | linha de evento | A, B, B−9 |
| auc_semanal | `clustered_auc` no teste | linha de teste | A, B, B−9 |
| brier | Brier no teste | linha de teste | A, B, B−9 |
| ece15 | `ece15` no teste | linha de teste | A, B, B−9 |
| suporte_comum_linhas | interseção de linhas de teste A×B | linha comum | A, B; B−9 UNAVAILABLE |
| auc_suporte_comum | AUC nessa interseção | linha comum | A, B; B−9 UNAVAILABLE |
| brier_suporte_comum | Brier nessa interseção | linha comum | A, B; B−9 UNAVAILABLE |
| landmark_em_risco | casos + controles do marco | matrícula | A, B, B−9 |
| landmark_casos | evento nas semanas 9–18 | matrícula | A, B, B−9 |
| landmark_controles | observado além de 18 sem evento até 18 | matrícula | A, B, B−9 |
| landmark_excluidos | censura precoce | matrícula | A, B, B−9 |
| auc_landmark | AUC sem peso no marco | caso e controle | A, B, B−9 |
| auc_ipcw | AUC com `G` de treino | caso e controle | A, B, B−9; NO-GO se `G(18)<0.05` |
| G18 | `censoring_g` no treino em risco | treino em risco na semana 8 | A, B, B−9 |
| ess_casos / ess_controles | `ess` dos pesos IPCW | caso / controle | A, B, B−9 |
| r18 | teste com linha na semana 18 | matrícula | A, B, B−9 |
| gatilho_r18 | R18 com janela de choque | R18 do braço | A, B, B−9 |
| resposta_r18 | R18 com resposta do mecanismo | R18 do braço | A, B, B−9 |
| delta_s_choque / delta_s_mecanismo | média de `S(18)` cenário−base | R18 do braço | A, B, B−9 |
| gap_basal / gap_choque / gap_mecanismo | média F−M de `S(18)` | R18 do braço | A, B, B−9 |
| delta_gap_choque / delta_gap_mecanismo | diferença dos gaps | R18 do braço | A, B, B−9 |
| linhas_sem_registro | semana sem VLE e sem submissão | linha | B, B−9; A UNAVAILABLE |
| clique_zero | registro de VLE com soma zero | linha | B, B−9; A UNAVAILABLE |
| semana_nominal_parcial | última semana administrativa incompleta | linha | B, B−9; A UNAVAILABLE |
| gatilho_f / gatilho_m | não separados no resumo congelado | — | A UNAVAILABLE; B e B−9 ainda sem valor nesta R1 se o resumo não os separar |

Os 12 contrastes de bootstrap usam `bootstrap` com 500 draws, seed 42, cluster por `id_student` e hazards já calculados. O ensaio sintético está em `fixed_hazard_contrasts`. A execução real grava só agregados.
