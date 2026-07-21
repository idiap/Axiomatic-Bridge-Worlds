# Scripts

This directory contains thin command-line wrappers and example adapters around
the canonical `python -m abw_core` entrypoint.

The goal is convenience, not a second runtime surface.

Paper-production, plot-rendering, provider-specific, historical
reclassification, and one-off result assembly helpers may exist in a local
working tree, but they are intentionally not part of this public script surface.

## Files In This Directory

| File | Purpose |
| --- | --- |
| `audit_dataset_diversity.py` | Audit repeated schemas, repeated public tasks, and split overlap. |
| `build_paired_difficulty_dataset.py` | Build paired C0-C6 difficulty-shape datasets from generated source worlds. |
| `difficulty_shape_summary.py` | Summarize benchmark JSON outputs by C0-C6 difficulty shape and family. |
| `export_public_dataset.py` | Export a packaged dataset with private artifacts stripped out for public-only evaluation. |
| `generate_dataset.py` | Dataset-generation entrypoint around the canonical config loader. |
| `generate_perturbed_dataset.py` | Create semantics-preserving perturbed dataset copies for robustness analysis. |
| `generic_model_target.py` | Neutral OpenAI-compatible target adapter configured through `ABW_MODEL_*` environment variables. |
| `inspect_world.py` | Convenience wrapper for world inspection (also covers NL packaging output — `abw_core.cli inspect-world` renders whichever track the world was packaged with). |
| `robustness_plan.py` | Emit model-agnostic original and perturbed `run-benchmark` commands for a robustness suite. |
| `robustness_summary.py` | Summarize paired original-minus-perturbed robustness drops from completed JSON outputs. |
| `run_benchmark.py` | Thin wrapper around one `run-benchmark` call (no dataset generation or validation). |
| `run_experiment.py` | Generate (optional), validate, and run one target model against a configured dataset; writes JSON outputs and a manifest. |
| `score_candidate.py` | Convenience wrapper for one-world candidate scoring. |
| `validate_dataset.py` | Convenience wrapper for validation checks. |
| `example_target_system.py` | Example target adapter that speaks the benchmark protocol for smoke testing. |

## Editing Guidance

- Keep wrappers thin and route them into `abw_core.cli`.
- Put real business logic in `abw_core/`, not here.
- Keep public experiment helpers model-agnostic; they should emit or consume
  `run-benchmark` JSON outputs rather than hard-code one provider or paper run.
- Use the example target adapter as a protocol reference, not as a benchmark
  baseline to compare against serious systems.
