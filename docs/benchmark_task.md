# Benchmark Task

This document packages Axiomatic Bridge Worlds as an evaluation task rather
than only a per-world scorer.

The benchmark asks a target system to read the public surface of one packaged
world and propose a bridge candidate in ABW syntax. The evaluator then scores
that candidate against the hidden bridge and hidden targets that remain private
to the benchmark harness.

## Task Contract

Use [run-benchmark](../abw_core/cli.py) as the single entry point for
dataset-level evaluation.

For release and paper-reproduction use, install the full executable environment
before running the benchmark:

```bash
uv sync --all-extras
```

This environment includes the exact local scorer used for the paper metrics
plus tests and solver-backed diagnostics. The diagnostic solver backends do not
change the composite scoring formulas or aggregation rule.

Dataset configs use balanced `examples_per_family` counts. The formal and
natural-language task surfaces are paired views of the same generated worlds,
so a formal run and an NL run can evaluate the same family/seed sample.

```bash
python scripts/install_seeded_v2_dataset.py
```

```bash
python -m abw_core run-benchmark \
  --dataset dataset/abw-formal-nl-core \
  --target-command python \
  --target-command scripts/example_target_system.py \
  --split dev \
  --limit 10 \
  --output artifacts/abw_benchmark_results.json
```

Repeat `--target-command` once per argv token, just like the subprocess scorer
backend flags elsewhere in the CLI. If a token itself starts with `-`, pass it
as `--target-command=-m` or `--target-command=-c`.

The runner invokes the target command once per world. It sends one JSON payload
to stdin with:

- `protocol_version`: current target-system protocol tag
- `task_name`: `axiomatic_bridge_worlds`
- `world_id`, `split`, `family`
- `public_artifacts.formal`: links to `signature`, `axioms`, `visible_facts`,
  `visible_theorems`, and `targets_visible`
- `public_artifacts.nl`: links to `problem`, `examples`, `theorem_cards`, and
  `nl_alignment`
- `metadata`: public generation metadata such as seed, family, and depth bound

The target system should return either:

- preferred: JSON with `{"candidate": "<abw text>", "metadata": {...}}`
- compatibility mode: raw ABW candidate text on stdout

The benchmark JSON output stores one scored record per world plus aggregate summaries
for the full run, each split, and each family.

## Generic Model Adapter

`run-benchmark` is model-agnostic. Any target command can participate if it
reads the JSON request from stdin and writes a candidate response to stdout.

For OpenAI-compatible chat-completions APIs, the disclosure branch includes a
neutral adapter:

```bash
ABW_MODEL_API_KEY=... \
ABW_MODEL_BASE_URL=https://api.example.test/v1 \
ABW_MODEL_ID=my-model \
python -m abw_core run-benchmark \
  --dataset dataset/abw-formal-nl-core \
  --target-command python \
  --target-command scripts/model_target.py \
  --split dev \
  --limit 10 \
  --output artifacts/abw_benchmark_results.json
```

The adapter also accepts command-line overrides such as `--model`,
`--base-url`, `--max-tokens`, `--temperature`, and `--timeout-seconds` when
environment variables are not convenient. Prefer environment variables for API
keys because benchmark JSON outputs record the target command for traceability.

## Robustness And Difficulty Controls

The public benchmark runner also supports the paper's paired robustness and
C0-C6 shape-control workflows without introducing provider-specific scripts.

Robustness is a post-generation perturbation analysis:

```bash
python scripts/generate_perturbed_dataset.py \
  --source dataset/abw-formal-nl-core \
  --output artifacts/abw_perturbed/alpha_renaming \
  --perturbation alpha_renaming
```

The supported robustness perturbations are `alpha_renaming`,
`axiom_order_shuffle`, `nl_paraphrase`, and `distractor_insertion`. Use
`scripts/robustness_plan.py` to emit original and perturbed `run-benchmark`
commands for any target adapter:

```bash
python scripts/robustness_plan.py \
  --base-dataset-root dataset/abw-formal-nl-core \
  --target-command python \
  --target-command scripts/model_target.py \
  --output artifacts/abw_robustness/robustness_plan.json
```

The plan records paired original and perturbed JSON output paths for downstream
analysis.

C0-C6 difficulty shapes are generator-side paired rewrites rather than
semantics-preserving robustness perturbations:

```bash
python scripts/build_paired_difficulty_dataset.py --overwrite
```

Run the same `run-benchmark` adapter on that derived dataset. Each record keeps
its difficulty case and paired source identity in metadata.

This separation is intentional: dataset configs describe ordinary generated
corpora, robustness creates perturbed copies after generation, and C0-C6
changes the public difficulty shape while keeping paired source identities.

## Metrics

The official leaderboard metric is:

- `primary_score`: the dataset mean of `total_score`

Per-world `total_score` is still computed by the existing evaluator described in
[Scoring](scoring.md). The benchmark runner then aggregates these auxiliary
means over the selected slice:

- `mean_validity_score`
- `mean_hidden_goal_solve_rate`
- `mean_proof_cost_reduction`
- `mean_compression_score`
- `mean_semantic_equivalence_score`
- `mean_novelty_score`
- `mean_minimality_score`
- `mean_candidate_size`
- `mean_total_score`

Operational metrics are included alongside the semantic ones:

- `coverage`: completed evaluations divided by requested worlds
- `failed_invocations`: target-system crashes, timeouts, or malformed outputs
- `scoring_failures`: evaluator-side failures after a candidate was returned
- `valid_submissions`
- `invalid_submissions`
- `mean_latency_seconds`
- `p95_latency_seconds`

## Aggregation Rule

Aggregate metric means are computed over the full selected slice, not only over
successful worlds.

That means:

- a crashed target invocation contributes zero metric values
- a malformed target payload contributes zero metric values
- a candidate that parses but is invalid still contributes its scored metrics,
  which usually means `validity_score = 0` and `total_score = 0`

This keeps the benchmark honest about reliability instead of rewarding systems
that only work on the easy subset.

## Example Target Adapter

[example_target_system.py](../scripts/example_target_system.py) demonstrates the
integration contract. It is only a protocol smoke test:

- it reads one benchmark request from stdin
- it picks the family-matched fixture under [examples](../examples)
- it returns that fixture as the candidate

Because it uses repo fixtures, it is not a fair benchmark participant. Its role
is to provide a known-good adapter for tests, CI, and downstream integrations.

## Output Shape

The JSON file written by `--output` contains:

- `task`: benchmark identity and protocol version
- `dataset`: root, manifest snapshot, split filter, and limit
- `target`: command and timeout
- `scoring`: optional backend override used by the evaluator
- `summary`: dataset-wide aggregates
- `by_split`
- `by_family`
- `worlds`: one detailed record per world, including target status, latency,
  candidate digest, and the full per-world score payload

Generated benchmark outputs should be written under `artifacts/` or another
local output path, not committed with the disclosure source.

## Evaluation Integrity

The runner passes only public artifact links to the target system, but this
local harness is cooperative rather than hard-isolated. A target process that
already has unrestricted filesystem access to the repository could still read
private files directly.

For a true blind benchmark setup, use one of these deployment patterns:

- export a stripped public dataset copy:

  ```bash
  python -m abw_core export-public-dataset \
    --dataset dataset/abw-formal-nl-core \
    --output artifacts/abw_paper_core_public
  ```

- evaluate against a stripped public dataset export
- run the target system in an isolated sandbox or container
- separate public inference from private scoring on different machines

The current runner is the right local protocol surface; stronger isolation is a
deployment concern on top of it.
