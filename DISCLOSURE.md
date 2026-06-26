# ABW Software Disclosure Scope

This disclosure branch contains the paper-relevant ABW software surface: the
deterministic generator, package format, public/private export logic, scorer,
benchmark runner, report renderer, robustness and C0-C6 difficulty-control
helpers, examples, tests, and documentation needed to evaluate model-generated
ABW bridge candidates.

Generated datasets and result artifacts are not part of this disclosure bundle.
They may remain on local disk for paper drafting and reproducibility work, but
they are intentionally ignored and removed from git tracking on this branch.

Disclosure archives must also keep REUSE metadata intact: SPDX headers or root
`REUSE.toml` annotations for distributed files, and full license texts in
`LICENSES/` using SPDX identifiers such as `LICENSES/MIT.txt`.

The default disclosed generator surface is the seven-family paper-core suite:

- `predicate_invention`
- `lemma_invention`
- `analogy`
- `invariant`
- `quotient`
- `normal_form`
- `multi_step`

Provider-specific paper-run orchestration is excluded from this branch. In
particular, the disclosure bundle does not include model-selection matrices,
selected-model run planners, provider-specific experiment adapters, repair
utilities, paper table builders, or generated paper outputs.

Any model can be evaluated through the benchmark protocol by supplying a target
adapter command to `python -m abw_core run-benchmark`. The adapter reads one
public ABW request from stdin and returns either raw ABW candidate text or JSON
with a `candidate` string field. `scripts/generic_model_target.py` provides a
neutral OpenAI-compatible adapter driven by `ABW_MODEL_API_KEY`,
`ABW_MODEL_BASE_URL`, and `ABW_MODEL_ID`.

`scripts/run_experiment.py` is the main single-model entrypoint: it generates
(or reuses) a packaged paper-core dataset, validates it, runs one
`--target-command` adapter against it, renders a report, and writes a manifest
with the resulting metrics and composite score. It does not know about any
specific provider or model-selection matrix — pass any adapter command, e.g.
`python scripts/generic_model_target.py`, and any model name through that
adapter's own configuration (env vars or flags).

The interactive refinement session API (`start-session`, `session-query`,
`finish-session`, backed by `abw_core/session.py`) is included and supported:
it offers budgeted public diagnostic queries against a packaged world. It is
not exercised by the paper's reported evaluation cells, which use the direct
`run-benchmark` path; it ships as a reusable capability for agentic or iterative
evaluation setups.

Robustness and difficulty controls remain reusable public workflows. Robustness
uses `scripts/generate_perturbed_dataset.py`, `scripts/robustness_plan.py`, and
`scripts/robustness_summary.py` to create paired perturbed datasets and compare
reports through the same model-agnostic benchmark runner. C0-C6 difficulty
shape experiments use `scripts/build_paired_difficulty_dataset.py` plus
`scripts/difficulty_shape_summary.py`. These workflows intentionally live
outside `configs/*.yaml`; perturbation is selected explicitly by the
post-generation helper command, not by a dataset-preset boolean.
