# Loop no chat Cursor aberto

Software: **ia-orchestrator 0.1.0**. Protocolo: **v1**.  
Este documento descreve o modo operacional em que a LLM **deste chat** (Agent mode local no IDE) executa o job. GitHub Issues continua a ser a fonte de verdade. O poller local só acorda **esta** conversa.

CLI: `ia-orchestrator loop inspect | tick | arm`. Script: `examples/cursor_chat_loop.sh`. Modo YAML: `executor.mode: cursor_chat` (e/ou `orchestrator.mode: cursor_chat`).

O canal partilhado entre N projectos continua a ser GitHub Issues. Este loop **não** substitui o protocolo nem a fila de envelopes. Também **não** é a fila de ficheiros `prompts/Q…__.md` de um estudo concreto. Discord não vem neste pacote; se o operador o ligar à parte, é só campainha de fase.

## 0. Dois processos

| Peça | O que é | O que faz | O que **não** faz |
| --- | --- | --- | --- |
| Poller | `examples/cursor_chat_loop.sh` (ou o comando impresso por `loop arm`) no terminal **deste** chat | chama `loop tick --claim`, compara um `wake_key`, imprime `AGENT_LOOP_TICK_*` só quando o estado muda. Lança `keep_awake.py` **num processo à parte** (`caffeinate -d -i -u` no macOS) e mata-o ao sair | Não lê o corpo científico da `request`. Não chama LLM/API. Não corre `worker run` para executar o trabalho. Não gera código. |
| Executor | a LLM **deste chat Cursor**, na sessão que o humano deixou aberta | quando acorda, lê o sentinela / `loop inspect`, **executa o job com as tools do agente**, depois `execution deliver` | Não espera o humano colar o prompt. Não abre outro chat. Não lança `Task`/subagente para “ser o executor”. |

O elo **não** é um webhook para um modelo. É o mecanismo local do Cursor (skill **Monitored shell output** — não Cloud `subscribe_timer`):

1. A LLM arranca o poller **em background neste chat**, com stdout monitorizado (`notify_on_output`).
2. O poller, só quando o estado **muda** e não é `IDLE`, imprime `AGENT_LOOP_TICK_executor {…}` (ou `_orchestrator`).
3. O Cursor injeta essa notificação **como follow-up nesta mesma conversa**.
4. A LLM acorda **neste chat**, processa **um** item, entrega via CLI.
5. O poller continua. O chat permanece aberto.

Se o chat fechar, a sessão do agente acabar, ou o terminal monitorizado morrer, **não há executor**. O poller sozinho não substitui a LLM. `worker run` em Python/API/subprocess é outro modo (headless) — não misture os dois no mesmo papel/projecto.

## 1. O que isto não é

Não use nenhum destes desenhos para o modo chat aberto:

- Cloud `/loop` com `cursor-subscriptions-subscribe_timer`
- `ia-orchestrator worker run --role executor` a **executar** o trabalho (com `mode: cursor_chat` o worker só sincroniza)
- `Task` / subagente / “best-of-n” como worker
- Segundo chat ou agente headless a quem o poller “envia” o prompt
- HTTP/LLM API chamada pelo bash
- O poller a interpretar o Markdown da `request`
- Vários chats executores em paralelo no mesmo projecto (no máximo **um** `running/*.md` por projecto)

## 2. Como o Cursor acorda este chat

A tool Shell do agente local:

- `block_until_ms: 0` — arranca e **não espera**; o processo fica ligado a **este** chat
- `notify_on_output.pattern` — regex contra stdout/stderr; quando casa, o Cursor notifica **este** agente
- A notificação traz o output (e frequentemente o path do terminal), **não** um prompt humano novo. O sentinela carrega o `prompt` ao lado:

```text
AGENT_LOOP_TICK_executor {"prompt":"Execute the pending GitHub work per INSTRUCOES_LLM_EXECUTORA.md and docs/CURSOR_CHAT_LOOP.md","status":"JOB","payload":{"project":"exemplo"}}
```

Contrato de wake:

**Agente de discussão (3.04):** use um **segundo chat**, com `loop arm --role agent`, sentinela `AGENT_LOOP_TICK_agent`, PID `cursor_loop_agent.pid` e diretório `agent_discussions/`. Ele apenas lê `discuss` e envia `analysis` à orquestradora; não executa tarefas, não reclama `running/*.md`, não interrompe o poller da executora e não altera labels. Veja [INSTRUCOES_LLM_AGENTE.md](../INSTRUCOES_LLM_AGENTE.md) e `examples/cursor/agent.mdc`.


