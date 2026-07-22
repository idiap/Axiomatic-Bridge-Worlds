# Model Evaluation

All public experiments use the tracked `abw-formal-nl-core.zip` snapshot. It
contains 35 `dev` worlds and 350 `test_public` worlds across the seven ABW
families.

## Install The Dataset

```bash
uv run python scripts/install_seeded_v2_dataset.py
```

`run_experiment.py` validates every selected world before it sends any model
request. Use `validate_world.py --world PATH` for a one-world check.

## Configure Any Model

The included adapter supports OpenAI-compatible APIs, Ollama, and Azure ML
score endpoints. Configure it through neutral environment variables:

```bash
export ABW_MODEL_BASE_URL=https://provider.example/v1
export ABW_MODEL_ID=model-id
export ABW_MODEL_API_KEY=...
export ABW_MODEL_MAX_TOKENS=8000
```

`ABW_MODEL_API_KEY` may be omitted for an unauthenticated local endpoint. A
custom adapter may be substituted anywhere below if it reads one ABW request
from stdin and writes a JSON object containing `candidate` to stdout. When the
request declares an `evaluation` contract, the adapter must echo its
`prompt_condition` and `exemplar_bank` in response `metadata`.

## Stage 1

Run each candidate model on the same 35-world `dev` slice, changing only its
endpoint/model settings and `--model-label`:

```bash
uv run python scripts/run_experiment.py \
  --dataset-root dataset/abw-formal-nl-core \
  --split dev \
  --limit 35 \
  --model-label candidate-model \
  --prompt-condition zero_shot_formal_direct \
  --target-command uv \
  --target-command run \
  --target-command python \
  --target-command scripts/model_target.py
```

Compare the aggregate `summary.primary_score` values in the generated JSON
outputs. No provider or model is selected by repository code.

## Stage 2 Zero-Shot

Use `--split test_public --limit 350`. The three public contracts are:

| Contract | Prompt condition | Model output |
| --- | --- | --- |
| Formal Direct (FD) | `zero_shot_formal_direct` | ABW DSL |
| Natural-Language Direct (NLD) | `zero_shot_natural_language_direct` | controlled NL, deterministically converted to ABW DSL |
| Cross-Track (CT) | `zero_shot_cross_track_nl_to_formal` | ABW DSL from NL input |

Supply the selected condition once to `run_experiment.py`. The runner forwards
it in every benchmark request and verifies the adapter's acknowledgement before
scoring. Give each condition a distinct `--model-label` or explicit `--output`
path.

## Stage 2 Few-Shot

Few-shot uses exactly two same-family examples drawn from `dev`; evaluation
worlds come only from `test_public`. The committed banks are:

| Contract | Prompt condition | Exemplar bank |
| --- | --- | --- |
| FD | `family_few_shot_formal_direct` | `configs/formal_direct_few_shot_exemplars_seeded_v2.json` |
| NLD | `family_few_shot_natural_language_direct` | `configs/natural_language_direct_few_shot_exemplars_seeded_v2.json` |
| CT | `family_few_shot_cross_track_nl_to_formal` | `configs/cross_track_few_shot_exemplars_seeded_v2.json` |

Pass the condition and bank to the runner:

```bash
uv run python scripts/run_experiment.py \
  --dataset-root dataset/abw-formal-nl-core \
  --split test_public \
  --limit 350 \
  --model-label candidate-model-fd-few-shot \
  --prompt-condition family_few_shot_formal_direct \
  --exemplar-bank configs/formal_direct_few_shot_exemplars_seeded_v2.json \
  --target-command uv \
  --target-command run \
  --target-command python \
  --target-command scripts/model_target.py
```

Rebuild a bank with `build_few_shot_exemplar_bank.py`; keep `--split dev` and
`--exemplars-per-family 2` to preserve the leakage-control contract.

## Robustness And C0-C6

`generate_perturbed_dataset.py` creates one semantics-preserving perturbed
copy. `robustness_plan.py` writes model-agnostic generation and evaluation
commands for paired original/perturbed runs. Both accept the same target
command used above.

```bash
uv run python scripts/robustness_plan.py \
  --base-dataset-root dataset/abw-formal-nl-core \
  --prompt-condition zero_shot_formal_direct \
  --target-command uv \
  --target-command run \
  --target-command python \
  --target-command scripts/model_target.py
```

Build the paired C0-C6 dataset from the same `test_public` source and evaluate
the resulting root with `run_experiment.py` using the intended
`--prompt-condition`:

```bash
uv run python scripts/build_paired_difficulty_dataset.py --overwrite
```

Every evaluation writes JSON results with world-level records and aggregate
metrics plus a JSON manifest containing the exact dataset slice and target
command. Paper-specific tables and plots are intentionally not part of the
public evaluation scripts.
