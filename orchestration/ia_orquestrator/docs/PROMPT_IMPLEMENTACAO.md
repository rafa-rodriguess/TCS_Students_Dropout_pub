Prompt de implementação — comunicação assíncrona entre IAs para N projetos

Nota desta cópia: o pacote instalável é este diretório. `.env.example`, `docs/ALERTS_DISCORD.md` e `discord_msg` ficaram de fora. O texto abaixo conserva a especificação original e ainda cita `util/ia_orquestrator` como nome histórico do código.

1. Missão e entrega

Você é a LLM responsável por implementar este projeto. Implemente um sistema funcional, reutilizável e independente do domínio em util/ia_orquestrator, relativo à raiz de trabalho informada pelo usuário. Preserve exatamente essa grafia. Não crie uma cópia do sistema dentro de cada projeto consumidor.

Este documento é uma especificação de implementação, não um pedido para produzir somente uma proposta. Entregue código, configuração, testes relevantes, exemplos e documentação operacional. Ao final da implementação, crie obrigatoriamente estes dois arquivos dentro de util/ia_orquestrator:

INSTRUCOES_LLM_ORQUESTRADORA.md.

INSTRUCOES_LLM_EXECUTORA.md.

Esses dois manuais devem descrever o software efetivamente implementado, com comandos executáveis e exemplos coerentes. Não basta copiar este prompt, produzir esqueletos ou prometer funcionalidades futuras.

Salve também uma cópia integral deste prompt em util/ia_orquestrator/docs/PROMPT_IMPLEMENTACAO.md, para preservar o histórico. Leia primeiro as instruções locais aplicáveis e inspecione o diretório de destino. Se já houver código, evolua-o preservando dados e compatibilidade; não sobrescreva trabalho desconhecido.

2. Contexto e objetivo do usuário

O usuário conversa com uma IA em uma interface de chat para formular ideias, definir propostas e criar prompts. Atualmente esses prompts são arquivos Markdown no GitHub. Uma IA em outro ambiente monitora novos arquivos, executa as tarefas e publica respostas. A retomada da análise na primeira ponta depende do usuário.

Implemente uma comunicação persistente, assíncrona e rastreável usando GitHub Issues e comentários. O usuário poderá continuar planejando pelo chat, mas um agente coordenador externo, acionado por um processo contínuo e por um modelo via API, poderá assumir as rodadas automáticas de avaliação e próximo prompt.

Não automatize cliques no chat nem presuma que uma API herda conversas, memória, assinatura ou permissões da interface utilizada pelo usuário. Todo contexto necessário deve ser fornecido explicitamente. O uso manual, no qual o usuário aciona a orquestradora, também deve funcionar com o mesmo protocolo.

O sistema deve servir a N projetos: pesquisa, software, análise de dados e outros. Nenhuma regra específica de um projeto pode ficar codificada no núcleo.

3. Escopo obrigatório e decisões de arquitetura

Use Python, uma versão estável compatível com o ambiente, pacote instalável e CLI ia-orchestrator. Registre dependências e versões de forma reproduzível. Use SQLite para persistência local, modelos validados para configuração/mensagens, cliente HTTP com timeout e testes automatizados. Bibliotecas concretas podem ser escolhidas conforme as convenções existentes.

Separe os componentes:

Componente

Responsabilidade

Transporte GitHub

Criar tarefas, enviar e ler mensagens, paginar, tratar limites e falhas

Protocolo

Validar envelope, autoria, correlação, tipos e transições

Registro de projetos

Resolver configuração explícita e isolamento

Estado local

Inbox, outbox, deduplicação, execução, checkpoints e auditoria

Worker da orquestradora

Avaliar resultados, pedir esclarecimentos e emitir próximas instruções

Worker da executora

Entregar tarefas ao executor configurado e publicar resultados

Adaptador de modelo

Chamar um provedor via API e validar sua saída

Adaptador de execução

Integrar uma IA local/CLI existente sem depender de sua interface gráfica

CLI

Operação humana, integração com LLMs e diagnóstico

Contexto

Montar pacote de contexto com fontes e versões verificáveis

