# ia_orquestrator

Comunicação persistente, assíncrona e rastreável entre uma LLM orquestradora e uma LLM executora, usando GitHub Issues e comentários. Independente de domínio. Uma instalação opera N projectos.

- Software: `ia-orchestrator` **0.1.5**
- Protocolo: **v1** (`<!-- ia-orchestrator:message:v1 -->`)
- Pacote Python: `ia_orchestrator` (CLI `ia-orchestrator`)
- Dados privados: `$IA_ORCHESTRATOR_HOME` (omissão: `~/.ia_orchestrator`)
- Util integration version: **3.08**

Este diretório é o pacote candidato `orchestration/ia_orquestrator`. Não é o runner científico `orquestrator.py` e não treina modelos. A repo `rafa-rodriguess/TCS_Students_Dropout_pub` já contém o runner no commit `ff99bbcb30f53bac0e3e7d1f2720a682a5620f51`, ramo `reproduction_candidate`. Este pacote ainda não foi copiado para lá.

## O que isto não é

- Não automatiza cliques nem herda a sessão do chat **via API** da interface.
- O modo **chat aberto** (opcional) usa o wake local do Cursor (`notify_on_output`) **nesta** conversa; não é Cloud Agent nem um segundo chat. Ver [docs/CURSOR_CHAT_LOOP.md](docs/CURSOR_CHAT_LOOP.md).
- Não é uma fila transaccional do GitHub. A fiabilidade está na outbox/inbox SQLite local.
- SQLite e locks são **por host**. Não há eleição distribuída nem exactly-once para comandos externos.
- Labels do GitHub: filtro de sync (`ia-orchestrator`) e **status visível** da executora (`status:claimed` / `running` / `waiting-orchestrator` / `completed`). A orquestradora fecha a issue ao publicar `complete`.
- Alertas Discord não vêm neste pacote. `alerts.enabled` nasce falso. Sem `discord_msg` instalado à parte, o envio falha em silêncio e o GitHub continua a ser o canal.
- Envelope recusado (hash, protocolo, política) fica em quarentena na SQLite **e** gera um comentário visível na issue (`Quarentena (não executável)`). Esse aviso não é executável.

## Terceiro papel (3.04): agente de discussão em paralelo

O agente é uma terceira sessão Cursor local **exclusivamente de leitura**, separada do worker executor. Pode analisar enquanto a executora opera e devolver um **parecer**, sem alterar o estado da execução.

- Orquestradora: `discuss` → destinatário `agent` na **issue atual**, `request_id` próprio.
- Agente: `analysis` (ou `question`) → `orchestrator` com `in_reply_to` ao `discuss`.
- Configurar `github.allowed_senders.agent` e iniciar `loop arm --role agent` **num chat/host próprio**. `worker run --role agent` apenas sincroniza.
- A fila usa `agent_discussions/` e sentinela `AGENT_LOOP_TICK_agent`, sem tocar `running/` da executora, sem emitir `ack`, `result` ou `complete`.

`INSTRUCOES_LLM_AGENTE.md` contém o contrato operacional, inclusive os limites de independência e a proibição de alterações no workspace de tarefa. O protocolo de envelope continua v1; o runtime corrente é 3.08.

## `send-file` (3.06)

A orquestradora coloca o arquivo numa pasta pública do Google Drive e a executora baixa esse link. Não há servidor local.

```bash
ia-orchestrator send-file --project EXEMPLO --role orchestrator --folder-link 'https://drive.google.com/drive/folders/ID?usp=sharing'
ia-orchestrator send-file --project EXEMPLO --role orchestrator --task TASK_ID --file ./artigo.pdf --drive-url 'https://drive.google.com/file/d/ID/view?usp=sharing' --wait
```

A primeira utilização grava o link da pasta. O arquivo conferido por SHA-256 fica em `transfered_files/`. `--push` é opcional e default false. Depois do `result` de sucesso, a orquestradora apaga o arquivo da pasta. Aliases: `send_file` e `send file`.

## `get-file` (3.08)

A orquestradora pede um URL https. A executora resolve o arquivo para um diretório temporário, envia-o à mesma pasta pública e responde com o nome, o link, o SHA-256, o tamanho e o protocolo usado. Se o arquivo está no repositório do projeto, a leitura é pelo Git, com preferência sobre HTTP. A orquestradora baixa essa cópia e a apaga.

