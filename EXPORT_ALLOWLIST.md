# Public scientific release — inclusion and exclusion policy

This repository is the **minimal public scientific code package** accompanying the manuscript *An Auditable Policy-Simulation Framework for Student Dropout in Intervention-Free Data*. It is **not a fork, mirror, or checkout export** of `TCS_Students_Dropout_desenv_v2`.

**Current publication state:** The code and aggregate documentation have been publicly released. The prior statement that this repository was empty and publication was blocked described an **earlier candidate stage** and is no longer the current repository status. Historical checks and their dates remain in Git history and under `docs/a8_g2c2_*.md`.

## Include only

- `README.md`, `CITATION.cff`, `LICENSE`, `.gitignore`, this policy, and scientific reproducibility documentation.
- Entry points: `orquestrator.py` (historical staged A workflow), `g2c2_reproduction.py` (three-arm execution), `g2c2_refit_r7.py` (three-arm refit with persisted/reloaded models), and the support modules used by them.
- `src/jla/` scientific source code; `tests/` tests; `config/protocol.yaml`; `requirements.txt`, `requirements-test.txt`, `requirements.lock`.
- `baselines/` **aggregate** frozen comparison targets; `docs/` reproducibility methodology, *aggregate* verification records and dated reports.
- Lightweight independent tooling needed to reproduce the science, when it passes the same public release review.

The stable, historically frozen core code files retain their original Git blob hashes unless a scientifically justified, separately reviewed code correction is made. Documentation-only updates do not authorize changing science, baselines, tests, threshold values or hashes. Prior numeric reproducibility is documented in [R7](docs/a8_g2c2_reexecucao_e2e_modelos_persistidos.md), not inferred from a file-tree copy.

## Exclude from the public Git checkout

- **All OULAD raw CSV files, ZIP downloads, working data directories and student/enrollment-level extracts.**
- Individual predictions, scores, records or unique identifiers; fitted models (`*.joblib`); derived private figures or datasets, checkpoints, logs, and experimental outputs.
- Private manuscript revisions, reviewer correspondence, unsubmitted editorial packages or private development history.
- The private repository's `.git`, local virtual environments, credentials, `.env`, access tokens, secrets, internal webhook and agent-control configuration.
- Any files not needed to reproduce or audit aggregate scientific findings.

## Publication checks

Before changing public files, confirm the material belongs to an allowed category, cannot reveal private data/credentials, and does not introduce unsupported performance or intervention-effect claims. For **scientific code changes**, require a documented error, a narrowly scoped diff, testing, and a new numerical comparison when relevant. For **documentation changes**, verify that commands and file paths match the checked-in code and that provenance limitations remain explicit.

Current repository documentation intentionally distinguishes the older A-only staged CLI from the full A/B/B-9 workflow. The paper is **under review**, and repository availability does not imply journal acceptance.

Historical candidate allowlist Git blob identifiers and former `publication_status=BLOCKED` notes can be recovered from the previous revision in Git history; they must not be treated as the current release gate.
