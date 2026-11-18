# Runner JLA (candidato preparado)

Este diretório é um candidato preparado para auditoria de exportação. A repo `rafa-rodriguess/TCS_Students_Dropout_pub` existe, está pública, usa `main` e continua vazia. Não contém este pacote e não houve reprodução. Nenhum código foi transferido para lá. O código científico-base auditado é o commit `92d242688b468d610b688192a1707c92dd6669c5` da repo privada de desenvolvimento. As correções desta rodada ainda aguardam conferência.

A licença deste código é MIT, no arquivo `LICENSE`. A linha de copyright usa a conta GitHub `rafa-rodriguess`, dona verificável da repo de desenvolvimento. A titularidade entre os autores do manuscrito não está decidida aqui e fica pendente para a orquestradora. A licença CC BY 4.0 não cobre estes scripts.

## Dados

Os dados vêm do UCI Machine Learning Repository, dataset 349:

`https://archive.ics.uci.edu/static/public/349/open+university+learning+analytics+dataset.zip`

Catálogo: `https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset`.

Licença do conjunto: CC BY 4.0. Atribuição obrigatória: Kuzilek, Hlosta e Zdrahal, Open University Learning Analytics Dataset. Os CSV não entram no git. O download só existe com `--allow-download` e não foi executado nesta preparação.

Cinco hashes de CSV estão congelados em `config/protocol.yaml`. Os hashes de `courses.csv`, `vle.csv` e do ZIP continuam vazios, com status PENDING. Não inventar esses valores.

## Ambiente

O `requirements.lock` registra o host em que o P2 foi feito: Python 3.14.3, NumPy 2.4.4, pandas 2.3.3, scikit-learn 1.8.0, joblib 1.5.3. Isso não foi validado num venv limpo. Outra pilha é instalação bloqueada, não uma tolerância maior.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-test.txt
python3 -m pytest tests -q
python orquestrator.py --help
python orquestrator.py --plan
```

`requirements-test.txt` traz só o pytest e não muda o lock científico. A instalação do lock num venv limpo ainda não foi provada.

`--help` e `--plan` não escrevem resultados. `pytest` usa só fixtures. Nenhum desses comandos baixa o OULAD nem ajusta o modelo.

## Saída

Executar exige `--output-dir` apontando para uma pasta fora deste checkout e fora da repo de desenvolvimento. A raiz do código não é destino. Uma pasta que já tenha `data/`, `models/`, `results/`, `figures/`, `logs/` ou `checkpoints/` não é reaproveitada, salvo `--resume` com `checkpoints/state.json` cujo fingerprint coincide com o código e que tenha ao menos uma etapa PASS. O resume não apaga o diretório.

A etapa 03 grava `person_period.csv`. A etapa 04 grava `person_period_split.csv`. A etapa 05 lê o segundo arquivo.

`--compare-baseline` sozinho lê saídas já gravadas e não percorre as etapas 00–09. Também exige `--output-dir` fora do checkout.

`PASS_MOCK` exercita a interface e não é o estudo. `PASS_EDITORIAL` escreve a matriz e não é reprodução. `PASS_REPRODUCTION` exige checkpoints PASS das etapas 00–09, tokens válidos e A4 REAL. Hashes PENDING e o float `A CONFIRMAR` do ΔGap do choque mantêm `publication_status` em BLOCKED.

## Exemplo não executado

O comando abaixo é só um exemplo. Não foi executado e depende de autorização posterior. Não o rode nesta preparação.

```bash
python orquestrator.py --all --allow-download --output-dir /caminho/fora/do/checkout
```

## Se algo falhar

- Sem `--output-dir`, ou com destino dentro do checkout, a execução para antes das etapas.
- Pasta ocupada sem `--resume` válido: escolher um diretório novo. Não apagar um checkpoint à mão para forçar PASS.
- Fingerprint diferente: o diretório antigo permanece. Usar outro diretório ou a mesma revisão de código.
- Hash divergente: o protocolo não é reescrito. A etapa 02 falha.
- Para desfazer uma saída local, apagar só o diretório passado em `--output-dir`. O código versionado não guarda CSV, `joblib` nem `results/`.
