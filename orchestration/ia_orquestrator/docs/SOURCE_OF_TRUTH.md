# Fonte de verdade — ia_orquestrator

Distinta da fonte de verdade de cada projecto consumidor. Não reformatar SoT dos consumidores.

| Campo | Valor |
| --- | --- |
| Software | ia-orchestrator 0.1.5 |
| Protocolo | v1 |
| UTIL_VERSION | 3.08 |
| Pacote | este diretório (`orchestration/ia_orquestrator` no candidato) |
| Python | ≥ 3.11 |
| Persistência | SQLite por host em `$IA_ORCHESTRATOR_HOME` |
| Transporte MVP | polling GitHub Issues/comentários |
| Modelo real | HTTP OpenAI-compatível (`POST /chat/completions`) e Anthropic (`POST /v1/messages`, `anthropic-version: 2023-06-01`) |
| Executor | subprocess lista de args, JSON stdin/stdout; simulated; manual/pull; `cursor_chat` (poller `loop tick` + LLM deste chat) |

## Escopo implementado

- Cadastro N projectos, `--project` obrigatório, anúncio do repositório antes de mutações
- Envelope JSON+Markdown, schema em `schemas/`
- Estados de tarefa, request e execução; uma request **primária** activa por tarefa, com comandos side-band `non_blocking` e `programmed_stop` permitidos durante `RECOVERY_REQUIRED` sem substituir a execução primária
- Inbox/outbox transaccionais, deduplicação `(namespace, message_id)`, cursor com janela sobreposta
- Reconciliação de POST com timeout via o mesmo `message_id`
- Locks locais de worker (identidade não é roubada por outro `worker_id`) e de workspace
- Workers orquestradora/executora, dry-run, doctor sem chamadas pagas
- Contexto com hash de fontes; bloqueio se fonte obrigatória ausente
- Políticas: sem push/merge/deploy por omissão; env minimizado no subprocesso
- Alertas Discord opcionais e desligados no exemplo; `discord_msg` não vem neste pacote
- Quarentena: SQLite + comentário de diagnóstico na issue (`quarantine-notice`; não é envelope)
- `ia-orchestrator loop inspect|tick|arm`, `examples/cursor_chat_loop.sh`, modo YAML `cursor_chat` (o worker Python não executa o job); polling continua a cada 10 s em `RECOVERY_REQUIRED` e novos controles side-band entram em `control_head`
- Devolução de controle (`result`, `question`, `error`, inclusive `blocked` / `failed` / `unknown`): persiste o checkpoint já registado, publica a mensagem do tipo certo, arquiva o `running/`, troca o label para `status:waiting-orchestrator` e o inspect local volta a `IDLE` se não houver outro trabalho. A issue fica aberta. O estado da tarefa (`WAITING_ORCHESTRATOR` ou `WAITING_INPUT`) não é o `IDLE` da executora. `RECOVERY_REQUIRED` permanece só enquanto o trabalho segue executável, incluindo `loop rearm`
- Defaults: `policy.allow_push=true` sem merge, deploy ou force push; o exemplo e o bootstrap desta cópia nascem com `alerts.enabled=false`; `progress.enabled=true` com intervalo de 15 minutos, reutilizando a tag `PULSE` sem o poller publicar sozinho. Push automático só após `success`, de commits já existentes, com upstream, árvore limpa e sem segredo. Override por projecto no YAML
- Continuação multi-turn util 3.03: `loop rearm` limpa apenas o marcador de wake, sem tick imediato, permitindo reemitir o mesmo `RECOVERY_REQUIRED` no próximo poll
- Guard macOS do monitor: `keep_awake` usa `caffeinate` em modo utility ligado ao PID do monitor, mantendo assertions `-d/-i/-u` durante toda a vida do monitor para evitar sleep e lock automático por inatividade; lock manual/MDM não é contornado
- Observabilidade util 3.03: `check` = inspeção passiva; `status` publica o `non_blocking` de telemetria com corpo fixo quando a issue está `status:running` e devolve o `request_id` na hora; outra inspeção remota usa `non_blocking` directo, com retorno por `control_result`
- Compatibilidade side-band util 3.03: `ACK/progress` inicial da executora anunciam `UTIL_VERSION` + tipos suportados em marcador machine-readable; o marcador descreve capacidades do canal side-band
- Demo offline e testes pytest
- `send_file` (util 3.06): a primeira utilização grava o link público da pasta do Google Drive. A orquestradora sobe o arquivo nessa pasta e publica o link, o hash, o tamanho e `push` (default false). A executora, só em IDLE, baixa o arquivo se ele estiver nessa pasta, grava apenas em `transfered_files/` depois do SHA-256 e não apaga nada no Drive. A orquestradora apaga o arquivo da pasta depois do `result` de sucesso.
- `get_file` (util 3.08): a orquestradora publica um URL https. A executora, só em IDLE, resolve o arquivo para um diretório temporário, envia-o à mesma pasta pública e responde com nome, link, SHA-256, tamanho e `source_protocol`. Se o URL aponta para um arquivo do repositório do projeto, a leitura usa Git (`git cat-file`) e não HTTP. Os demais URLs continuam em https com TLS verificado. A orquestradora baixa essa cópia e a apaga. A executora não grava o arquivo no repositório e não apaga nada no Drive.