Implemente polling como mecanismo inicial para ambos os workers. Webhooks são uma evolução opcional e não podem ser necessários para o funcionamento básico. Os dois ambientes se comunicam somente pelo transporte configurado; não compartilham filesystem ou banco SQLite.

Implemente um adaptador real de modelo via API, configurável por modelo e credencial, validando a documentação oficial vigente durante a implementação. Inclua um adaptador simulado determinístico para demonstração e testes. O adaptador real deve ter chamada, timeout, validação de resposta, tratamento de erro e registro de consumo; não aceite um stub como integração pronta.

Para a IA local, implemente integração genérica por processo externo: comando configurado como lista de argumentos, entrada JSON por stdin, saída JSON por stdout, stderr para logs, diretório de trabalho explícito, timeout e código de saída. Não use shell=True nem transforme texto de mensagens em comandos shell. Forneça um executor simulado funcional e documente o contrato para conectar a ferramenta real do usuário. Se a ferramenta real não foi identificada, não invente flags ou alegue que foi integrada.

4. Instalação compartilhada e configuração de N projetos

O código fica em util/ia_orquestrator. Configurações privadas, bancos, logs e segredos ficam fora do código versionado, em diretório de dados configurável. Cada host possui seu próprio diretório de dados; permita definir IA_ORCHESTRATOR_HOME.

Uma instalação deve cadastrar e operar vários projetos. Cada operação deve indicar --project <id>. O cadastro deve exigir --repo owner/repo. O comando deve mostrar qual repositório foi resolvido antes de modificar recursos. Não inferir silenciosamente o repositório a partir do cwd, de outro projeto ou de uma conversa anterior.

Permita repositórios diferentes por projeto e vários projetos no mesmo repositório. A identidade de roteamento deve incluir host GitHub, repositório, project_id, issue e task_id. Uma colisão de nomes ou números de issue entre repositórios não pode causar contaminação.

Distinguir:

Repositório de comunicação: obrigatório, recebe Issues/comentários.

Repositório de código/artefatos: por padrão o mesmo, mas configurável separadamente quando necessário.

Workspace local: caminho específico daquele ambiente, nunca pressuposto como válido na outra ponta.

Configuração de exemplo, a ser adaptada e validada pelo software:

schema_version: 1
project_id: projeto-exemplo
github:
  host: github.com
  repository: organizacao/repositorio
  token_env: GITHUB_TOKEN_PROJETO_EXEMPLO
  allowed_senders:
    human: [usuario-responsavel]
    orchestrator: [bot-orquestrador]
    executor: [bot-executor]
artifacts:
  repository: organizacao/repositorio
workspace:
  root: /caminho/local/do/projeto
context:
  proposal: docs/proposta.md
  source_of_truth: source_of_truth.json
  instructions: AGENTS.md
orchestrator:
  mode: api
  provider: provedor-configurado
  model: modelo-configurado
  api_key_env: LLM_API_KEY
executor:
  mode: subprocess
  command: [caminho-do-executavel, argumento-configurado]
polling:
  interval_seconds: 30
  max_backoff_seconds: 300
limits:
  max_rounds_per_task: 10
  max_revisions_per_request: 3
  task_timeout_seconds: 7200
  model_call_timeout_seconds: 120
  max_input_tokens: 30000
  max_output_tokens: 4000
  budget_usd_per_task: 5.0
policy:
  allow_push: false
  allow_merge: false
  allow_deploy: false

Valores são exemplos configuráveis, não credenciais, preços ou decisões reais do usuário. Valide campos, caminhos, credenciais por referência e políticas antes de ativar um worker. Paths de contexto opcionais ausentes devem ser informados, sem inventar conteúdo. Ausência de uma fonte declarada obrigatória deve bloquear a tarefa. Configurações locais podem variar por host; project_id, repositório e protocolo devem coincidir.

5. GitHub como registro de comunicação

Use uma issue por tarefa. O corpo inicial contém objetivo, contexto, critérios de aceitação e identificação do protocolo. Cada nova mensagem vira um novo comentário. Correções são novas mensagens referenciando a anterior. O software não deve editar respostas antigas para substituir o histórico.

