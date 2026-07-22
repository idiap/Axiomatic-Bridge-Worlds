# Axiomatic Bridge Worlds

Axiomatic Bridge Worlds (ABW) is a benchmark for evaluating whether a model can
invent a useful missing predicate, lemma, invariant, quotient, normal form, or
theory morphism. This repository contains the deterministic generator, formal
DSL, model adapters, scorer, and the dataset used by the public experiments.

The benchmark has seven families:
`predicate_invention`, `lemma_invention`, `analogy`, `invariant`, `quotient`,
`normal_form`, and `multi_step`.

## Quick Start

Use Python 3.9+ and [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run python scripts/install_seeded_v2_dataset.py
```

The archive installs to `dataset/abw-formal-nl-core/` and contains 35 `dev`
worlds plus 350 `test_public` worlds. Validate the installation with:

```bash
uv run abw validate-world \
  --world dataset/abw-formal-nl-core/test_public/predicate_invention/abw_test_public_0000
```

## Run A Model

The included adapter supports OpenAI-compatible APIs, Ollama, and Azure ML
score endpoints:

```bash
export ABW_MODEL_BASE_URL=https://provider.example/v1
export ABW_MODEL_ID=model-id
export ABW_MODEL_API_KEY=...

uv run python scripts/run_experiment.py \
  --dataset-root dataset/abw-formal-nl-core \
  --split test_public \
  --limit 350 \
  --model-label model-id \
  --prompt-condition zero_shot_formal_direct \
  --target-command uv \
  --target-command run \
  --target-command python \
  --target-command scripts/model_target.py
```

`ABW_MODEL_API_KEY` is optional for unauthenticated local endpoints. Results and
the run manifest are JSON. The condition and exemplar bank are sent to the
adapter in every request and must be acknowledged before a candidate is scored.

See [EVALUATION.md](EVALUATION.md) for Stage 1, Stage 2, few-shot, robustness,
and C0-C6 commands.

## Public Interfaces

- [Dataset card](dataset/README.md): dataset contents and public/private files
- [Evaluation protocol](docs/benchmark_task.md): adapter request, response, and
  result JSON
- [ABW DSL](docs/dsl.md): accepted formal candidate syntax
- [Scripts](scripts/README.md): supported evaluation entry points

Do not expose private gold or scoring files to the evaluated model. The local
runner provides a cooperative interface, not filesystem isolation; use a
stripped export or separate inference and scoring environments for blind runs.

## Development

```bash
uv sync --extra test
uv run --extra test pytest
```

Optional finite-model diagnostics use `uv sync --extra validation`. See
[CONTRIBUTING.md](CONTRIBUTING.md) for maintenance commands.

ABW is released under the MIT License. Citation metadata is in
[CITATION.cff](CITATION.cff). See also [Security](SECURITY.md),
[Code of Conduct](CODE_OF_CONDUCT.md), and [Changelog](CHANGELOG.md).
