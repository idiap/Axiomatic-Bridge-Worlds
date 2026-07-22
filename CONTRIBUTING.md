# Contributing

ABW uses `uv` for dependency management.

```bash
uv sync --extra test
uv run --extra test pytest
```

Optional finite-model diagnostics use:

```bash
uv run --extra test --extra validation pytest
```

Useful checks:

```bash
uv run python scripts/install_seeded_v2_dataset.py
uv run python scripts/run_experiment.py --help
make dist-check
```

Keep changes scoped and deterministic. Update tests and the relevant public
guide when changing a CLI, dataset format, prompt contract, or scoring behavior.
Changes to generation presets, weights, or public/private artifact boundaries
change benchmark meaning and must state whether datasets or results need to be
regenerated.

Distributed files must remain REUSE compliant:

- use SPDX headers where comments are supported
- use `REUSE.toml` annotations for other files
- keep license texts under `LICENSES/`
- run `reuse lint` when `reuse-tool` is available

Before submitting a change, run the focused test suite and avoid committing
generated datasets or experiment artifacts unrelated to the change.