GitHub não é um registro imutável: comentários podem ser editados ou excluídos por usuários autorizados. Grave IDs, timestamps e hashes das mensagens observadas; detecte alterações posteriores e sinalize divergência, sem executar automaticamente o texto alterado como uma nova instrução.

Labels podem facilitar visualização, mas não são autoridade para estado ou deduplicação. Fechar uma issue manualmente deve interromper novas rodadas e ser registrado; fechamento não prova aprovação do resultado.

Artefatos extensos ficam em arquivos ou commits acessíveis às duas pontas. Use referência com repositório, caminho, commit e hash quando aplicável. Um caminho local sozinho não é uma entrega compartilhada. Não faça push sem a política do projeto autorizar; nesse caso explique como disponibilizar o resultado e mantenha a tarefa pendente de publicação.

Documentação técnica de referência: a API permite listar e criar comentários e retornar seus corpos Markdown. Na implementação, valide os endpoints e permissões atuais na documentação oficial de comentários. Aplique paginação, tratamento de rate limits e retries conforme as boas práticas oficiais. Essas capacidades do GitHub não constituem uma fila transacional; implemente a confiabilidade na camada de aplicação.

6. Protocolo de mensagens versionado

Defina um envelope JSON validado, delimitado por marcadores inequívocos, seguido de corpo Markdown legível. Inclua um schema versionado no projeto. Exemplo conceitual:

<!-- ia-orchestrator:message:v1 -->
```json
{
  "schema_version": 1,
  "project_id": "projeto-exemplo",
  "repository": "organizacao/repositorio",
  "task_id": "uuid-da-tarefa",
  "message_id": "uuid-da-mensagem",
  "sender_role": "orchestrator",
  "sender_id": "coordenador-01",
  "recipient_role": "executor",
  "type": "request",
  "in_reply_to": null,
  "request_id": "uuid-da-solicitacao",
  "attempt": 1,
  "created_at": "2026-09-17T12:00:00Z",
  "context_revision": "identificador-da-revisao",
  "payload_sha256": "hash-do-corpo-canonicalizado"
}
```
<!-- ia-orchestrator:body -->
## Objetivo
Executar a etapa definida no contexto.

## Critérios de aceitação
- Critérios observáveis e verificáveis.

## Entregáveis
- Resultado e evidências com referências acessíveis.
<!-- ia-orchestrator:end -->

Defina canonicalização, campos obrigatórios por tipo e limites de tamanho. O hash detecta mudanças; não comprova identidade. Valide remetente contra a autoria autenticada retornada pelo GitHub e a configuração. Não confie apenas no campo sender_role. Contas distintas são preferíveis; se as duas pontas compartilham credencial, documente a redução de garantia sobre a identidade dos papéis.

Tipos mínimos:

Tipo

Emissor

Efeito

task_open

Humano ou orquestradora autorizada

Abre tarefa com objetivo e critérios

request

Orquestradora

Solicita uma execução delimitada

non_blocking

Orquestradora

Solicita trabalho side-band durante uma execução ativa; só pode executar após preflight que demonstre não interferência com o processamento atual

programmed_stop

Orquestradora

Solicita parada imediata ou condicional da execução ativa; é a única classe side-band autorizada a interferir deliberadamente para produzir a parada


ack

Executora

Confirma recebimento; não significa conclusão

progress

Executora

Informa andamento sem disparar nova rodada

question

Qualquer papel

Solicita esclarecimento correlacionado

answer

Destinatário da pergunta

Responde sem criar execução duplicada

result

Executora

Entrega resultado e evidências para avaliação

control_result

Executora

Entrega o resultado de `non_blocking` ou `programmed_stop` sem substituir nem concluir a request primária


review

Orquestradora

Registra aceite parcial ou necessidade de correção

error

Qualquer papel

Falha classificada e possibilidade de recuperação

pause / resume / cancel

Humano ou papel autorizado

Controla ciclo conforme política

complete

Orquestradora autorizada

Declara aceite final com evidências

