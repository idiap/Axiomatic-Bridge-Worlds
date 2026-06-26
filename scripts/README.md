# Scripts

This directory contains thin command-line wrappers and example adapters around
the canonical `python -m abw_core` entrypoint.

The goal is convenience, not a second runtime surface.

## Files In This Directory

| File | Purpose |
| --- | --- |
| `build_few_shot_exemplar_bank.py` | Build a public-only few-shot exemplar bank for direct-condition runs. |
| `build_paired_difficulty_dataset.py` | Build paired C0-C6 difficulty-shape datasets from generated source worlds. |
| `check_natural_language_artifacts.py` | Check public natural-language artifacts for the Natural-Language Direct track. |
| `difficulty_shape_summary.py` | Summarize benchmark reports by C0-C6 difficulty shape and family. |
| `export_public_dataset.py` | Export a packaged dataset with private artifacts stripped out for public-only evaluation. |
| `generate_dataset.py` | Dataset-generation entrypoint around the canonical config loader. |
| `generate_perturbed_dataset.py` | Create semantics-preserving perturbed dataset copies for robustness analysis. |
| `generic_model_target.py` | Neutral OpenAI-compatible target adapter configured through `ABW_MODEL_*` environment variables. |
| `internal_model_target.py` | OpenAI-compatible adapter for internal / self-hosted model deployments. |
| `openai_model_target.py` | Adapter for the OpenAI Responses API, configured through `OPENAI_*` environment variables. |
| `retry_failed_invocations.py` | Retry failed benchmark invocations recorded in an existing report file. |
| `inspect_world.py` | Convenience wrapper for world inspection (also covers NL packaging output — `abw_core.cli inspect-world` renders whichever track the world was packaged with). |
| `render_benchmark_report.py` | Convenience wrapper for LaTeX benchmark report generation. |
| `robustness_plan.py` | Emit model-agnostic original and perturbed `run-benchmark` commands for a robustness suite. |
| `robustness_summary.py` | Summarize paired original-minus-perturbed robustness drops from completed reports. |
| `run_benchmark.py` | Thin wrapper around one `run-benchmark` call (no dataset generation, validation, or report rendering). |
| `run_experiment.py` | Generate (optional), validate, and run one target model against the paper-core dataset; renders a report and writes a manifest. The main "pick a dataset, pick a model, check the score" entrypoint. |
| `score_candidate.py` | Convenience wrapper for one-world candidate scoring. |
| `validate_dataset.py` | Convenience wrapper for validation checks. |
| `example_target_system.py` | Example target adapter that speaks the benchmark protocol for smoke testing. |

## Editing Guidance

- Keep wrappers thin and route them into `abw_core.cli`.
- Put real business logic in `abw_core/`, not here.
- Keep public experiment helpers model-agnostic; they should emit or consume
  `run-benchmark` reports rather than hard-code one provider or paper run.
- Use the example target adapter as a protocol reference, not as a benchmark
  baseline to compare against serious systems.
