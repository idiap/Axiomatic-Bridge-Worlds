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

## 2. Install or regenerate the dataset

```bash
# Install the tracked 5-dev + 50-public-test worlds per family archive.
uv run python scripts/install_seeded_v2_dataset.py

# Or regenerate it from the only release preset.
uv run python -m abw_core generate-dataset --config configs/paper_core_seeded_v2.yaml \
  --output artifacts/paper_core_seeded_v2_regenerated
```

Export a public-only copy (private bridge and hidden goals stripped) before
handing a dataset to a target system:

```bash
uv run abw export-public-dataset --dataset dataset/abw-formal-nl-core --output artifacts/abw_public
```

## 3. Evaluate a model

`run-benchmark` sends one request per world, expects an ABW candidate back, and
writes JSON output with the dataset-level `primary_score` plus per-metric
means.
Repeat `--target-command` once per argv token (use `--target-command=-m` for
tokens starting with `-`). The full contract is in
[benchmark_task.md](benchmark_task.md).

```bash
uv run abw run-benchmark \
  --dataset dataset/abw-formal-nl-core \
  --target-command uv --target-command run --target-command python \
  --target-command scripts/model_target.py \
  --split test_public --limit 10 \
  --output artifacts/abw_results.json
```

`scripts/model_target.py` adapts any OpenAI-compatible model via
`ABW_MODEL_API_KEY`, `ABW_MODEL_BASE_URL`, and `ABW_MODEL_ID` (see the README).
To run a model end to end in one step -- validate, run, write JSON outputs, and
write a manifest -- use `scripts/run_experiment.py`:

```bash
uv run python scripts/run_experiment.py \
  --dataset-root dataset/abw-formal-nl-core --model-label my_model \
  --target-command uv --target-command run --target-command python \
  --target-command scripts/model_target.py
```

## 4. Robustness and difficulty

**Robustness** measures whether a score survives semantics-preserving rewrites
(`alpha_renaming`, `axiom_order_shuffle`, `nl_paraphrase`, `distractor_insertion`).
Make a perturbed copy and plan the paired runs:

```bash
uv run python scripts/generate_perturbed_dataset.py \
  --source dataset/abw-formal-nl-core --output artifacts/abw_perturbed/alpha_renaming \
  --perturbation alpha_renaming

uv run python scripts/robustness_plan.py \
  --base-dataset-root dataset/abw-formal-nl-core \
  --perturbed-dataset-root artifacts/abw_perturbed \
  --results-dir artifacts/abw_robustness \
  --target-command uv --target-command run --target-command python \
  --target-command scripts/model_target.py \
  --output artifacts/abw_robustness/plan.json

```

The plan records the original and perturbed JSON result paths, making paired
downstream analysis independent of paper-specific tooling.

**Difficulty (C0-C6)** probes the same source worlds under controlled
public-shape changes. Build the paired dataset, then run `run-experiment.py` on
the resulting root:

```bash
uv run python scripts/build_paired_difficulty_dataset.py --overwrite
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

## 6. Benchmark Outputs

`run-benchmark` writes machine-readable JSON outputs under `artifacts/` or
another local output path. Keep generated benchmark outputs out of the
disclosure source unless a specific reference snapshot is intentionally added.
