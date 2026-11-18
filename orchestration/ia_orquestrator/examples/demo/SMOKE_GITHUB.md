# Smoke test GitHub real

Não execute isto contra repositórios de terceiros. Só com `--repo` e token **autorizados**.

```bash
cd orchestration/ia_orquestrator
python3 -m pip install -e .
export IA_ORCHESTRATOR_HOME="$HOME/.ia_orchestrator"
ia-orchestrator bootstrap --project teste --repo OWNER/REPO --workspace /caminho/local --force
# edite allowed_senders e token_env no YAML gerado
export GITHUB_TOKEN_TESTE=...          # nome = github.token_env
# opcional, se orchestrator.mode=api:
export LLM_API_KEY=...
ia-orchestrator doctor --project teste --probe
ia-orchestrator task create --project teste --prompt-file /tmp/prompt.md --title "smoke ia-orchestrator"
ia-orchestrator worker run --project teste --role orchestrator --once
ia-orchestrator worker run --project teste --role executor --once
ia-orchestrator task list --project teste
```

Limites baixos no YAML: `max_rounds_per_task: 2`, `model_call_timeout_seconds: 30`.