1. Sentinela único por papel: `AGENT_LOOP_TICK_executor` ou `AGENT_LOOP_TICK_orchestrator`.
2. Regex: `AGENT_LOOP_TICK_executor` (âncora `^` se for sempre início de linha).
3. Um único loop por papel. Antes de armar, inspecione os terminais; não duplique o poller.
4. PID em `$IA_ORCHESTRATOR_HOME/projects/<id>/data/cursor_loop_<role>.pid`.
5. Smoke-check: o processo arrancou.
6. **Não mate o poller** no fim de um job. Ciclo: acordar → um job → idle neste chat, shell ainda a correr.
7. Para parar: matar o PID e consumir a notificação de término do shell.

### macOS: impedir lock automático enquanto o monitor está vivo

O script `examples/cursor_chat_loop.sh` lança `ia_orchestrator.keep_awake` automaticamente. No macOS, esse helper usa `caffeinate -d -i -u` **com uma utility-vigia ligada ao PID do monitor**. Como `-u` isolado tem timeout padrão curto, o uso de utility garante que a assertion de `user active` dure enquanto o monitor/sentinela estiver vivo. Resultado esperado: sem display sleep, idle sleep ou lock automático/tela de login por inatividade durante a execução do monitor.

Ao terminar o monitor, o helper/caffeinate é encerrado e o comportamento normal do Mac volta. O mecanismo não tenta impedir `Lock Screen` manual nem políticas de segurança/MDM que imponham bloqueio independentemente da inatividade.

`IDLE` **não** emite sentinela.

Rede de segurança no projecto consumidor: cópia renderizada de `examples/cursor/executor.mdc` em `<workspace>/.cursor/rules/executor.mdc` (`<id>` preenchido, `alwaysApply: true` só no destino). Procedimento: [INSTRUCOES_LLM_EXECUTORA.md](../INSTRUCOES_LLM_EXECUTORA.md), secção «Regra Cursor no projecto consumidor». O modelo no pacote não substitui esse ficheiro.

## 3. Sequência para armar (uma vez por sessão)

Execute **neste** chat, Agent mode **local** (Cursor Desktop/IDE):

1. Workspace = projecto consumidor (ou o cwd combinado). Confirme `--project` e o repositório com `project show`.
2. Instalar `.cursor/rules/executor.mdc` a partir de `examples/cursor/executor.mdc` do pacote importado, como em [INSTRUCOES_LLM_EXECUTORA.md](../INSTRUCOES_LLM_EXECUTORA.md) («Regra Cursor no projecto consumidor»).
3. No YAML: `executor.mode: cursor_chat` (e/ou `orchestrator.mode: cursor_chat`). Token no env.
4. Listar terminais. Se já existir o sentinela / poller deste papel, não arranque outro.
5. Obter o comando:

```bash
ia-orchestrator loop arm --project EXEMPLO --role executor
```

6. Arrancar **só** o poller em background **com monitorização**, usando o `command` + `environment` impressos:

```text
Shell:
  command: IA_ORCHESTRATOR_HOME=... IA_ORCHESTRATOR_PROJECT=EXEMPLO IA_ORCHESTRATOR_ROLE=executor IA_ORCHESTRATOR_POLL_SECONDS=10 IA_ORCHESTRATOR_PID_FILE=... bash examples/cursor_chat_loop.sh
  block_until_ms: 0
  description: Start ia-orchestrator chat poller
  notify_on_output:
    pattern: AGENT_LOOP_TICK_executor
    reason: Executor job wake
```

Caminho do script: `examples/cursor_chat_loop.sh` neste pacote. Equivalente: o `command` JSON de `loop arm --json`.

7. Smoke-check (PID / primeiras linhas). O arranque faz um `tick --reset-wake` imediato: se já houver `running/*.md` ou pendências, o sentinela pode sair já.
8. Confirmar ao humano numa frase: intervalo, PID, que o processamento ocorrerá **neste chat**, e que o chat deve permanecer aberto.
9. Terminar o turno. O agente fica à espera. O poller continua.

Quando a notificação chegar:

1. Ler a linha mais recente com o sentinela.
2. Interpretar o JSON (`status`, `payload.running`, `payload.head`, `payload.running_dir`).
3. Se `status` é `JOB` ou `RECOVERY_REQUIRED`: tratar **agora** (secção 6). Não pedir ao humano para colar.
4. Um job por ciclo. Não puxe o próximo à mão.
5. Não desarme o loop.

## 4. O que o tick faz