A orquestradora emite nova request para uma correção; review não executa comandos. Defina respostas a perguntas para permitir retomar uma solicitação bloqueada sem tratá-la como nova tarefa. Mensagens ordinárias sem envelope não são instruções executáveis; exiba-as como observações. Uma intervenção humana operacional usa CLI ou envelope validado e autoria autorizada.

Aceite eventos entregues repetidamente e fora de ordem. Referências ainda não recebidas ficam pendentes até sincronização; não descarte nem execute por aproximação. Mensagens inválidas ou incompatíveis ficam em quarentena com diagnóstico.

7. Estados, autoria das transições e concorrência

Implemente estado de tarefa separado do estado de entrega de mensagem e de execução de uma solicitação. Defina tabela de transições, guardas e testes. Estados de tarefa mínimos:

NEW, WAITING_EXECUTOR, RUNNING, WAITING_ORCHESTRATOR, WAITING_INPUT, PAUSED, COMPLETED, FAILED, CANCELLED.

Fluxo nominal: abertura → request → ack/início → result → avaliação → nova request ou complete. Durante `RECOVERY_REQUIRED`, o poller continua sincronizando em ciclos de 10 s; request normal não concorre com a primária, mas `non_blocking` e `programmed_stop` podem chegar pelo canal side-band e retornar `control_result`. Perguntas suspendem a execução afetada. progress e ack nunca geram chamadas de modelo por si só. A entrega result não significa sucesso aceito. Preserve referências a resultados rejeitados e à nova tentativa.

Na primeira versão, suporte uma solicitação ativa por tarefa e um worker ativo por papel/projeto. Projetos independentes podem progredir em paralelo, dentro de limites de recursos. Use lock local para impedir processos duplicados no mesmo host. SQLite local e labels do GitHub não fornecem exclusão mútua entre hosts: não prometa eleição distribuída ou exatamente uma execução global.

Cada papel/projeto deve ter worker_id fixo e proprietário operacional configurado. Outro host não pode assumir automaticamente a mesma identidade após apenas um timeout. Documente transferência manual: parar o proprietário anterior, reconciliar execuções/outbox e ativar o novo. Suporte a múltiplos workers concorrentes do mesmo papel/projeto exige um coordenador de locks transacional externo e fica fora do MVP.

Pause/cancel devem impedir novas solicitações e interromper subprocessos quando possível. Documente que não desfazem efeitos já realizados. Resultados tardios devem ficar registrados, sem reativar tarefa encerrada. Reabertura requer ação explícita e nova geração/revisão de execução.

8. Persistência, retries e recuperação

Implemente inbox/outbox transacionais em SQLite, com migrations. Unicidade inclui namespace do projeto/repositório e message_id. Guarde também IDs do GitHub, hash original, eventos, solicitações, tentativas, decisão do modelo, consumo e checkpoints.

Antes de publicar, persista a mensagem na outbox com ID estável. Se o POST terminar com timeout após possível sucesso remoto, reconcilie os comentários pelo mesmo message_id antes de repetir. Reutilize o ID em retries. Duplicatas remotas ainda possíveis devem ser reconhecidas e ignoradas pelos consumidores.

No consumo, persista o evento antes de avançar o cursor. Faça polling com janela sobreposta e deduplicação; não dependa somente de um timestamp estritamente crescente. Trate paginação completa, empates, respostas vazias e falhas no meio de páginas. Faça reconciliação periódica das issues ativas.

Persista início de execução antes de chamar o adaptador e o resultado antes de publicá-lo. Após crash com execução de estado desconhecido, não repita efeitos cegamente. Consulte o checkpoint/adaptador ou marque WAITING_INPUT para reconciliação. Diferencie retry de transporte, retry de chamada de modelo e nova tentativa de execução.

Garanta processamento idempotente onde controlável, sem prometer exactly-once para comandos externos. Documente esse limite nos dois manuais. Backoff exponencial com jitter, limites de tentativas e respeito aos cabeçalhos de rate limit devem evitar tempestades de requisições. Auth inválida deve gerar erro acionável, não loop infinito.

9. Contexto e comportamento da orquestradora

