---
license: mit
pretty_name: ABW Formal-NL Core
language:
- en
size_categories:
- n<1K
task_categories:
- text-generation
tags:
- benchmark
- llm-evaluation
- theorem-proving
- neuro-symbolic-ai
- formal-methods
- axiomatic-bridge-worlds
---

# ABW Formal-NL Core

This dataset package contains the core Axiomatic Bridge Worlds (ABW) benchmark.
It is intended for evaluating how well a model invents useful bridge concepts,
lemmas, morphisms, or normal forms from a public formal or natural-language task
description.

The package preserves the native ABW directory layout so it can be used directly
with the ABW software tools.

## Dataset Contents

- Archive: `abw-formal-nl-core.zip`
- Dataset root after extraction: `abw-formal-nl-core/`
- Version: `0.3.0`
- Worlds: `364`
- Splits: `dev` (`14` worlds), `test_public` (`350` worlds)
- Families: `predicate_invention`, `lemma_invention`, `analogy`, `invariant`,
  `quotient`, `normal_form`, `multi_step`
- Per-family counts: `2` dev worlds and `50` test_public worlds per family
- DSL versions: core families use `abw-dsl-v1`; analogy uses `abw-dsl-v2`

## Directory Layout

```text
abw-formal-nl-core.zip

After extraction:

abw-formal-nl-core/
  manifest.json
  dev/
    <family>/
      <world_id>/
        metadata.json
        formal/
        nl/
  test_public/
    <family>/
      <world_id>/
        metadata.json
        formal/
        nl/
```

Each world directory is a complete ABW package. The public files are the files a
model may read when producing an answer. The private, gold, and scoring files
are included so users can validate and score model outputs locally.

## Public Model Inputs

For Formal Direct evaluation, expose these files to the model:

- `metadata.json`
- `formal/signature.json`
- `formal/axioms.abw`
- `formal/visible_theorems.abw`
- `formal/visible_facts.abw`
- `formal/targets_visible.abw`

For Cross-Track NL-to-formal evaluation or human-readable inspection, expose
these files and ask the model to return an ABW DSL bridge:

- `metadata.json`
- `nl/problem.md`
- `nl/examples.md`
- `nl/theorem_cards.md`
- `nl/nl_alignment.json`

The ABW runner uses these public files when constructing prompts for target
models.

For true Natural-Language Direct evaluation, expose the same public
natural-language files but ask the model to return controlled-natural-language
bridge blocks under the `abw-controlled-nl-v1` contract. Convert that text to
ABW DSL with the deterministic converter in `abw_core.nl.controlled_candidate`
before scoring. The converter performs no semantic repair; conversion failures
are invalid candidates.

## Private, Gold, And Scoring Files

Do not include these files in the model prompt during evaluation:

- `formal/targets_hidden.abw`
- `formal/hidden_bridge.json`
- `formal/gold_solution.abw`
- `formal/proof_fixtures.json`
- `formal/scoring_config.json`
- `nl/hidden_bridge_private.md`
- `nl/gold_informal_solution_private.md`

These files are not secret from the dataset user. They are hidden from the
model during evaluation and are provided so the ABW tooling can score candidate
bridges, check validity, compute proof-cost improvements, and compare against
the semantic reference behavior.

Important: do not feed an entire world directory to an LLM as the task input.
That would leak the answer and scoring artifacts. Feed only the public files,
then score the model's final candidate with the private and scoring files.

## Recommended Evaluation Flow

1. Extract `abw-formal-nl-core.zip`.
2. Choose a world from `abw-formal-nl-core/dev/` or
   `abw-formal-nl-core/test_public/`.
3. Build the model prompt from the public model-input files listed above.
4. Ask the model to produce an ABW candidate bridge, or controlled-natural-language
   bridge blocks for true Natural-Language Direct.
5. Convert controlled-natural-language candidates when needed, then score the
   ABW candidate with the ABW software against the same packaged world.

For example, from the ABW software repository:

```bash
.venv/bin/abw score-candidate \
  --world dataset/abw-formal-nl-core/test_public/predicate_invention/abw_test_public_0000 \
  --candidate path/to/candidate.abw
```

You can also validate a packaged world before scoring:

```bash
.venv/bin/abw validate-world \
  --world dataset/abw-formal-nl-core/test_public/predicate_invention/abw_test_public_0000
```

## License

This dataset package is released under the MIT License, as declared in the
dataset card metadata.
