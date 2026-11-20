# G2c.2 R0 — preflight sem ajuste

Decisão: **STOP** para execução científica. O código isolado deste branch pode ser inspecionado. Ele não autoriza PASS G2c.2, não reutiliza o PASS numérico da A6 e não dispara R1.

- `r0_isolated_code`: GO
- `r1_execution`: NO-GO
- `g2c2_numeric_pass`: NO-GO

## O que a A6 já cobre e o que não cobre

O runner histórico `orquestrator.py` etapas 00–10 permanece o caminho A. Ele já tem a família logística pedida: liblinear, C=1, `max_iter=4000`, `class_weight=balanced`, `random_state=42`, calibração sigmoide com `ensemble=False` e `GroupKFold(n_splits=5)` recebendo splits por `id_student`. Também já tem lag `t−1`, whitelist P2, `delta=0.08`, `alpha_first=0.35` e `alpha_second=0.10`.

Esse runner corta o acompanhamento no último VLE, ou na semana do evento quando o desfecho é Withdrawn com data não negativa. Não abre a semana nominal `floor(module_presentation_length/7)`, não marca semana sem registro, não separa B de B−9 e não produz as 99 células nem os 12 contrastes do contrato novo. Um PASS da A6 não é PASS G2c.2.

## Checklist das cláusulas públicas

A lista numerada B01–B16 vive no repositório privado citado pelo contrato e não foi importada. O checklist abaixo é só o contrato público deste branch.

| Cláusula pública | Estado no R0 | Falta |
| --- | --- | --- |
| Sete CSV oficiais e chave de matrícula | Inventário do extrato já obtido, sem download novo | R1 precisa repetir o gate no diretório da própria execução |
| Relógio A até o último VLE, semana zero inclusive | Regras reaproveitadas e cobertas por teste sintético | Contagens 22.855/9.738 e 232.509 só depois do painel real |
| B estende Pass/Fail/Distinction sem evento até a semana nominal, inclusive parcial | Implementado em `src/jla/g2c2.py` | Confirmar contagens 278.056 e R18 7.337 só na R1 |
| Semanas sem registro ficam com clique zero e flag de ausência | Teste sintético | Não inventar atividade no arquivo real |
| VLE e submissão observados não são apagados | Se a última observação passa da semana nominal, o fim acompanha a observação | — |
| Withdrawn sem evento V6 permanece até o último VLE | Teste com data negativa | Não imputar data |
| Nove Fail com data conflitante | B aceita máscara explícita; B−9 recusa máscara ausente | Predicado de identificação não está no contrato público |
| Proibição de vazamento e lag `t−1` | Whitelist P2; `date_registration` também fica fora de X | — |
| GroupKFold por estudante, não `cv=5` | Especificação e teste de splits disjuntos, sem `fit` | — |
| Landmark L8–T18, IPCW, ESS, G só no treino | Regras descritas no plano; funções A6 existentes não foram religadas a B | Positividade e identificação só podem ser julgadas com dados |
| R18 ex-post, não causal e não política | Documentado; sem cálculo | Populações 6.369 / 7.337 / 7.335 só na R1 |
| 99 células e 12 contrastes | Catálogo conferido: 91 agendadas, 8 UNAVAILABLE, 12 contrastes de 500 draws | Nenhum valor foi calculado |
| Tolerância numérica `1e-9` se algoritmo e versões coincidirem | Regra de comparação escrita; sem resultado | Divergência futura é STOP, não ajuste de meta |

## Oito UNAVAILABLE já fechadas

Não são lacunas de implementação. O resumo congelado as deixa vazias:

- A: `linhas_sem_registro`, `clique_zero`, `semana_nominal_parcial`, `gatilho_f`, `gatilho_m`
- B−9: `suporte_comum_linhas`, `auc_suporte_comum`, `brier_suporte_comum`

## Inventário do extrato oficial já isolado

Não houve download neste R0 e nenhuma métrica foi estimada. O extrato previamente obtido da UCI tem os sete CSV e o ZIP. `courses.csv` traz `module_presentation_length` e 22 apresentações, com comprimentos inteiros.

| Arquivo | Gate neste extrato |
| --- | --- |
| studentInfo.csv | PASS por equivalência semântica; o hash bruto do protocolo não foi reescrito |
| studentRegistration.csv | PASS por equivalência semântica |
| studentVle.csv | PASS pelo hash bruto |
| studentAssessment.csv | PASS por equivalência semântica |
| assessments.csv | PASS por equivalência semântica |
| courses.csv | PENDING |
| vle.csv | PENDING |
| ZIP | PENDING, sha256 `f2ed1902616c1fe8d2824d872c0b7d2d72be435bf0124d077044fe4be2c6d3e4`, 46748244 bytes |

A equivalência troca `?` por vazio só na memória, nas colunas já publicadas, e não falsifica o hash bruto.

## Testes e ambiente

`python -m pytest tests -q`: 81 passed. Os testes novos são sintéticos: composição de matrícula, semana de evento, data negativa, semana silenciosa, linha nominal parcial, lag da semana anterior, vazamento, splits por estudante, recusa de B−9 sem máscara e recusa de `--fit`.

Ambiente do teste: Python 3.14.3, numpy 2.4.4, pandas 2.3.3, scikit-learn 1.8.0, joblib 1.5.3. Nenhum modelo foi ajustado.

## Custo previsto da R1, se a orquestradora a autorizar

Uma leitura do `studentVle.csv` já extraído, com cerca de 454 MB, mais a montagem da grade B, um ajuste logístico calibrado e 500 reamostragens por estudante com estimador fixo. Não há segundo ajuste dentro do bootstrap. O diretório de saída tem de ficar fora do checkout.

## Obstáculos que mantêm o STOP

1. O contrato público não define como reconhecer os nove Fail com data de saída conflitante. B−9 não tenta adivinhar.
2. B01–B16 não estão neste repositório.
3. courses.csv, vle.csv e o ZIP continuam PENDING.
4. Suporte comum, AUC e Brier de B−9 contra A permanecem UNAVAILABLE por definição do alvo.