```bash
ia-orchestrator loop tick --project EXEMPLO --role executor --claim
ia-orchestrator loop inspect --project EXEMPLO --role executor --json
```

1. `Engine.sync()` — puxa comentários GitHub para a SQLite local (SoT continua a ser o GitHub).
2. Estados visíveis:
   - `QUEUE_CONFLICT` — mais do que um `running/*.md`
   - `RECOVERY_REQUIRED` — exactamente um `running/*.md` (claim anterior ou crash)
   - `JOB` — zero running e há envelope pendente para este papel
   - `IDLE` — nada a fazer
   - `GIT_ERROR` — falha de auth/rede/política no sync
3. Com `--claim` e estado `JOB`: escreve **no máximo um** `running/<tipo>-<id>.md`, publica `ack` na issue, aplica `status:claimed`, alerta Discord `request_claimed`. O estado visível passa a `RECOVERY_REQUIRED`. O sentinela da primeira vez usa `"status":"JOB"`.
4. Dedup: hash `wake_key` em `cursor_loop_<role>.last_wake`. Sentinela só se a chave mudou **e** o estado não é `IDLE`. Em `RECOVERY_REQUIRED`, requests normais não entram na chave, mas `non_blocking` e `programmed_stop` entram como `control_pending/control_head`; portanto um novo controle acorda o executor no próximo poll sem criar segundo `running/*.md`.
5. `--reset-wake` (o script usa-o no arranque): esquece a chave antes de executar **esse mesmo tick**; é recuperação de arranque/crash.
6. `loop rearm --project EXEMPLO --role executor`: apaga `last_wake` **sem executar tick**. É o mecanismo de continuação multi-turn: use-o como última acção antes de ceder um turno com `running/*.md` saudável e incompleto. O próximo tick do poller de background vê a chave ausente e reemite o sentinela para `RECOVERY_REQUIRED`.

O bash **não** interpreta o Markdown científico.

## 5. Fila (continua a ser o protocolo GitHub)

A pendência canónica é o envelope na issue **com label `ia-orchestrator` e um comentário-envelope** (não basta o corpo da issue). `running/*.md` é o **claim** deste host (no máximo um).

A orquestradora, ao publicar `request` / `review` / `complete`, deve seguir [INSTRUCOES_LLM_ORQUESTRADORA.md](../INSTRUCOES_LLM_ORQUESTRADORA.md) § Publicação no GitHub: label **e** comentário. Sem os dois, `loop inspect --role executor` fica `IDLE`. Se o envelope existir mas o `payload_sha256` (ou outro campo) falhar, o software **quarentena** a mensagem e comenta a issue com `Quarentena (não executável)` — isso também deixa a executora em `IDLE` até haver um comentário-envelope válido novo.

```bash
ia-orchestrator pending --project EXEMPLO --role executor --json
ia-orchestrator loop inspect --project EXEMPLO --role executor --json
ia-orchestrator task show --project EXEMPLO --task TASK_ID
```

Não abra segundo chat executor no mesmo workspace. Após o claim, `inspect` mostra `RECOVERY_REQUIRED` enquanto o `running/*.md` existir. `execution deliver` e uma `question` que devolve o controle arquivam esse ficheiro e voltam a `IDLE`; a issue segue aberta. Esse `IDLE` não fecha a tarefa. O `loop rearm` mantém o ficheiro quando o mesmo trabalho continua executável.

### Continuação de jobs que excedem um turno do chat

O dedup do poller é deliberado: um `RECOVERY_REQUIRED` estável **não** gera sentinela repetidamente. Isso evita spam, mas significa que terminar um turno deixando o job incompleto sem preparar novo wake produz um stall silencioso: a issue pode continuar `status:running`, o sentinela pode continuar vivo, e ainda assim não existir cálculo activo.

Por isso, quando a executora precisa ceder o turno mas a request continua saudável e executável:

1. persiste checkpoint;
2. publica `PULSE` se devido;
3. executa **como última acção** `ia-orchestrator loop rearm --project EXEMPLO --role executor`;
4. termina o turno sem `deliver`;
5. o próximo poll (normalmente em até 10 s) reemite `AGENT_LOOP_TICK_executor` com o mesmo `running/*.md` e o turno seguinte continua a request.

Não use `loop tick --reset-wake` para esse yield intencional: como ele já faz o tick, consome o reset imediatamente e pode deixar o poller de background deduplicado outra vez.

## 6. O que a LLM faz quando acorda

### Papel executor (`AGENT_LOOP_TICK_executor`)

