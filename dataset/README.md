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
---

# ABW Formal-NL Core

`abw-formal-nl-core.zip` is the version `0.4.0` benchmark snapshot:

- 35 `dev` worlds, 5 per family
- 350 `test_public` worlds, 50 per family
- seven families
- paired formal and natural-language views of every world

Install it from the repository root:

```bash
uv run python scripts/install_seeded_v2_dataset.py
```

The extracted layout is:

```text
dataset/abw-formal-nl-core/
  manifest.json
  dev/<family>/<world_id>/
  test_public/<family>/<world_id>/
```

## Public Inputs

Formal Direct may expose:

- `metadata.json`
- `formal/signature.json`
- `formal/axioms.abw`
- `formal/visible_theorems.abw`
- `formal/visible_facts.abw`
- `formal/targets_visible.abw`

Natural-Language Direct and Cross-Track may expose:

- `metadata.json`
- `nl/problem.md`
- `nl/examples.md`
- `nl/theorem_cards.md`
- `nl/nl_alignment.json`

NLD returns controlled NL under `abw-controlled-nl-v1`; the frozen converter
produces ABW DSL before scoring. CT returns ABW DSL directly.

## Private Files

Never include these files in a model prompt:

- `formal/targets_hidden.abw`
- `formal/hidden_bridge.json`
- `formal/gold_solution.abw`
- `formal/proof_fixtures.json`
- `formal/scoring_config.json`
- `nl/hidden_bridge_private.md`
- `nl/gold_informal_solution_private.md`

They are included only so the local harness can score submissions. Giving a
model the complete world directory leaks the answer.

Validate one world with:

```bash
uv run abw validate-world \
  --world dataset/abw-formal-nl-core/test_public/predicate_invention/abw_test_public_0000
```

The dataset is released under the MIT License.
