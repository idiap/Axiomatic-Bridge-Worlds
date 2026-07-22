# Configs

Reproducible generation presets for ABW worlds and datasets. Each file answers:
what packaged material should be generated, and with what defaults?

| File | Use |
| --- | --- |
| `paper_core_seeded_v2.yaml` | Structurally diverse paper-core release with schema-disjoint dev/test splits. |

Every generated world packages the same task through both formal and
natural-language artifacts; the `views` field records that paired surface (it
does not create separate datasets).

Robustness perturbations and C0-C6 difficulty shapes are derived only from the
packaged seeded-v2 worlds. Use `scripts/generate_perturbed_dataset.py` with
`scripts/robustness_plan.py`, and `scripts/build_paired_difficulty_dataset.py`,
so derived data and model-agnostic run plans remain auditable.

## Editing Guidance

- Keep presets reproducible and documented.
- Prefer `examples_per_family` over raw split totals for balanced datasets.
- Use split-level `start_seed` only to reproduce a known paper slice whose dev
  and public-test worlds came from different seed blocks.
- When a change affects packaged artifacts or evaluation semantics, update the
  docs and changelog too.