## Decisões

- Isolamento: `namespace = host|owner/repo|project_id`
- GitHub API version header: `2022-11-28`; Accept `application/vnd.github+json`; paginação por `Link: rel=next`
- Preços de modelo não estão embutidos; `pricing.models` é opcional
- GitHub webhooks de Issues fora do MVP (o transporte é polling)
- Alertas Discord não são SoT nem envelopes executáveis. Este pacote não inclui `discord_msg` nem `docs/ALERTS_DISCORD.md`
- Sem eleição distribuída; sem exactly-once externo
- A ferramenta CLI real do utilizador **não** foi identificada: só o contrato + `examples/simulated_executor.py`
- Três elos de execução: (1) `worker run` headless, (2) CLI pull colada à mão, (3) chat Cursor local acordado por `notify_on_output` — `loop arm` / `docs/CURSOR_CHAT_LOOP.md`.
- No chat Cursor, `RECOVERY_REQUIRED` bloqueia uma segunda request normal, mas não o canal de controle: `non_blocking` exige preflight de não interferência; `programmed_stop` pode controlar a parada; ambos retornam `control_result`.
- O spec original proíbe herdar a UI do chat **via API**; o wake local do IDE não é essa API. Cloud `subscribe_timer` está fora deste modo.
- Observabilidade side-band: `status` publica o `non_blocking` padronizado de telemetria e devolve o `request_id` na hora; outro pedido side-band usa `non_blocking` directamente. `control_result` segue o fluxo normal da orquestradora.
- Compatibilidade de banco: as migrations históricas que criaram `scheduled_followups` permanecem imutáveis para não renumerar versões em bancos 3.01 já existentes; a API/runtime correspondente foi removida em 3.02 e a tabela, se existir, fica inerte.

## Testes executados

`python3 -m pytest tests -q` — suite offline com transporte em memória e adaptadores determinísticos (incluindo duas rodadas + complete, pergunta/resposta, isolamento multi-repo e multi-projecto, reentrega, timeout de publicação, crash, paginação/rate limit, envelope inválido/editado, pause/cancel tardio, limites, locks, dry-run/CLI, subprocesso, loop tick/claim/dedup/`cursor_chat`).

Smoke test GitHub real: **pendente** (sem repositório/credenciais autorizados nesta sessão).

Mudança util 3.00 / macOS keep-awake (2026-10-04): foram adicionados testes unitários para construir o comando `caffeinate` com utility-vigia e vincular o PID do monitor. **Esses testes novos também não foram executados nesta sessão connector-only**.

Mudança util 3.03 / observabilidade direta (2026-10-05): o wrapper de telemetria temporizado foi removido. `check` permanece passivo; consultas à executora usam `non_blocking` diretamente e `control_result` volta ao fluxo normal. O marcador de capabilities continua anunciando os tipos side-band suportados. **Validar com `python3 -m pytest tests -q` em checkout local/CI.**

## Pendências

- Webhooks
- Vários workers concorrentes do mesmo papel/projecto (exigiria lock transaccional externo)
- Migração histórica dos `.md` antigos (opcional, explícita, sem reexecutar)
- Integração da CLI real do utilizador quando for identificada