Monte para cada chamada um pacote contendo objetivo, proposta aprovada, instruções operacionais, fonte de verdade quando existente, revisão de contexto, critérios, decisões humanas, limites, solicitação em avaliação, resultado e evidências relevantes. Todas as referências devem ser resolvidas de modo acessível ao host consumidor.

Registre commit/hash de cada fonte. Não permita atualização silenciosa de metodologia ou critérios por um resultado da executora. Mudanças autorizadas de contexto geram nova revisão e mensagem explícita. Resultado baseado em revisão anterior exige avaliação da divergência antes de continuar.

Imponha limite de contexto: preserve instruções, critérios, decisões e evidências necessárias. Resumos devem apontar mensagens de origem e não substituir os dados originais. Se não houver contexto suficiente, peça esclarecimento; não invente fatos.

A saída do modelo deve seguir schema fechado com decisão entre: dispatch, revise, ask_executor, ask_human, complete, pause, fail; texto e referências de evidências; e uma próxima solicitação quando pertinente. O código valida a saída e aplica política/estado. Não delegue ao modelo a validação final de permissões ou limites.

A avaliação deve distinguir evidência observada, relato da executora e informação ausente. Não declarar teste aprovado sem evidência. Quando possível, verificar critérios automaticamente. Ao atingir limite de rodadas, revisões, tempo ou orçamento, pausar com resumo e motivo.

Custos: registre tokens e custo estimado com tabela de preços explicitamente configurada. Reserve orçamento conservador antes de cada chamada quando for possível estimá-lo. Se não houver preço/tokenização confiável, não alegue garantia monetária: use limites de chamadas/tokens e informe que custo é desconhecido. Não embuta preços como fatos permanentes.

10. Integração da executora

Contrato de entrada: projeto/repositório, task/request IDs, tentativa, prompt, contexto resolvido, revisão, cwd permitido, critérios, limites e chave idempotente. Contrato de saída: status, resumo, arquivos modificados, artefatos compartilhados, testes com resultados, erros, dúvidas, checkpoint e recomendação técnica.

O worker é responsável pelo protocolo e publicação. A IA local deve usar o adaptador ou a CLI, sem implementar sua própria lógica divergente de fila. Inclua modo manual/pull para ferramentas que não expõem uma CLI de execução: obter pendência, registrar início e entregar resultado. Esse modo requer um acionador externo e não deve ser apresentado como execução automática.

Não executar duas tarefas mutáveis no mesmo workspace ao mesmo tempo. Implemente lock de workspace ou use worktrees isoladas quando apropriado e suportado. Verifique branch e alterações existentes antes de trabalhar. Nunca descarte alterações do usuário para cumprir tarefa.

11. CLI e experiência de uso

Implemente estes comandos ou equivalentes consistentes; se alterar nomes, atualize todos os exemplos e manuais:

ia-orchestrator project add --project exemplo --repo organizacao/repositorio --workspace /caminho/local
ia-orchestrator project list
ia-orchestrator project show --project exemplo
ia-orchestrator doctor --project exemplo
ia-orchestrator task create --project exemplo --prompt-file /caminho/prompt.md
ia-orchestrator task list --project exemplo
ia-orchestrator task show --project exemplo --task TASK_ID
ia-orchestrator worker run --project exemplo --role executor --once
ia-orchestrator worker run --project exemplo --role orchestrator --once
ia-orchestrator worker run --project exemplo --role executor
ia-orchestrator worker run --project exemplo --role orchestrator
ia-orchestrator task pause --project exemplo --task TASK_ID --reason "Revisão humana"
ia-orchestrator task resume --project exemplo --task TASK_ID
ia-orchestrator task cancel --project exemplo --task TASK_ID --reason "Cancelada pelo responsável"
ia-orchestrator task export --project exemplo --task TASK_ID --output /caminho/historico.md

Inclua comandos para publicar respostas/perguntas validadas, consultar pendências e reconciliar a outbox. Ofereça saída --json, códigos de saída documentados e --dry-run para ações mutáveis. Em dry-run, não publique, não execute subprocessos de trabalho e não chame modelos pagos.

