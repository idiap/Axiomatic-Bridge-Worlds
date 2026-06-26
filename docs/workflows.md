# Workflows

ABW is a framework for evaluating **model creativity** — whether a system can
invent the missing bridge concept (a predicate, lemma, or morphism) that makes
later goals provable, not just chain existing facts. These are the command
recipes for running that evaluation end to end.

All commands run from `theory-creation/` through `uv run …`. The `abw` console
script equals `python -m abw_core`. For the shortest path, see the
[README](../README.md); for the scoring details, see [Scoring](scoring.md).

## 1. Generate and inspect a world

```bash
uv run abw generate-world --family predicate_invention --seed 7 --output examples/tiny_world
uv run abw inspect-world  --world examples/tiny_world
uv run abw validate-world --world examples/tiny_world
```

## 2. Generate a dataset

```bash
# 14-world all-family smoke dataset
uv run python scripts/generate_dataset.py --output artifacts/abw_smoke_dataset

# paper-core reproduction (5 dev + 50 public-test per family; or: make paper-core)
uv run python scripts/generate_dataset.py --config configs/paper_core.yaml --output datasets/paper_core
```

Export a public-only copy (private bridge and hidden goals stripped) before
handing a dataset to a target system:

```bash
uv run abw export-public-dataset --dataset datasets/paper_core --output artifacts/abw_public
```

## 3. Evaluate a model

`run-benchmark` sends one request per world, expects an ABW candidate back, and
writes a report with the dataset-level `primary_score` plus per-metric means.
Repeat `--target-command` once per argv token (use `--target-command=-m` for
tokens starting with `-`). The full contract is in
[benchmark_task.md](benchmark_task.md).

```bash
uv run abw run-benchmark \
  --dataset datasets/paper_core \
  --target-command uv --target-command run --target-command python \
  --target-command scripts/generic_model_target.py \
  --split test_public --limit 10 \
  --output artifacts/abw_report.json
```

`scripts/generic_model_target.py` adapts any OpenAI-compatible model via
`ABW_MODEL_API_KEY`, `ABW_MODEL_BASE_URL`, and `ABW_MODEL_ID` (see the README).
To run a model end to end in one step — validate, run, render a report, write a
manifest — use `scripts/run_experiment.py`:

```bash
uv run python scripts/run_experiment.py \
  --skip-generation --dataset-root datasets/paper_core --model-label my_model \
  --target-command uv --target-command run --target-command python \
  --target-command scripts/generic_model_target.py
```

## 4. Robustness and difficulty

**Robustness** measures whether a score survives semantics-preserving rewrites
(`alpha_renaming`, `axiom_order_shuffle`, `nl_paraphrase`, `distractor_insertion`).
Make a perturbed copy, plan the paired runs, then summarize the drops:

```bash
uv run python scripts/generate_perturbed_dataset.py \
  --source datasets/paper_core --output artifacts/abw_perturbed/alpha_renaming \
  --perturbation alpha_renaming

uv run python scripts/robustness_plan.py \
  --base-dataset-root datasets/paper_core \
  --perturbed-dataset-root artifacts/abw_perturbed \
  --report-dir artifacts/abw_robustness \
  --target-command uv --target-command run --target-command python \
  --target-command scripts/generic_model_target.py \
  --output artifacts/abw_robustness/plan.json

uv run python scripts/robustness_summary.py \
  --plan artifacts/abw_robustness/plan.json \
  --output artifacts/abw_robustness/summary.json
```

**Difficulty (C0-C6)** probes the same source worlds under controlled public-shape
changes. Build the paired dataset, run `run-benchmark` on it, then summarize by
shape:

```bash
uv run python scripts/build_paired_difficulty_dataset.py \
  --all-families --examples-per-family 1 \
  --output datasets/paired_difficulty_shapes --overwrite

uv run python scripts/difficulty_shape_summary.py \
  --report artifacts/abw_c0_c6_report.json \
  --output artifacts/abw_c0_c6_summary.json
```

## 5. Diagnostics

Inspect the bounded countermodel for a goal that does not hold, or score with a
solver backend for stronger finite-model checks:

```bash
uv run abw countermodel-goal --world examples/tiny_world --goal hidden_step_2
uv run abw score-candidate --world examples/tiny_world \
  --candidate examples/predicate_invention/gold_candidate.abw --prover-backend z3   # or: cvc5
```

An interactive **refinement session** lets a system explore a world (public-only)
under a query budget before submitting, scoring its `exploration_efficiency_score`:

```bash
uv run abw start-session  --world examples/tiny_world --output artifacts/abw-session
uv run abw session-query  --session artifacts/abw-session --kind examples \
  --candidate examples/predicate_invention/gold_candidate.abw --predicate PairStable --limit 3
uv run abw finish-session --session artifacts/abw-session \
  --candidate examples/predicate_invention/gold_candidate.abw
```

Sessions support `validate`, `equivalence`, `examples`, and `countermodel`
queries; hidden-goal scoring happens only at submission. See
[Scoring](scoring.md).

## 6. Reports

Render a benchmark report to LaTeX (add `--fragment` for an `\input{}`-able
snippet, or pass multiple `--report`/`--name` pairs to compare runs):

```bash
uv run abw render-benchmark-report \
  --report artifacts/abw_report.json --output artifacts/abw_report.tex
```

`run-benchmark` can also emit the LaTeX sidecar inline via `--latex-output`. The
`make benchmark-report*` targets wrap these flows.
