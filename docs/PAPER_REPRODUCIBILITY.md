# Reproducing the JLA student-dropout paper

**Manuscript:** *An Auditable Policy-Simulation Framework for Student Dropout in Intervention-Free Data* (da Silva, Eicher & Longo, 2026; under review).

This is a **numerical reproduction** package for observational OULAD analyses. It does not provide real intervention outcomes or identify causal effects. The public repository was constructed separately from the private development workflow; agreement is assessed by scientific quantities and declared tolerances, **not binary identity of files**.

## 1. Data, cohort, and observation contracts

Use the official [Open University Learning Analytics Dataset](https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset) and its seven CSVs: `studentInfo.csv`, `studentRegistration.csv`, `studentVle.csv`, `studentAssessment.csv`, `assessments.csv`, `courses.csv`, and `vle.csv`. The source is **CC BY 4.0**; cite Kuzilek, Hlosta, and Zdrahal (2017). Keep source data and outputs in directories **outside the repository**.

The cohort has **32,593 enrollments** from **28,785 students**, over **seven modules** and **22 presentations**. A dated withdrawal event requires administrative status `Withdrawn` and a valid nonnegative post-start unregistration date: **7,387** of the **10,156** administrative withdrawals meet this definition; **2,769** are treated as right-censored non-events under the adopted analytical contract.

The analysis uses a stratified **student-disjoint** partition (22,855 training / 9,738 test enrollments). Arm **A** ends non-event follow-up at last recorded VLE; arm **B** extends Pass/Fail/Distinction records through nominal presentation end; arm **B-9** excludes nine Fail enrollments with discordant unregistration dates (seven training, two test). Each arm fits and calibrates a separate model. B-9 has **9,736 test enrollments**.

For target week `t`, `total_clicks_lag` is the **previous week's total clicks**, not clicks accumulated over the full enrollment history. The model does not use same-week activity to predict the event in that week.

## 2. Exact source and environment requirements

Recorded R7 environment: Python **3.14.3**; NumPy **2.4.4**, pandas **2.3.3**, scikit-learn **1.8.0**, joblib **1.5.3**. Dependency declarations are `requirements.txt`, `requirements.lock` and `requirements-test.txt`. Check pins and platform compatibility before reproducing.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python g2c2_reproduction.py --plan
.venv/bin/python g2c2_reproduction.py --synthetic-proof
```

Tests and planning/synthetic proof do **not** download OULAD or fit a real-data model. The dataset must be obtained separately from the official UCI resource.

**Important:** `g2c2_refit_r7.py` performs a strict **raw SHA-256** check on **all seven CSV files**, using the observed hashes hard-coded in `EXPECTED_RAW`. The original `config/protocol.yaml` intentionally leaves historical raw-hash reference fields for `courses.csv`, `vle.csv` and the ZIP as `null`. The R7 runner's recorded exact hashes are different from saying those historical protocol references were completed. Some official OULAD repackagings can differ at the byte level even when semantically equivalent. Never modify hashes, thresholds, data or reference targets to force a pass; record and investigate a discrepancy.

## 3. Reproduce all three arms (A, B, B-9)

Extract the seven official CSV files into one external directory, with names **exactly** as listed above. The runner expects those seven CSVs **directly** under `--data-dir`, not an unextracted ZIP or a nested folder.

Use two **new and empty** external output directories:

```bash
DATA=/path/outside/checkout/oulad_csv
RUN1=/path/outside/checkout/r1_private_run
RUN7=/path/outside/checkout/r7_persisted_run

# Optional structural contract before any training.
.venv/bin/python g2c2_reproduction.py --structural-gates --data-dir "$DATA"

# R1: fit and evaluate three follow-up arms, including bootstrap outputs.
.venv/bin/python g2c2_reproduction.py --run-approved --data-dir "$DATA" --output-dir "$RUN1"