1. `ia-orchestrator project show --project EXEMPLO` — confirmar repositório. Não adivinhar.
2. `ia-orchestrator loop inspect --project EXEMPLO --role executor --json`.
3. `QUEUE_CONFLICT` / `GIT_ERROR`: tratar o incidente, não inventar trabalho.
4. `JOB`: ler o `running/*.md` e executar normalmente. Se `type` for `send_file`, rodar `ia-orchestrator send-file --role executor` com o `task` e o `request` desse arquivo; o comando baixa o arquivo da pasta pública do Drive, confere o hash e grava só em `transfered_files/`. Não usar `execution deliver` para essa transferência. Se `type` for `get_file`, rodar `ia-orchestrator get-file --role executor` com o `task` e o `request` desse arquivo; o comando lê pelo Git quando o arquivo está no repositório do projeto e, nos demais casos, baixa o URL para um diretório temporário, envia o arquivo à pasta pública e publica o `result`. Não usar `execution deliver` para esse pedido. `RECOVERY_REQUIRED`: manter o job primário e verificar primeiro `payload.control_head`. Como o controle não ganha segundo `running/*.md`, ler seu corpo em `pending --role executor --json` pelo `request_id`. Se for `non_blocking`, executar somente após preflight de isolamento; se houver risco, devolver `control_result` bloqueado. Se for `programmed_stop`, aplicar a condição de parada. Sem `control_head`, continuar/recuperar o job primário. Nunca criar segundo `running/*.md` para controle side-band. Se o job não terminar neste turno e continuar saudável, aplique a secção de continuação multi-turn e faça `loop rearm` antes de ceder.
5. `prompts`/ficheiros do estudo só se o **job** o disser.
6. Resposta curta: task, request, veredito. Não desligar o poller.
7. Não enviar `complete`.

### Papel orquestradora (`AGENT_LOOP_TICK_orchestrator`)

1. Confirmar `--project` / repositório.
2. `loop inspect --role orchestrator`.
3. Se houver `result` (ou `task_open` ainda sem `request`, ou o `running/*.md`): avaliar evidências **neste chat**. Ajuste: `review` + `request` na mesma issue. Aceite: `complete` (fecha a issue). Nova issue só com `task create --dispatch` para **outra** tarefa.
4. `ack` e `progress` não disparam avaliação.
5. Um item por tick. Não fechar a issue à mão; o `complete` publicado é que fecha.

## 7. Mensagem de armamento

> Poller a cada 10s neste chat (PID …). Quando o tick deixar de ser IDLE, o terminal imprime `AGENT_LOOP_TICK_executor` e **esta** sessão executa o `request` e entrega com a CLI. Não feche este chat. O bash não processa o job.

## 8. Relação com os outros modos

| Modo | Quem executa | Monitorização |
| --- | --- | --- |
| `executor.mode: subprocess` / `simulated` | processo `worker run` | launchd/systemd/foreground Python |
| `orchestrator.mode: api` | HTTP do modelo | idem |
| `manual` + CLI colada | humano ou LLM pontual | nenhuma |
| **`cursor_chat`** (este doc) | LLM desta sessão Cursor | `loop arm` + `notify_on_output` |

Escolha **um** executor por papel/projecto neste host.

## 9. Fora deste documento

- Fila `Q<timestamp>Z__*.md` dos estudos
- Webhooks
- Cloud Agent `/loop`


## 10. Controles durante execução longa

O poller continua fazendo `sync` a cada **10 segundos** enquanto há `RECOVERY_REQUIRED`. Isto permite dois comandos side-band no mesmo `task_id`/issue do job ativo, sempre com novo `request_id`:

- `non_blocking`: só pode executar se não tocar nem degradar materialmente o job primário; em dúvida, recusar.
- `programmed_stop`: pode interferir no job primário exclusivamente para aplicar uma parada imediata ou condicional.

O resultado é `control_result` e não substitui o `result` do job primário. Requests normais continuam sem wake durante recovery.


## 11. Observabilidade side-band

A orquestradora mantém `check` como inspeção passiva. Para o estado padronizado da execução activa, corre `ia-orchestrator status`: isso publica o `non_blocking` de corpo fixo na mesma issue/`task_id`. Outra consulta continua a ser um `non_blocking` directo.

Um `control_result` recebido pela orquestradora entra na fila normalmente e pode acordar o chat imediatamente. O poller continua sendo apenas o mecanismo de sync/wake; ele não cria timers de observabilidade.

A executora deve aplicar o preflight descrito na secção 10: telemetria read-only pode ser executada quando barata e isolada; se houver risco de interferência, responda `control_result` com `status: blocked`.
