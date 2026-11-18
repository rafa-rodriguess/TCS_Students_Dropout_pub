# Allowlist de exportação — orquestrador LLM

**Pacote aprovado para exportação** a partir da repo privada no commit `28a6deef0fea67852f17ca07c101583b0ca4e8af` e publicado na repo `rafa-rodriguess/TCS_Students_Dropout_pub`. A branch `reproduction_candidate` continua congelada no commit científico `ff99bbcb30f53bac0e3e7d1f2720a682a5620f51`. Este inventário descreve somente o runtime LLM em `orchestration/ia_orquestrator/`.

Origem lida, e não alterada: `util/ia_orquestrator/` do software 0.1.5, `UTIL_VERSION` 3.08, protocolo v1. Destino: `a6_orchestration_candidate/orchestration/ia_orquestrator/`.

Os identificadores são Git blob SHA-1 (40 hex), os mesmos de `git hash-object` sobre o arquivo de destino. Não são SHA-256. `EXPORT_ALLOWLIST.md` entra na entrega e não é hasheado aqui.

## Incluir

| Origem | Destino | Git blob SHA-1 | Estado |
|---|---|---|---|
| `util/ia_orquestrator/.gitignore` | `orchestration/ia_orquestrator/.gitignore` | `e5262622d8111650f5fd9ccb37d19eec6182f675` | sanitizado |
| `util/ia_orquestrator/INSTRUCOES_LLM_AGENTE.md` | `orchestration/ia_orquestrator/INSTRUCOES_LLM_AGENTE.md` | `200fa52f6f5d11b63e7185a633bfd2eea4cb3ce4` | igual |
| `util/ia_orquestrator/INSTRUCOES_LLM_EXECUTORA.md` | `orchestration/ia_orquestrator/INSTRUCOES_LLM_EXECUTORA.md` | `2aef92242f3c852dc0545ab4ff2488bc1ff9786b` | sanitizado |
| `util/ia_orquestrator/INSTRUCOES_LLM_ORQUESTRADORA.md` | `orchestration/ia_orquestrator/INSTRUCOES_LLM_ORQUESTRADORA.md` | `a9d3b5cc794bbc3e45ee169856b53be4ad5b9be3` | sanitizado |
| `util/ia_orquestrator/README.md` | `orchestration/ia_orquestrator/README.md` | `76f7fd343e78f273f686791313f7afcdbf0e883e` | sanitizado |
| `util/ia_orquestrator/docs/CURSOR_CHAT_LOOP.md` | `orchestration/ia_orquestrator/docs/CURSOR_CHAT_LOOP.md` | `da2f5fdf699368c3f316cecefa8f0dd28e2ff1fe` | sanitizado |
| `util/ia_orquestrator/docs/PROMPT_IMPLEMENTACAO.md` | `orchestration/ia_orquestrator/docs/PROMPT_IMPLEMENTACAO.md` | `49280c1446bb579433885afea009a99e3255b267` | sanitizado |
| `util/ia_orquestrator/docs/SOURCE_OF_TRUTH.md` | `orchestration/ia_orquestrator/docs/SOURCE_OF_TRUTH.md` | `250e60d61b1a5aef06b357d1d5160ddb76e9335d` | sanitizado |
| `util/ia_orquestrator/examples/config.example.yaml` | `orchestration/ia_orquestrator/examples/config.example.yaml` | `1ac87ceaab7c570b6fce7fce61f23882d47eca21` | sanitizado |
| `util/ia_orquestrator/examples/cursor/agent.mdc` | `orchestration/ia_orquestrator/examples/cursor/agent.mdc` | `a1c5f89032efc3efaa548c4a62f04c18c64720a0` | igual |
| `util/ia_orquestrator/examples/cursor/executor.mdc` | `orchestration/ia_orquestrator/examples/cursor/executor.mdc` | `14a60eda403c3222d0b778e7f26ab64a87c3fb57` | igual |
| `util/ia_orquestrator/examples/cursor_chat_loop.sh` | `orchestration/ia_orquestrator/examples/cursor_chat_loop.sh` | `98647999403b08f8a02769d76653b9edbbaeedff` | igual |
| `util/ia_orquestrator/examples/demo/SMOKE_GITHUB.md` | `orchestration/ia_orquestrator/examples/demo/SMOKE_GITHUB.md` | `dcd7d2621f64547e1e9b8ab3c0ae9b18e3d89c8c` | sanitizado |
| `util/ia_orquestrator/examples/linux/ia-orchestrator-worker.service.example` | `orchestration/ia_orquestrator/examples/linux/ia-orchestrator-worker.service.example` | `a597f72a4a8a63167eb7231cedd372385d3e1e5b` | igual |
| `util/ia_orquestrator/examples/macos/launchd.ia-orchestrator.plist.example` | `orchestration/ia_orquestrator/examples/macos/launchd.ia-orchestrator.plist.example` | `dbeb1b53bf59a38a7531ba5f4136c9a2706d929b` | igual |
| `util/ia_orquestrator/examples/simulated_executor.py` | `orchestration/ia_orquestrator/examples/simulated_executor.py` | `a4714e4dbf72aadcda1640a3bff3241a45683423` | igual |
| `util/ia_orquestrator/pyproject.toml` | `orchestration/ia_orquestrator/pyproject.toml` | `d07cd4ae927de0a99e719239c1dacbd3a3fc319b` | igual |
| `util/ia_orquestrator/requirements.lock` | `orchestration/ia_orquestrator/requirements.lock` | `261d81027c0b1091554dd48b6340b1c676f1f44d` | igual |
| `util/ia_orquestrator/schemas/executor_io_v1.json` | `orchestration/ia_orquestrator/schemas/executor_io_v1.json` | `57ea66afababa1af612f0a67f7361a6c2e161dc7` | igual |
| `util/ia_orquestrator/schemas/message_v1.json` | `orchestration/ia_orquestrator/schemas/message_v1.json` | `50b80dacc8cf9fe671f11900f8ae8bde949d81f2` | igual |
| `util/ia_orquestrator/schemas/model_decision_v1.json` | `orchestration/ia_orquestrator/schemas/model_decision_v1.json` | `2e1a154f793dbd280807fdea5458f18cf605d90e` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/__init__.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/__init__.py` | `3537d8bba0e1848d4e202dd965666a8545ee035c` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/__main__.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/__main__.py` | `35b3bcef1e0dcf4af9728a862fb1438489ae82fd` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/adapters/__init__.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/adapters/__init__.py` | `50292d9bc300a64258a622822ae7a1029c3f0627` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/adapters/executor.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/adapters/executor.py` | `36cfa9b621c962568fcfe41e6074b95c8d4f1a0c` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/adapters/model.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/adapters/model.py` | `2d837a4e46a508eb8169f3ce1deeeaa16b9c8100` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/alerts.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/alerts.py` | `0f3e153885cfd58e629691f6fe2579f0c57fe629` | sanitizado |
| `util/ia_orquestrator/src/ia_orchestrator/cli.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/cli.py` | `314f601b91db61de14937c8e550cbb76b3b16f4e` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/config.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/config.py` | `0926adf68e247d2d0b2b0cf4041a868c54bd245a` | sanitizado |
| `util/ia_orquestrator/src/ia_orchestrator/context.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/context.py` | `200a098c127d98b78ea857314828eea1e6c0f17a` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/demo.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/demo.py` | `6f4d34603178e6ecff921c3e711a36c1b3db3696` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/doctor.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/doctor.py` | `efc67d875464b1a90fec251593c2b8b464fab051` | sanitizado |
| `util/ia_orquestrator/src/ia_orchestrator/errors.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/errors.py` | `3ed370610f69a7176f9575a7eebad52dfec20a18` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/get_file.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/get_file.py` | `d4ec305d3d7ae5828c00e318518d79ff7d379b95` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/issue_status.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/issue_status.py` | `66023cb1a6607fa6443fc22e040c670d458cd0d9` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/keep_awake.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/keep_awake.py` | `c4ec36e145007495e9c2de9ebe47ab807c709788` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/locks.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/locks.py` | `a8a3a814b5407430d032dc966415cccc942db7c4` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/loop.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/loop.py` | `9aac4a797e7d903d35fd39ec916ac81acfcff712` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/persistence.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/persistence.py` | `57965596d2b5d6f84429a9f30fcff3999ea5d4d6` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/policy.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/policy.py` | `45b58dfb68aa774b1593cee1250b38ea4002e1b6` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/protocol.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/protocol.py` | `aa6b07f49d41b17c69e6417f0016de0819855ccd` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/publish.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/publish.py` | `153dc4714a635805df6e47022b49ecb6561aad99` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/py.typed` | `orchestration/ia_orquestrator/src/ia_orchestrator/py.typed` | `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/send_file.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/send_file.py` | `943a98aebd8d98e9c0ac5cfe5e6bb174ad881897` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/state.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/state.py` | `fc286a396785c21fd056f3845f291d966712b7c4` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/transport.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/transport.py` | `18c62e7a685612904e59a6517313e121e28c69dc` | igual |
| `util/ia_orquestrator/src/ia_orchestrator/workers.py` | `orchestration/ia_orquestrator/src/ia_orchestrator/workers.py` | `972c61046771a95c7c5ffc87396b56909916d5fb` | igual |
| `util/ia_orquestrator/tests/helpers.py` | `orchestration/ia_orquestrator/tests/helpers.py` | `a0a660ab06e7b994b9fbc408cb5ebf0b2a3c1353` | igual |
| `util/ia_orquestrator/tests/test_agent_role.py` | `orchestration/ia_orquestrator/tests/test_agent_role.py` | `7ba6c5d0562492e7e55f16d7538387ede7459bef` | igual |
| `util/ia_orquestrator/tests/test_alerts.py` | `orchestration/ia_orquestrator/tests/test_alerts.py` | `94bdaf9ca5dc7e9a72c627ef888996a93c3afad0` | igual |
| `util/ia_orquestrator/tests/test_cli.py` | `orchestration/ia_orquestrator/tests/test_cli.py` | `bc79714d04dab03fe6b52ec4ebfbfa88e30ce373` | igual |
| `util/ia_orquestrator/tests/test_decision_block.py` | `orchestration/ia_orquestrator/tests/test_decision_block.py` | `e9926fb149831e5c4b33c82c9ddadbab60f9994f` | igual |
| `util/ia_orquestrator/tests/test_e2e_offline.py` | `orchestration/ia_orquestrator/tests/test_e2e_offline.py` | `7e8a5c807f804bb774a5c63a3a96453d1a5ba51f` | igual |
| `util/ia_orquestrator/tests/test_get_file.py` | `orchestration/ia_orquestrator/tests/test_get_file.py` | `da53499c8fcebc240247081897abe528e46fac07` | igual |
| `util/ia_orquestrator/tests/test_isolation.py` | `orchestration/ia_orquestrator/tests/test_isolation.py` | `3c2c49478a1e93554963468cb58c789301c20f8a` | igual |
| `util/ia_orquestrator/tests/test_keep_awake.py` | `orchestration/ia_orquestrator/tests/test_keep_awake.py` | `4af3b46c1b220a7baaa35b33c0f8f12f244624f9` | igual |
| `util/ia_orquestrator/tests/test_locks_context.py` | `orchestration/ia_orquestrator/tests/test_locks_context.py` | `ace6b9d9a434a20f1a9c4dbfe479c9bfc8697501` | igual |
| `util/ia_orquestrator/tests/test_loop.py` | `orchestration/ia_orquestrator/tests/test_loop.py` | `67f83d59a0417980a60a37d701705f019d793ef9` | igual |
| `util/ia_orquestrator/tests/test_policy.py` | `orchestration/ia_orquestrator/tests/test_policy.py` | `c4660098506ac13f16bcafceb7d3f9e4ec143b4a` | igual |
| `util/ia_orquestrator/tests/test_protocol.py` | `orchestration/ia_orquestrator/tests/test_protocol.py` | `7a49c1a40642243dc20ff55b0266cee713b09141` | igual |
| `util/ia_orquestrator/tests/test_publish.py` | `orchestration/ia_orquestrator/tests/test_publish.py` | `67d10e64eb0a7e181ee42a061026502e192bdef6` | igual |
| `util/ia_orquestrator/tests/test_question_resume.py` | `orchestration/ia_orquestrator/tests/test_question_resume.py` | `d6717e14b61519ef8f4773f8e8fea208fb6cb2a7` | igual |
| `util/ia_orquestrator/tests/test_recovery.py` | `orchestration/ia_orquestrator/tests/test_recovery.py` | `1afcf362152fccad29d10731dca020c1962bd4fa` | igual |
| `util/ia_orquestrator/tests/test_send_file.py` | `orchestration/ia_orquestrator/tests/test_send_file.py` | `baee958e316202afbb625a12c4ddbd29ec3df63a` | igual |
| `util/ia_orquestrator/tests/test_state.py` | `orchestration/ia_orquestrator/tests/test_state.py` | `e5db696075db47dc8045129f9da5fc6baf837200` | igual |
| `util/ia_orquestrator/tests/test_status.py` | `orchestration/ia_orquestrator/tests/test_status.py` | `e766bb6f852c80cc87de875d047afded749bf179` | igual |
| `util/ia_orquestrator/tests/test_subprocess_executor.py` | `orchestration/ia_orquestrator/tests/test_subprocess_executor.py` | `34c66d2ed53906597435cb7c449e5f661034c19d` | igual |
| `util/ia_orquestrator/tests/test_sync.py` | `orchestration/ia_orquestrator/tests/test_sync.py` | `ad4e095949aa7acb49b5d8394f5c880e3b3c65bb` | igual |

Arquivos de destino: 68. Iguais à origem: 56. Sanitizados: 12. Novos: 0.

## Exclusões

Não exportar, e não hashear como conteúdo público:

- `util/ia_orquestrator/.env.example`
- `util/ia_orquestrator/docs/ALERTS_DISCORD.md`
- `util/discord_msg/` e qualquer webhook, token ou `config.yaml` privado fora deste pacote
- SQLite, `~/.ia_orchestrator/`, caches, `__pycache__`, `*.egg-info` e o histórico git da repo privada

## Varredura de segredo

No destino, não há `parents[3]`, não há caminho `/Users/rafars` e não há token `ghp_` ou `github_pat_` gravado. Os testes `test_alerts.py` usam URLs fictícias `https://discord.com/api/webhooks/9/secret-token` e `https://discord.com/api/webhooks/1/abc` para provar que a redação as esconde. O exemplo launchd usa `/Users/EXEMPLO`. Nomes de variáveis (`GITHUB_TOKEN_TCS_PUB`, `DISCORD_WEBHOOK_URL`, `LLM_API_KEY`) aparecem sem valores.