# R7: fit A/B/B-9 again, serialize models, reload them before scoring,
# then compare the new scores to R1 and numerical aggregate targets.
.venv/bin/python g2c2_refit_r7.py --data-dir "$DATA" --output-dir "$RUN7" --r1-private "$RUN1/private"
```

The last command **requires** the earlier R1 output under `"$RUN1/private"/A`, `/B`, and `/B-9`, each with `test_scores.csv`. It also checks frozen targets in `baselines/a8_g2c2_dev_targets_v2.csv` and `baselines/a8_g2c2_bootstrap_targets.csv`, persistence fingerprints, count gates, bootstrap endpoints and paired numerical agreement. The R7 runner emits `"decision": "PASS_E2E_R7"` only when **all** its conditions pass; otherwise it reports `STOP`. It refuses a nonempty R7 output directory. Neither a predicted PASS nor any fabricated old checkpoint is acceptable.

**Historical runner:** `orquestrator.py --all --allow-download --output-dir ...` implements the original staged **A-only** workflow (00–10), not all three follow-up arms. Do not present an A-only run as a reproduction of B or B-9. Its older `--compare-baseline` status is separate from R7.

## 4. What to compare

| Quantity (test panels) | A: last-VLE | B: nominal | B-9: exclude nine |
|---|---:|---:|---:|
| Enrollments | 9,738 | 9,738 | 9,736 |
| Person-week rows | 232,509 | 278,056 | 277,979 |
| Dated event rows | 2,193 | 2,193 | 2,193 |
| Weekly AUC | 0.8142 | 0.7872 | 0.7873 |
| Landmark IPCW AUC (week 8 → 18) | 0.7024 | 0.6609 | 0.6609 |
| Observed week-18 cohort `R18` | 6,369 | 7,337 | 7,335 |
| Model-implied ΔS(18): hazard shock | 0.001336 | 0.001533 | 0.001533 |
| Model-implied ΔS(18): lagged engagement state | 0.006322 | 0.007748 | 0.007749 |

These are **rounded descriptive results** drawn from the frozen aggregate targets; exact values and uncertainty endpoints are preserved in `baselines/`. The week-18 cohort is **retrospectively observed**, not an eligibility set identified prospectively; it differs between arms. The lower Brier score on B's extended panel is not evidence of a paired calibration improvement. The estimated scenarios rely on frozen predictive models and **illustrative** policy settings (`r_star=1`, two-week window, `delta=0.08`, `alpha_first=0.35`, `alpha_second=0.10`, 500 student-cluster bootstrap draws, seed 42). They do not measure prevented withdrawals or experimental treatment effects.

The approved public R7 report [records](a8_g2c2_reexecucao_e2e_modelos_persistidos.md) agreement for **91 computable numerical targets**, **12 AUC interval endpoints**, and **12 policy contrasts** at absolute tolerance `1e-9`, with **8 UNAVAILABLE** values left empty. The [first-run comparison](a8_g2c2_comparacao_dev_pub.md) preserves the earlier differences rather than rewriting history. The later bootstrap/landmark [reconciliation report](a8_g2c2_reconciliacao_final_bootstrap.md) documents their resolution. These reports show **internal computational reproducibility**, not independent external scientific validation.

## 5. Map from the paper to executable public files

| Paper element | Source files |
|---|---|
| Enrollment keys, endpoint, observed risk sets and A/B/B-9 follow-up | `src/jla/science.py`, `src/jla/g2c2.py`, `src/jla/g2c2_gates.py`, `src/jla/stage03_cohort.py` |
| Student-disjoint split and lag `t-1` | `src/jla/science.py`, `src/jla/stage04_split.py` |
| Hazard model, grouped calibration, weekly metrics | `src/jla/stage05_model.py`, `src/jla/g2c2_execute.py` |
| Landmark, IPCW and censoring | `src/jla/landmark.py`, `src/jla/stage06_censoring.py` |
| One-time recency trigger, shock and engagement-state scenarios | `src/jla/audit.py`, `src/jla/stage07_policy.py`, `src/jla/g2c2_execute.py` |
| Descriptive gender diagnostics and bootstrap | `src/jla/stage09_equity.py`, `src/jla/g2c2_execute.py` |
| Operator verification and tests | `src/jla/stage08_operator.py`, `src/jla/audit.py`, `tests/` |
| Historical staged workflow (A only) | `orquestrator.py` |
| Full A/B/B-9 reproduction, serializing/reloading newly fitted models | `g2c2_reproduction.py`, `g2c2_refit_r7.py`, `src/jla/g2c2_execute.py` |
| Immutable aggregate comparison targets and protocol | `baselines/`, `config/protocol.yaml` |

## 6. Reproduction boundaries and privacy

This repository does not distribute raw OULAD CSV/ZIP files, private model `.joblib` artifacts, enrollment-level predictions, personal identifiers, or internal development/editorial material. **Do not commit** them. Fitted artifacts and results live only in external private directories.

The raw OULAD source is CC BY 4.0, separate from the MIT-licensed code. A journal review or editorial decision is **not** encoded by flags such as `publication_status=BLOCKED`, `PASS_EDITORIAL` or old `A CONFIRMAR` metadata; these are legacy workflow states. Conversely, numeric agreement alone does not validate assumptions about censoring, predictability at a new institution, efficacy of interventions or fairness improvements.

The associated paper is **under review**; no publication date, DOI, acceptance or externally validated causal result is claimed.
