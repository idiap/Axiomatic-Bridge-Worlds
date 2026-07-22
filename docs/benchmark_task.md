# Evaluation Protocol

`run-benchmark` invokes one target adapter per world and scores the returned ABW
candidate against private benchmark artifacts.

## Adapter Contract

The adapter is any command that reads one JSON object from stdin and writes one
JSON object to stdout. Configure it by repeating `--target-command` once per
argument:

```bash
uv run abw run-benchmark \
  --dataset dataset/abw-formal-nl-core \
  --split dev \
  --limit 10 \
  --prompt-condition zero_shot_formal_direct \
  --target-command uv \
  --target-command run \
  --target-command python \
  --target-command scripts/model_target.py \
  --output artifacts/results.json
```

The request contains:

```json
{
  "protocol_version": "...",
  "task_name": "axiomatic_bridge_worlds",
  "world_id": "...",
  "split": "dev",
  "family": "predicate_invention",
  "evaluation": {
    "prompt_condition": "zero_shot_formal_direct",
    "exemplar_bank": null
  },
  "public_artifacts": {
    "formal": {"signature": "...", "axioms": "..."},
    "nl": {"problem": "...", "examples": "..."}
  },
  "metadata": {}
}
```

Artifact objects contain paths to all public files listed in the
[dataset card](../dataset/README.md). The target must not read private files.

The preferred response is:

```json
{
  "candidate": "define ...",
  "metadata": {
    "prompt_condition": "zero_shot_formal_direct",
    "exemplar_bank": null
  }
}
```

When a condition is declared, response metadata must echo the exact
`prompt_condition` and `exemplar_bank`. Missing or contradictory values produce
`contract_failed`; the candidate is not scored and the CLI exits nonzero. Raw
candidate text is accepted only when no condition is declared.

The included `scripts/model_target.py` reads the condition from the request,
constructs the corresponding prompt, and returns the acknowledgement. Explicit
adapter CLI flags are allowed only when they agree with the request.

## Conditions

| Track | Input | Model output |
| --- | --- | --- |
| Formal Direct (FD) | formal public artifacts | ABW DSL |
| Natural-Language Direct (NLD) | NL public artifacts | controlled NL, deterministically converted to ABW DSL |
| Cross-Track (CT) | NL public artifacts | ABW DSL |

Supported zero-shot and family-specific two-shot condition names and exemplar
banks are listed in [EVALUATION.md](../EVALUATION.md).

## Result JSON

The output contains:

- `task`: benchmark and protocol versions
- `dataset`: root, manifest, and selected slice
- `target`: command, timeout, condition, and exemplar bank
- `summary`, `by_split`, `by_family`: aggregate metrics
- `worlds`: target status, response metadata, candidate, and score per world

Important summary fields are `primary_score`, `valid_submissions`, `coverage`,
`failed_invocations`, `contract_failures`, and `scoring_failures`.

Metric means are computed over every requested world. Invocation, contract, and
scoring failures contribute zero rather than disappearing from the denominator.
Invalid candidates receive zero `total_score`.

For non-analogy families, total score weights are hidden-goal utility `0.30`,
proof-cost reduction `0.20`, compression `0.10`, semantic agreement `0.20`,
novelty `0.10`, and minimality `0.10`. Analogy uses theorem transport `0.55`,
semantic agreement `0.30`, and minimality `0.15`.

## Blind Evaluation

The local runner sends only public artifact paths, but it does not sandbox the
target process. For a blind evaluation, export a public-only dataset and run
inference separately from private scoring:

```bash
uv run abw export-public-dataset \
  --dataset dataset/abw-formal-nl-core \
  --output artifacts/abw-public
```

`scripts/example_target_system.py` intentionally reads private artifacts and is
only a protocol smoke fixture. Never use it as a benchmark participant.