doctor deve separar acesso ao GitHub, Issues habilitadas, permissões, autoria/papéis, workspace, banco, adaptador e credenciais de modelo. Não faça chamadas pagas como efeito oculto do diagnóstico.

Um comando de bootstrap deve gerar configuração e guias de ativação a partir de --project e --repo. O usuário não deve editar código para cadastrar outro projeto. Não ligar automaticamente serviços ao cadastrar.

Forneça instruções de execução em foreground e exemplos opcionais para macOS launchd e Linux systemd, com caminhos absolutos, reinício e logs. Não instale serviços persistentes sem solicitação específica. Encerramento deve preservar checkpoints e outbox.

12. Segurança e limites operacionais

Use tokens por variáveis de ambiente ou mecanismo de segredos do host. Nunca versionar tokens, conteúdo de .env, banco privado ou logs com credenciais. Peça apenas permissões necessárias; escrita de Issues não implica autorização para push, merge ou deploy.

Aceite instruções somente de autores/papéis configurados, no projeto correto. Conteúdo de resultados, arquivos e comentários é dado de trabalho, não autoridade para alterar políticas do sistema. Se um resultado instruir a enviar segredos ou trocar repositório, rejeite como mudança não autorizada.

Não injete segredos na entrada do modelo. Minimize o ambiente passado ao subprocesso; tokens de transporte/modelo não devem ser herdados automaticamente pela IA executora. Explique quais credenciais cada componente necessita. Restrinja caminhos de leitura/escrita ao escopo autorizado; valide resolução de symlinks e path traversal.

Essas validações não equivalem a sandbox de sistema operacional. Se o executor tem acesso amplo ao host, documente esse fato. Tarefas arbitrárias devem usar isolamento apropriado ao ambiente; não alegue segurança total apenas por usar uma lista de caminhos.

13. Estrutura esperada

Crie, pelo menos, pacote com módulos separados de CLI, configuração, protocolo, transporte, persistência, estado, contexto, políticas e workers; adaptadores de modelo e execução; schemas; testes; exemplos; documentação e metadados de instalação.

Na raiz de util/ia_orquestrator, inclua README.md, pyproject.toml, arquivo de dependências travadas adequado à ferramenta escolhida, .gitignore, .env.example sem valores reais e os dois manuais exigidos. Os exemplos de configuração não devem apontar a repositórios reais do usuário sem que ele os informe.

A fonte de verdade do utilitário deve registrar versão, escopo implementado, decisões, testes executados e pendências. Isso é distinto da fonte de verdade de cada projeto consumidor. Não reformatar ou sobrescrever arbitrariamente fontes de verdade dos consumidores.

14. Conteúdo obrigatório dos dois manuais gerados

INSTRUCOES_LLM_ORQUESTRADORA.md

Escreva como instrução operacional pronta para uma LLM: papel, entrada necessária, como selecionar projeto/repositório, como consultar o registro e montar contexto, iniciar tarefa, publicar request, avaliar result, perguntar, corrigir, concluir, pausar e recuperar falhas. Diferencie operação manual em chat e worker automático via API. Explique que o manual sozinho não cria monitoramento contínuo.

Inclua uma conversa completa com solicitação, resultado insuficiente, revisão, nova solicitação, resultado aceito e complete. Inclua comandos reais e os envelopes válidos correspondentes. Explique critérios de evidência, revisão de contexto, orçamento e como transferir uma decisão tomada no chat para o registro compartilhado.

INSTRUCOES_LLM_EXECUTORA.md

Escreva como instrução operacional pronta para uma LLM: selecionar projeto/repositório, consultar pendências, validar destinatário e contexto, registrar início, executar dentro do escopo, fornecer progresso sem gerar loops, solicitar esclarecimentos, publicar evidências e aguardar próxima solicitação.

Inclua comandos reais e exemplos de sucesso, bloqueio, falha recuperável e crash com execução desconhecida. Explique o contrato stdin/stdout para adaptadores, o modo manual/pull, os requisitos de artefatos compartilhados e o que fazer quando não há autorização para publicar arquivos. Uma entrega da executora não encerra a tarefa por decisão unilateral.

