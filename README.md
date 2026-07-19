# Axiomatic Bridge Worlds

Axiomatic Bridge Worlds (ABW) is a synthetic benchmark for theory formation. It
does not only ask whether a system can prove the next statement. It asks whether
the system can invent the missing bridge concept that makes several later
statements easier to justify — a new predicate, a reusable lemma, or a morphism
that transports structure between theories.

The repository ships the typed DSL, deterministic world generators, a bounded
(optionally solver-backed) prover, natural-language renderers, controlled-NL
candidate conversion, and dataset and benchmark tooling, so ABW can be used as
a reusable evaluation harness.

## A Tiny Example

Suppose a world keeps exposing this pattern:

```text
R(x,y)   P0(x)   P1(y)
R(x,y) -> R(f0(x), f1(y))
P0(x) -> P0(f0(x))
P1(y) -> P1(f1(y))
```

A strong candidate is not another low-level theorem. It is the bridge that names
the pattern and advances it:

```abw
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
```

That bridge turns repeated proof burden into one named object reused across
hidden targets. Each packaged world keeps the intended bridge **private**; the
target system sees only the public view selected by the condition, and submits a
candidate that the scorer judges on validity, hidden-goal utility, compression,
novelty, and bounded semantic alignment.

The scorer consumes ABW DSL candidates. For true Natural-Language Direct
experiments, `abw_core.nl.controlled_candidate` provides a frozen
controlled-natural-language bridge contract and deterministic converter to ABW
DSL; the converter performs no semantic repair, so failed conversions are scored
as invalid by the unchanged scorer.

## Task Families

ABW is a suite of seven families, each requiring a different kind of bridge:

| Family | Hidden bridge style |
| --- | --- |
| `predicate_invention` | A new conjunctive predicate |
| `lemma_invention` | A reusable derived rule |
| `analogy` | A theory morphism between structures |
| `invariant` | A property preserved through transitions |
| `quotient` | A canonical / equivalence view |
| `normal_form` | A rewrite-aware abstraction |
| `multi_step` | A bridge whose value grows with depth |

## Bundled Core Dataset

A ready-to-use export of the benchmark ships in [`dataset/`](dataset/) as the
`abw-formal-nl-core` package (version `0.3.0`), so you can evaluate a model
without generating worlds first. It holds 364 packaged worlds spanning all seven
families: a `dev` split (14 worlds, 2 per family) and a `test_public` split (350
worlds, 50 per family). Every world carries both the formal and
natural-language tracks.

Each world keeps the native ABW layout — public model inputs (`metadata.json`,
`formal/`, `nl/`) alongside the private gold and scoring artifacts the tooling
needs to validate and score candidates locally. Feed a model only the public
files; [`dataset/README.md`](dataset/README.md) lists the exact public vs.
private files, the recommended evaluation flow, and licensing (MIT).

```bash
uv run python -m abw_core score-candidate \
  --world dataset/abw-formal-nl-core/test_public/predicate_invention/abw_test_public_0000 \
  --candidate path/to/candidate.abw
```

## Setup

Use Python 3.9+ and [`uv`](https://docs.astral.sh/uv/). The full environment
includes the scorer, generators, tests, benchmark runner, and the optional
`z3`/`cvc5` solver diagnostics:

```bash
uv sync --all-extras      # or: make setup
```

For a minimal install (framework, generator, packaging, local scoring), use
`uv sync` (or `make setup-base`). Run commands through the managed environment;
the installed `abw` console script is equivalent to `python -m abw_core`:

```bash
uv run python -m abw_core inspect-world --world examples/tiny_world
uv run pytest -q          # or: make test
```

## Generate A Small Dataset

Generate the 14-world all-family smoke dataset (one dev + one public-test world
per family), then inspect and score the bundled example:

```bash
uv run python scripts/generate_dataset.py --output artifacts/abw_smoke_dataset

uv run python -m abw_core inspect-world  --world examples/tiny_world
uv run python -m abw_core score-candidate \
  --world examples/tiny_world \
  --candidate examples/predicate_invention/gold_candidate.abw
```

## Evaluate A Model With Your API Key

To score an OpenAI-compatible model without writing an adapter, provide neutral
`ABW_MODEL_*` settings and route the target command through
`scripts/generic_model_target.py`:

```bash
ABW_MODEL_API_KEY=sk-... \
ABW_MODEL_BASE_URL=https://api.example.test/v1 \
ABW_MODEL_ID=my-model \
uv run python -m abw_core run-benchmark \
  --dataset artifacts/abw_smoke_dataset \
  --target-command uv \
  --target-command run \
  --target-command python \
  --target-command scripts/generic_model_target.py \
  --split dev \
  --limit 10 \
  --output artifacts/abw_benchmark_report.json
```

The runner sends one request per world and expects the target adapter to return
scoreable ABW candidate text. Adapters for controlled-natural-language outputs
should run the deterministic conversion step before returning the candidate to
the runner. The JSON output includes the dataset-level `primary_score` plus
auxiliary semantic and operational metrics. Repeat `--target-command` once per
argv token; the same protocol accepts any custom adapter.

## Read Next

- [Documentation Index](docs/index.md) — the map of the full documentation set
- [Project Concepts](docs/project_concepts.md) — what ABW measures, one example per family
- [Workflows](docs/workflows.md) — diagnostics, sessions, datasets, and robustness recipes
- [Benchmark Task](docs/benchmark_task.md) — target-system contract, metrics, aggregation
- [Architecture](docs/architecture.md) · [Scoring](docs/scoring.md) · [DSL](docs/dsl.md)
- [Repository Layout](docs/repository_layout.md) — what belongs in each folder

## Scope And Boundaries

ABW implements a deterministic local runtime: multi-family generation, bounded
proving, solver-aided diagnostics, dataset packaging, target-system
benchmarking, and local scoring. The disclosure surface is the
framework code, public documentation, examples, tests, reusable dataset and
benchmark wrappers, and the generic target adapter. Paper-specific generated
artifacts and orchestration remain local, not part of the public framework
surface. The curated reference package under
`dataset/` is the tracked benchmark snapshot; generated roots under
`datasets/` and outputs under `artifacts/` remain local by default.

ABW is intentionally bounded: there is no remote model dependency in the core
runtime, the local proof engine is not a full higher-order prover, the
`z3`/`cvc5` integrations are finite-model diagnostics rather than complete
theorem proving, and the interactive loop is a bounded refinement surface, not a
proof assistant. That boundedness keeps ABW inspectable, reproducible, and
locally debuggable.

## Project Hygiene

[Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) ·
[Security](SECURITY.md) · [Changelog](CHANGELOG.md) ·
[Citation Metadata](CITATION.cff)
