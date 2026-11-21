# Reexecução ponta a ponta com modelos gravados

A R7 ajustou de novo os braços A, B e B−9. Cada `fit_one` foi gravado com `joblib` antes dos escores e do marco. O arquivo foi recarregado e foi esse objeto, não o que estava só na memória, que seguiu para `evaluate_landmark`. O comando histórico `--fit` continua recusado.

O extrato foi o mesmo da R1. Os sete hashes conferidos permanecem os do manifesto, inclusive os três PENDING. O preflight estrutural passou com 348 linhas removidas, 77 no teste, e Fail9 igual a 9, com 7 no treino e 2 no teste. `PYTHONHASHSEED` não estava definido. O ambiente foi Python 3.14.3, numpy 2.4.4, pandas 2.3.3, scikit-learn 1.8.0 e joblib 1.5.3.

## Modelos novos

A saída privada da R7 tem um `model.joblib` por braço. A R1 continua sem modelo serializado. Os hashes abaixo são dos arquivos novos.

| Braço | SHA-256 | Bytes | Diferença após o reload | Chamadas de `predict_proba` | Gap do marco |
| --- | --- | --- | --- | --- | --- |
| A | `49d3f2c519cb58700ca8049db7cd1b9319492085657f17ba58db487859729208` | 21719263 | 0 | 4 | 0 |
| B | `cc19fb6d76324050ae4add024a42e6c4353f7b5560627206734b0b9f9aa52cb7` | 26029775 | 0 | 4 | 0 |
| B−9 | `12ea89575db24cc877d015c58fe18b7003b20e3b494fb6f22d2b7dfcfe0d3a7e` | 26018927 | 0 | 4 | 0 |

O hash foi relido depois do marco e não mudou. A matriz de teste e uma linha da semana 9 foram previstas de novo a partir do arquivo, com diferença 0. O gap entre o fechamento da semana 8 e a linha 9 foi 0, abaixo de 1e-10. Matrículas em risco sem linha 9 conferida: 164 em A, 5 em B e 5 em B−9.

## Gates

Os escores novos coincidem com os da R1 nas mesmas matrículas e semanas: 232509, 278056 e 277979 linhas, diferença máxima 0. Os 91 pontos computáveis ficam a no máximo 1e-9 dos alvos v2, e os 8 `UNAVAILABLE` seguem vazios. Os seis intervalos de AUC têm os doze extremos dentro de 1e-9. As seis impressões de ordem coincidem. Os doze contrastes de política, com 500 draws e semente 42, também ficam dentro de 1e-9. Há 500 draws válidos em cada intervalo.

Os clusters são 6256, 7165 e 7164. Casos, controles e excluídos são 576/6275/435, 576/7283/6 e 576/7281/6. Em B−9, `G(18)`, a AUC IPCW e os dois ESS permanecem nos valores v2.

`src/jla/science.py` e `src/jla/landmark.py` não foram editados. Os CSV da R1 e os alvos v2 também não. Nenhum modelo, escore ou identificador entrou no Git.

## Decisão

`PASS_E2E_R7`. O teste sintético mostra que `evaluate_landmark` recebe o modelo recarregado e que o caminho antigo não grava `model.joblib`. Esta decisão não é o aceite autoral de G2c.2 nem autoriza merge.
