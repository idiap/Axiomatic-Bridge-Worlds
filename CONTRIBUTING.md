# Contributing

Thanks for taking an interest in Axiomatic Bridge Worlds.

ABW is both a research artifact and a reusable benchmark harness, so good
contributions usually improve one of three things:

- the formal runtime or solver interfaces
- the benchmark, dataset, or JSON result surface
- the clarity and trustworthiness of the documentation

## Development Setup

ABW uses `uv` for environment and dependency management.

```bash
uv sync --extra dev
```

Install optional solver dependencies when you need the stronger diagnostic
backends:

```bash
uv sync --extra dev --extra solver
```

Install the release/build tooling when you want to verify distributable
artifacts locally:

```bash
uv sync --extra dev --extra release
```

## Common Commands

Run the default test suite:

```bash
uv run pytest
```

Run the solver-aware suite:

```bash
uv run --extra dev --extra solver pytest
```

Generate an example world:

```bash
uv run python -m abw_core generate-world --family predicate_invention --seed 7 --output examples/tiny_world
```

Install the canonical dataset and inspect the generic evaluation CLI:

```bash
uv run python scripts/install_seeded_v2_dataset.py
uv run python scripts/run_experiment.py --help
```

```bash
uv run python -m abw_core run-benchmark \
  --dataset dataset/abw-formal-nl-core \
  --target-command uv \
  --target-command run \
  --target-command python \
  --target-command scripts/example_target_system.py \
  --split dev \
  --limit 10 \
  --output artifacts/abw_benchmark_results.json
```

Build and validate the source distribution and wheel:

```bash
make dist-check
```

## Contribution Guidelines

- Keep changes scoped to the behavior you are modifying.
- Add or update tests when runtime behavior changes.
- Update docs, examples, and configs when user-facing interfaces move.
- Prefer cross-platform Python or standard-library solutions over shell-specific
  tricks when implementing automation.
- Preserve deterministic behavior unless the change is explicitly about
  generation diversity or search.
- Make benchmark changes auditable by recording motivation, regeneration notes,
  and validation evidence in the change discussion.

## Dataset And Benchmark Changes

Changes to generation presets, scoring weights, or packaged artifact contracts
affect benchmark meaning, not only implementation details.

When you modify those surfaces:

- explain the motivation in the merge request
- update the relevant docs under [`docs`](docs)
- mention whether existing generated datasets or JSON results need regeneration

## Release Metadata

Before cutting a disclosure archive, keep the REUSE metadata intact:

- use SPDX headers for source files that can carry comments
- use `REUSE.toml` annotations for documentation, examples, JSON, lock files,
  placeholders, and other files where visible headers would distract from the
  content
- keep full license texts under `LICENSES/` using SPDX identifiers, for example
  `LICENSES/MIT.txt`
- run `reuse download --all` and `reuse lint` when `reuse-tool` is available

## Pull Request Checklist

Before opening a merge request, make sure you have:

- run the relevant tests locally
- updated documentation for any changed CLI, file format, or metric behavior
- called out platform assumptions and optional solver requirements
- avoided committing unrelated dataset churn unless it is part of the change