Ambos devem ser genéricos, em PT-BR, sem depender do projeto usado na demonstração. Devem exigir identificação do repositório na ativação e nunca instruir a adivinhar o destino. Especifique versão do protocolo e do software a que se aplicam.

15. Testes e critérios de aceitação

Teste comportamento e recuperação, não somente funções isoladas. Use transporte simulado e adaptadores determinísticos para testes offline reproduzíveis. Inclua:

Duas rodadas completas de prompt/resposta e aceite final.

Pergunta da executora, resposta e retomada da solicitação correta.

Dois projetos em repositórios diferentes, com números de issue iguais, sem cruzar mensagens.

Dois projetos no mesmo repositório, corretamente separados.

Reentrega da mesma mensagem sem repetição de execução concluída.

Timeout de publicação após sucesso remoto, com reconciliação e ID estável.

Crash antes/depois da execução e antes/depois da publicação.

Paginação, timestamps iguais e falha parcial de sincronização sem perda de evento.

Mensagem editada, remetente não autorizado, envelope inválido e versão incompatível.

Resultado tardio após cancelamento e pausa antes de nova rodada.

Limites de rodadas, tokens/tempo/orçamento e saída inválida do modelo.

Divergência de revisão de contexto e ausência de fonte obrigatória.

Lock de worker/workspace e recuperação sem concorrência indevida.

Falha de autenticação e rate limit sem loop agressivo.

Dry-run sem efeitos remotos ou chamadas pagas.

Inclua demonstração end-to-end offline que qualquer pessoa possa executar sem credenciais. Prepare smoke test real em repositório de teste fornecido pelo usuário, usando adaptadores configurados e limites baixos. Não invente repositório nem publique em terceiros para testar.

Se faltarem credenciais, finalize todo o código testável, documentação e demonstração offline; informe que a validação real ficou pendente e forneça o comando exato para executá-la. Não classifique um teste simulado como integração real comprovada.

Aceitação final: instalação limpa, CLI funcional, comunicação registrada, isolamento entre projetos, recuperação demonstrada, nenhuma credencial nos entregáveis, adaptadores documentados e os dois manuais compatíveis com os comandos reais. Um novo projeto deve funcionar por cadastro/configuração, sem alteração do núcleo.

16. Sequência de implementação e relatório final

Inspecione o ambiente e as instruções locais; registre decisões e salve este prompt.

Implemente configuração multi-projeto, protocolo e modelo de estado.

Implemente persistência, transporte GitHub e recuperação.

Implemente CLI, adaptadores e workers dos dois papéis.

Implemente contexto, políticas e limites.

Execute testes de integração offline e corrija falhas.

Gere os dois manuais operacionais, exemplos e demonstração.

Execute smoke test real apenas se repositório e credenciais autorizados estiverem disponíveis.

Entregue resumo do que funciona, comandos para instalar/cadastrar/iniciar, testes efetivamente executados e limitações concretas.

Não pare após planejar. Não implemente um dashboard, serviço distribuído complexo ou migração destrutiva dos .md antigos como requisito inicial. Preserve o fluxo atual; a adoção do novo sistema pode começar por uma tarefa de teste. Migração histórica é opcional e deve ser explícita, com deduplicação e sem reexecutar tarefas antigas.

O resultado esperado é um utilitário operacional reutilizável em util/ia_orquestrator, acompanhado de dois manuais que permitam a uma LLM orquestradora e a uma LLM executora usar o mesmo protocolo em qualquer projeto cadastrado.


### Observabilidade da orquestradora

Implemente `check` como sincronização e inspeção **passiva** do estado corrente; ele não envia trabalho ao executor.

Telemetria e outras inspeções durante execução ativa devem usar diretamente o tipo `non_blocking` já definido no protocolo, na mesma task/issue e com novo `request_id`. A executora faz preflight de não interferência e responde por `control_result`.

Não crie timer ou follow-up especial para observabilidade e não suprima temporariamente `control_result`. A resposta side-band deve seguir o fluxo normal assim que observada.
