# TCS Students Dropout — code and numerical reproduction package

**Companion code for:** *An Auditable Policy-Simulation Framework for Student Dropout in Intervention-Free Data* (da Silva, Eicher, and Longo; manuscript under review).

This is the **public, minimal scientific repository** for the paper. It contains executable source code, frozen **aggregate** comparison targets, configurations, automated tests, and a documented procedure for reconstructing the analyses from the [Open University Learning Analytics Dataset (OULAD)](https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset). It is **not** a mirror of the private development repository. Manuscript drafts, private models, raw student data, individual predictions and internal editorial records are not distributed here.

The paper combines (RQ1) calibrated weekly discrete-time withdrawal hazard estimation, (RQ2) **hypothetical**, fixed-model hazard-shock and lagged engagement-state scenarios, and (RQ3) **descriptive** female-minus-male modeled survival-gap comparisons. These calculations **do not measure causal intervention effects, demonstrated dropout prevention, or equity benefits**.

## Start here

- [Paper reproduction guide](docs/PAPER_REPRODUCIBILITY.md): end-to-end commands, model arms A/B/B-9, file-to-method mapping, numerical checks and their limits.
- [Study configuration](config/protocol.yaml): source, seed, horizons, scenario parameters and model settings.
- [Three-arm reproduction runner](g2c2_reproduction.py): fits A, B and B-9 using the *approved* execution path; the separate [R7 runner](g2c2_refit_r7.py) persists/reloads newly fitted models and compares them with an earlier external run.
- [Original staged runner](orquestrator.py): stages 00–10 for the earlier last-VLE workflow; **not by itself** the complete three-arm analysis in the revised paper.
- [Scientific modules](src/jla/), [offline tests](tests/), [frozen aggregate targets](baselines/) and [historical verification reports](docs/).
- [Publication and exclusion policy](EXPORT_ALLOWLIST.md).

## Install and inspect without running OULAD

The recorded independent run used Python **3.14.3**, NumPy **2.4.4**, pandas **2.3.3**, scikit-learn **1.8.0**, and joblib **1.5.3**. Check `requirements.lock` before reproducing and do not change dependency versions silently.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python g2c2_reproduction.py --plan
.venv/bin/python orquestrator.py --help
```

These commands do **not** fit models or download OULAD. The tests are fixture-based; they do not substitute for rerunning the real dataset.

## Recreate the paper's three follow-up arms

Obtain the official OULAD archive from the UCI source above and extract the seven CSV files into **one directory outside this repository**. Keep all datasets and outputs outside the checkout. On the same validated data extraction, execute the two stages below (see the detailed guide for strict source-hash requirements):

```bash
DATA=/path/outside/repo/oulad_csv
R1=/path/outside/repo/three_arm_run_1
R7=/path/outside/repo/three_arm_run_7

# Train/evaluate A, B, B-9 and save original outputs privately.
.venv/bin/python g2c2_reproduction.py --run-approved --data-dir "$DATA" --output-dir "$R1"

# Independently refit all arms, persist and reload models, then compare
# against both the frozen aggregate targets and the preceding R1 scores.
.venv/bin/python g2c2_refit_r7.py --data-dir "$DATA" --output-dir "$R7" --r1-private "$R1/private"
```

Use **new, empty output directories**. The R7 gate requires the **exact seven raw CSV SHA-256 values recorded by its code**, plus a previous R1 private score directory. Its refusal of a differently packaged extraction must not be bypassed by modifying source files, hashes or frozen targets. The initial R1 runner records output but does **not** by itself certify every later interval and persisted-model gate.

The historical single-arm runner can separately be used with `orquestrator.py --all --allow-download --output-dir /path/outside/repo/another_clean_run` (see `--help`); it is **not** a replacement for the two-step A/B/B-9 procedure.

## Documented numerical results and scope

The test panel contains **232,509 / 278,056 / 277,979** enrollment-week rows in arms **A / B / B-9**. Weekly test ROC AUC is **0.8142 / 0.7872 / 0.7873** and week-8-to-18 landmark IPCW AUC is **0.7024 / 0.6609 / 0.6609**, respectively. At week 18, the observed risk-set sizes are **6,369 / 7,337 / 7,335** enrollments. These populations and observation contracts are **different across arms**; cross-arm metrics are sensitivity analyses, not paired intervention effects.

The prior public R7 execution [documented here](docs/a8_g2c2_reexecucao_e2e_modelos_persistidos.md) recorded agreement for **91 computable numerical cells, 12 AUC interval endpoints and 12 policy-contrast checks** within the prespecified absolute tolerance of `1e-9`. Eight deliberately unavailable cells remain blank. This establishes **internal numerical reproducibility under the recorded inputs and rules**—not an external validation, new randomized intervention study, or journal acceptance. The earlier [R1 report](docs/a8_g2c2_comparacao_dev_pub.md) documents discrepancies that were subsequently investigated; read the dated R7 result rather than treating all historical gate labels as current.

The original staged comparison also has legacy status flags such as `publication_status=BLOCKED` and pending raw-input reference hashes. Those are **workflow/checkpoint metadata**, not a decision of the *Journal of Learning Analytics* or proof of an intervention effect. We do not claim the historical `--compare-baseline` CLI was subsequently rerun with an updated fingerprint and issued `PASS_REPRODUCTION`. For details see the [reproduction guide](docs/PAPER_REPRODUCIBILITY.md).

## Data, license, citation and safety

OULAD: Kuzilek, Hlosta and Zdrahal (2017), [UCI dataset 349](https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset), **CC BY 4.0**. The code is under the repository [MIT license](LICENSE), which does not relicense OULAD. Please cite the code repository (GitHub's *Cite this repository* facility) and the associated manuscript when available.

Do **not** commit data, models, per-student records, scores, downloaded ZIP files, run artifacts, credentials or unreviewed exports. Outputs and checkpoints belong in external, private directories. Consult [`EXPORT_ALLOWLIST.md`](EXPORT_ALLOWLIST.md) before changes to public content.