```bash
ia-orchestrator get-file --project EXEMPLO --role orchestrator --task TASK_ID --url 'https://example.com/artigo.pdf' --wait
```

O envio ao Drive usa `IA_ORCHESTRATOR_DRIVE_TOKEN` ou `~/.ia_orchestrator/drive_token`. A verificação TLS permanece ligada. Aliases: `get_file` e `get file`.

## Instalação

Python ≥ 3.11.

```bash
cd orchestration/ia_orquestrator
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e .
.venv/bin/pip install pytest==8.4.2
```

## Segunda executora

Use um home, uma SQLite e um workspace só desta executora. Não reutilize o home do projeto privado.

```bash
export IA_ORCHESTRATOR_HOME="$HOME/.ia_orchestrator_tcs_pub"
ia-orchestrator bootstrap \
  --project TCS_PUB \
  --repo rafa-rodriguess/TCS_Students_Dropout_pub \
  --workspace /caminho/do/clone/TCS_Students_Dropout_pub \
  --token-env GITHUB_TOKEN_TCS_PUB
```

`TCS_PUB` é a proposta de project id. Confirme com `project show` antes de a tratar como definitiva. O token nomeado por `GITHUB_TOKEN_TCS_PUB` fica só no ambiente local, com escopo de repositório público, e não entra no git. Edite `allowed_senders` no YAML gerado com as contas desta executora, não com as do projeto privado. Sem `--probe`, `doctor` não chama a rede.

```bash
ia-orchestrator project show --project TCS_PUB
ia-orchestrator doctor --project TCS_PUB
ia-orchestrator loop arm --help
ia-orchestrator pending --help
ia-orchestrator execution deliver --help
```

## Cadastrar um projecto (sem ligar workers)

O repositório **nunca** é inferido do cwd. `--project` e `--repo owner/repo` são obrigatórios.

```bash
export IA_ORCHESTRATOR_HOME="$HOME/.ia_orchestrator"
ia-orchestrator bootstrap --project exemplo --repo organizacao/repositorio --workspace /caminho/local
ia-orchestrator project list
ia-orchestrator project show --project exemplo
```

Edite `allowed_senders` no YAML gerado. Exporte o token referenciado por `github.token_env`. Não versione `.env`.

```bash
ia-orchestrator doctor --project exemplo
ia-orchestrator doctor --project exemplo --probe   # GET /user e GET /repos; não chama modelos pagos
```

## Fluxo manual (humano no chat + CLI)

```bash
ia-orchestrator task create --project exemplo --prompt-file /caminho/prompt.md
ia-orchestrator worker run --project exemplo --role orchestrator --once
ia-orchestrator worker run --project exemplo --role executor --once
ia-orchestrator task show --project exemplo --task TASK_ID
ia-orchestrator task export --project exemplo --task TASK_ID --output /tmp/historico.md
```

`--dry-run` não publica, não executa subprocessos de trabalho e não chama modelos pagos.

## Três formas de execução contínua (escolha uma por papel)

1. **Headless Python** — o processo `worker run` chama o modelo HTTP e/ou o subprocesso. Foreground ou os exemplos em `examples/macos/` e `examples/linux/` (não se instalam sozinhos).

```bash
ia-orchestrator worker run --project exemplo --role orchestrator
ia-orchestrator worker run --project exemplo --role executor
```

Ctrl+C preserva checkpoints e outbox. Enquanto o worker corre em contínuo (sem `--once`), o processo lança `keep_awake` à parte (`caffeinate` no macOS) e termina-o ao sair. O poller do chat aberto faz o mesmo. Na versão util **3.03**, o guard do macOS mantém `display`, `idle sleep` e `user active` durante toda a vida do monitor, evitando lock automático/tela de login por inatividade; lock manual e políticas MDM ficam fora do escopo.

2. **Pull/manual** — ferramentas sem CLI de execução; o humano (ou uma LLM pontual) cola:

```bash
ia-orchestrator pending --project exemplo --role executor
ia-orchestrator execution start --project exemplo --task TASK_ID --request REQUEST_ID
ia-orchestrator execution deliver --project exemplo --task TASK_ID --request REQUEST_ID --result-file out.json
```

Observabilidade da orquestradora:

```bash
ia-orchestrator check --project exemplo --task TASK_ID
ia-orchestrator status --project exemplo --task TASK_ID

ia-orchestrator message post \
  --project exemplo \
  --task TASK_ID \
  --type non_blocking \
  --recipient executor \
  --request-id NOVO_UUID \
  --body-file controle.md \
  --sender-role orchestrator
```

