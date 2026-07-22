# Public Evaluation Scripts

The scripts in this directory form the supported public evaluation surface.
They do not select a provider or model: pass any target command that implements
the ABW stdin/stdout protocol, or configure the included OpenAI-compatible
adapter with neutral `ABW_MODEL_*` environment variables.

## Evaluation

| File | Purpose |
| --- | --- |
| `install_seeded_v2_dataset.py` | Install the tracked 385-world dataset archive. |
| `model_target.py` | Evaluate any model served by an OpenAI-compatible, Ollama, or Azure ML score endpoint. |
| `run_experiment.py` | Validate a dataset slice, evaluate one target command, and write JSON results plus a run manifest. |
| `run_benchmark.py` | Thin wrapper for a single benchmark call. |
| `retry_failed_invocations.py` | Retry only failed calls in existing JSON results. |
| `build_few_shot_exemplar_bank.py` | Build leakage-controlled, same-family exemplar banks from `dev`. |
| `generate_perturbed_dataset.py` | Create semantics-preserving dataset variants for robustness evaluation. |
| `robustness_plan.py` | Build model-agnostic original/perturbed benchmark commands. |
| `build_paired_difficulty_dataset.py` | Derive paired C0-C6 evaluation views from the packaged test worlds. |
| `validate_world.py` | Validate one packaged world before evaluation. |
| `score_candidate.py` | Score one candidate against one packaged world. |
| `example_target_system.py` | Reference implementation of the target-system protocol for smoke tests. |

Paper tables, plots, statistical summaries, provider-specific launchers, and
cluster orchestration are intentionally outside this public directory. The
canonical output of an evaluation is JSON; downstream analysis can consume the
world-level records and aggregate summary without depending on paper tooling.

## Adapter Configuration

`model_target.py` reads these optional settings from `.env` or the process
environment:

- `ABW_MODEL_BASE_URL` (required unless `--base-url` is passed)
- `ABW_MODEL_ID` (required unless `--model` is passed)
- `ABW_MODEL_API_KEY` (optional for local unauthenticated endpoints)
- `ABW_MODEL_MAX_TOKENS`, `ABW_MODEL_CONTEXT_TOKENS`
- `ABW_MODEL_TEMPERATURE`, `ABW_MODEL_TIMEOUT_SECONDS`, `ABW_MODEL_RETRIES`

Keep target adapters model-agnostic and keep evaluation logic in `abw_core/`.
