# G2c.2 R2 — preflight corretivo sem ajuste real

Decisão do preflight: **GO**. Decisão da execução real: **STOP** até a orquestradora emitir R1. Este código não autoriza PASS G2c.2 e não reutiliza o PASS numérico da A6.

- `r2_preflight`: GO
- `r1_execution`: NO-GO
- `g2c2_numeric_pass`: NO-GO

## O que a A6 já cobre e o que não cobre

O runner histórico `orquestrator.py` etapas 00–10 permanece o caminho A. Ele já tem a família logística pedida: liblinear, C=1, `max_iter=4000`, `class_weight=balanced`, `random_state=42`, calibração sigmoide com `ensemble=False` e `GroupKFold(n_splits=5)` recebendo splits por `id_student`. Também já tem lag `t−1`, whitelist P2, `delta=0.08`, `alpha_first=0.35` e `alpha_second=0.10`.

Esse runner corta o acompanhamento no último VLE, ou na semana do evento quando o desfecho é Withdrawn com data não negativa. Não abre a semana nominal `floor(module_presentation_length/7)`, não marca semana sem registro, não separa B de B−9 e não produz as 99 células nem os 12 contrastes do contrato novo. Um PASS da A6 não é PASS G2c.2.

## Checklist B01–B16

A especificação pública está em `docs/a8_g2c2_b01_b16_public.md`. `contract_checklist()` devolve as 16 cláusulas. Três ficam em LIMITAÇÃO porque a contagem oficial ainda não rodou. Nenhuma está em STOP.

| Código | Status | Prova |
| --- | --- | --- |
| B01 | PASS | A e B têm relógios separados e a especificação não lê escores externos |
| B02 | PASS | Evento só para Withdrawn com data não negativa |
| B03 | LIMITAÇÃO | O split sintético não mistura estudante; 32.593 / 22.855 / 9.738 ficam para R1 |
| B04 | PASS | `t_final_week` administrativo é `floor(length/7)` mesmo com atividade posterior |
| B05 | LIMITAÇÃO | `fail9_mask` está implementado; as contagens 9, 348 e 77 não foram medidas |
| B06 | PASS | Withdrawn sem evento V6 termina no último VLE |
| B07 | PASS | A grade inclui a semana zero e não corrige entrada tardia |
| B08 | PASS | A semana nominal parcial é marcada e não vira inferência por dia |
| B09 | PASS | X não contém desfecho, datas nem estado da própria semana |
| B10 | PASS | A família logística e os splits por estudante estão fixos |
| B11 | PASS | O ensaio sintético calcula AUC, Brier, ECE15 e suporte comum |
| B12 | PASS | Landmark, G, IPCW e ESS rodam no ensaio; `G(18)<0.05` devolve NO-GO |
| B13 | LIMITAÇÃO | Choque, mecanismo e R18 rodam no ensaio; 6.369 / 7.337 / 7.335 não foram estimados |
| B14 | PASS | A média em coorte fixa é não crescente; o bootstrap tem 500 draws e escore fixo |
| B15 | LIMITAÇÃO | Os catálogos contam 99 e 12; nenhum valor oficial foi produzido |
| B16 | PASS | Alvo e modelo não mudam depois do escore; divergência futura é STOP |

Atividade VLE ou submissão depois da semana nominal permanece no registro bruto e entra só na métrica diagnóstica `post_nominal_diagnosis`. Ela não abre linha de risco.

## Oito UNAVAILABLE já fechadas

Não são lacunas de implementação. O resumo congelado as deixa vazias:

- A: `linhas_sem_registro`, `clique_zero`, `semana_nominal_parcial`, `gatilho_f`, `gatilho_m`
- B−9: `suporte_comum_linhas`, `auc_suporte_comum`, `brier_suporte_comum`

## Inventário do extrato oficial já isolado

Não houve download nesta R2 e nenhuma métrica OULAD foi estimada. O extrato previamente obtido da UCI tem os sete CSV e o ZIP. `courses.csv` traz `module_presentation_length` e 22 apresentações, com comprimentos inteiros. O hash abaixo é o sha256 observado do arquivo. Onde ele difere do protocolo, o gate continua sendo a equivalência semântica já publicada; o hash bruto histórico não foi substituído. courses.csv, vle.csv e o ZIP não têm hash no protocolo e permanecem PENDING. Esse PENDING não impede a reprodução científica.

| Arquivo | sha256 observado | Gate |
| --- | --- | --- |
| studentInfo.csv | `815fbc3e2de29f79900bc63f0345a35db62c9146afaa1d86e7107b8b3beffc60` | PASS semântico; bruto diferente do protocolo |
| studentRegistration.csv | `bbc87a0de1fe2a9ec6decce1ca6c1a02cf17b54ad3bdcc673fc6413b41c61d47` | PASS semântico; bruto diferente do protocolo |
| studentVle.csv | `52668253d876c5becbcb72185977152700cecab2942aca807fecc3dd54b937f0` | PASS_RAW |
| studentAssessment.csv | `b1839e17618a5de36b6d189a242d3123f7939a56c8c9ccef0c17b9199c614a6b` | PASS semântico; bruto diferente do protocolo |
| assessments.csv | `9ce92381e4a0ac457f8e251b2eb2c179ed51e023ab30d1d671a0268bd62316ba` | PASS semântico; bruto diferente do protocolo |
| courses.csv | `4f16eee7454b15e109b0a21a0e43be820e6846ed6f9301bb7feb5ab5ad737a75` | PENDING |
| vle.csv | `d7a146497edd0e47ef536144b58796c07b554002d3753e848b8e4cd8a56f4c38` | PENDING |
| ZIP | `f2ed1902616c1fe8d2824d872c0b7d2d72be435bf0124d077044fe4be2c6d3e4` | PENDING, 46748244 bytes |

A equivalência troca `?` por vazio só na memória, nas colunas já publicadas, e não falsifica o hash bruto.

## Testes e ambiente

`python -m pytest tests -q`: 83 passed. Os testes novos são sintéticos: composição de matrícula, corte nominal estrito, atividade posterior só no diagnóstico, Fail9 com data negativa, zero, positiva e nula, exclusão por matrícula, semana silenciosa, lag, vazamento, splits, métricas em memória e recusa de `--fit`. Nenhum treino usa OULAD.

Ambiente do teste: Python 3.14.3, numpy 2.4.4, pandas 2.3.3, scikit-learn 1.8.0, joblib 1.5.3. Nenhum modelo foi ajustado.

## Custo previsto da R1, se a orquestradora a autorizar

Uma leitura do `studentVle.csv` já extraído, com cerca de 454 MB, mais a montagem da grade B, um ajuste logístico calibrado e 500 reamostragens por estudante com estimador fixo. Não há segundo ajuste dentro do bootstrap. O diretório de saída tem de ficar fora do checkout.

## O que ainda não autoriza R1

1. A execução real continua fechada até uma request R1.
2. As contagens oficiais dos nove Fail e das grades ainda não foram medidas. O predicado já está fixo: Fail com `date_unregistration` numérica não nula, inclusive negativa e zero. B−9 exclui a matrícula, não o estudante inteiro.
3. O catálogo conta 99 indicadores e 12 contrastes. O ensaio sintético calcula as famílias de métrica, mas nenhum valor oficial foi produzido.
4. courses.csv, vle.csv e o ZIP continuam PENDING. Isso não bloqueia a ciência.
5. Suporte comum, AUC e Brier de B−9 contra A permanecem UNAVAILABLE por definição do alvo.