`check` apenas sincroniza/inspeciona e não envia trabalho. `status` publica o `non_blocking` de telemetria com corpo fixo, na mesma task/issue, e devolve o `request_id` na hora. Só publica se a issue tiver o label `status:running`. Outra inspeção side-band continua a ser um `message post --type non_blocking`. A executora faz o preflight de não interferência e responde por `control_result` assim que a leitura termina.

3. **Chat aberto (Cursor IDE local)** — poller burro neste terminal acorda **esta** conversa; a LLM executa o job. O bash **não** processa o trabalho. YAML: `executor.mode: cursor_chat`. Armar:

```bash
ia-orchestrator loop arm --project exemplo --role executor
```

Use o `command` impresso com `block_until_ms: 0` e `notify_on_output.pattern: AGENT_LOOP_TICK_executor`. Contrato: [docs/CURSOR_CHAT_LOOP.md](docs/CURSOR_CHAT_LOOP.md). Se o chat fechar, não há executor neste modo. Não combine com `worker run` contínuo no mesmo papel/projecto.

Durante uma execução longa (`RECOVERY_REQUIRED`), o poller continua sincronizando GitHub a cada 10 s. Uma segunda `request` normal não é executada em paralelo; os únicos comandos concorrentes são `non_blocking` (após preflight de isolamento) e `programmed_stop` (parada imediata/condicional). Ambos usam novo `request_id` no mesmo `task_id`/issue e retornam `control_result` sem substituir o resultado primário.

Jobs `cursor_chat` podem atravessar vários turnos da mesma conversa. O dedup de `RECOVERY_REQUIRED` é silencioso enquanto o estado não muda; portanto, antes de ceder intencionalmente um turno com trabalho ainda saudável e incompleto, a executora deve persistir checkpoint e executar **como última acção** `ia-orchestrator loop rearm --project <id> --role executor`. Esse comando apenas apaga o marcador de wake; o próximo poll de background re-acorda o mesmo `running/*.md`. `status:running` não é prova de cálculo activo.

## Demonstração offline (sem credenciais)

```bash
ia-orchestrator demo offline --output /tmp/ia-orch-demo
python3 -m pytest tests -q
```

## Smoke test real

Só com repositório e token **autorizados pelo utilizador**. Não inventamos repositório.

```bash
export GITHUB_TOKEN_EXEMPLO=...   # nome = github.token_env da config
ia-orchestrator task create --project exemplo --prompt-file prompt.md
ia-orchestrator worker run --project exemplo --role orchestrator --once
ia-orchestrator worker run --project exemplo --role executor --once
```

## Códigos de saída

| Código | Significado |
| --- | --- |
| 0 | sucesso |
| 1 | erro genérico |
| 2 | uso incorrecto |
| 3 | autenticação |
| 4 | não encontrado |
| 5 | lock |
| 6 | protocolo |
| 7 | política |
| 8 | rede |
| 9 | limite |

## Documentação

- [INSTRUCOES_LLM_ORQUESTRADORA.md](INSTRUCOES_LLM_ORQUESTRADORA.md)
- [INSTRUCOES_LLM_EXECUTORA.md](INSTRUCOES_LLM_EXECUTORA.md)
- [INSTRUCOES_LLM_AGENTE.md](INSTRUCOES_LLM_AGENTE.md) — discussão e análise em paralelo; não executa nem ordena
- [docs/SOURCE_OF_TRUTH.md](docs/SOURCE_OF_TRUTH.md)
- [docs/CURSOR_CHAT_LOOP.md](docs/CURSOR_CHAT_LOOP.md) — poller + execução no chat aberto
- [docs/PROMPT_IMPLEMENTACAO.md](docs/PROMPT_IMPLEMENTACAO.md)
- [examples/config.example.yaml](examples/config.example.yaml)
- Contrato do executor: `examples/simulated_executor.py` (stdin/stdout JSON, sem `shell=True`)

## Segurança

Tokens só em variáveis de ambiente. O subprocesso da executora **não** herda `GITHUB_TOKEN*` nem chaves de modelo. `allow_push` default true; `allow_merge` e `allow_deploy` default false. Sem force push. Isto não é sandbox de SO: se o executor tiver acesso amplo ao host, documente-o no projecto consumidor.
