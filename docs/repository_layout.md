# Repository Layout

The rule of thumb: reusable source and docs are tracked; generated corpora and
run outputs stay local unless a release says otherwise.

## Top-Level Map

| Path | Role | Commit policy |
| --- | --- | --- |
| `abw_core/` | Installable runtime: CLI, generator, packager, prover, scorer, NL helpers. | Maintained source only. |
| `configs/` | Reproducible generation presets and packaging profiles. | Commit stable, documented presets. |
| `dataset/` | Tracked release archive, dataset card, and ignored extracted benchmark root. | Commit the archive and documentation; ignore extracted files. |
| `docs/` | Narrative documentation and design notes. | Maintained docs only. |
| `examples/` | Tiny inspectable worlds and family-matched candidate fixtures. | Public teaching examples only. |
| `scripts/` | Thin wrappers and adapters around the CLI. | Keep small; no forked runtime logic. |
| `tests/` | Regression coverage for the public runtime contract. | Deterministic tests and stable fixtures. |
| `artifacts/` | Local JSON results, generated datasets, debug output. | Ignored — never committed. |

## Where New Material Goes

- Importable runtime behavior → `abw_core/`
- A stable, reusable generation preset → `configs/`
- A tiny public teaching or smoke artifact → `examples/`
- A large generated run output → `artifacts/` (or another ignored dir)
- Documentation for humans → `docs/`, or a directory README when that's the main
  context a visitor needs
- Local tool/editor/agent-only material → keep out of the public surface unless
  it ships with the project

## `dataset/` vs `examples/`

`examples/` holds tiny worlds and candidate fixtures used by docs and smoke
tests. `dataset/` holds the versioned benchmark archive and its dataset card.
The installer expands the archive to `dataset/abw-formal-nl-core/`, which is
ignored because the ZIP remains the canonical tracked snapshot.

## Directory Entry Points

After opening a top-level folder, its local README is the fastest orientation:
[`configs/`](../configs/README.md) · [`dataset/`](../dataset/README.md) ·
[`examples/`](../examples/README.md) · [`scripts/`](../scripts/README.md) ·
[`tests/`](../tests/README.md)
