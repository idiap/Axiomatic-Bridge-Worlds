# Structured Artifacts

This document explains the repository's machine-readable artifacts: the YAML
presets that steer generation workflows and the JSON files that package worlds
and benchmark results. It exists because many of those files are deliberately
terse for tool compatibility, which makes their motivation easy to lose when
you first open them.

## Why This Document Exists

ABW ships a mix of human-facing code and tool-facing configuration. Python files
can carry docstrings and inline comments, but JSON files cannot safely do that
across every consumer in the repo. Rather than polluting those files with
non-portable comment tricks, this document gives the missing explanation in one
place:

- what each structured artifact is for
- which tool reads it
- what assumptions it encodes
- what should stay stable when you edit it

## YAML Surfaces

The YAML files in this repository are generation presets.

### Dataset presets

The files in `configs/` define two reproducible generation profiles: the
smoke sample (`mvp.yaml`) and the paper-core reproduction sample. They answer
four questions for the generator:

- which benchmark families should be rotated through
- which paired public views are packaged
- how many worlds per family should go into each split
- what depth, proof-budget, interactivity, and backend defaults should be
  packaged into every world

If you change one of these presets, you are not only changing generation-time
behavior. You are also changing the metadata that later scoring and session
tools will read from the packaged worlds.

## JSON Surfaces

JSON files in this repo are intentionally machine-oriented. They should stay
stable, parseable, and boring. This section gives them the explanatory layer
they cannot safely carry inline.

### Dataset manifest

The root dataset `manifest.json` summarizes one packaged dataset build. Its job
is not to repeat every world's contents. Instead, it captures the generation
contract for the dataset as a whole:

- dataset name and version
- split sizes
- examples per family, when the preset uses balanced counts
- paired public views
- family inventory
- DSL version
- output root
- interactive and backend defaults

This is the quickest place to confirm what kind of dataset a directory is.

Public-only dataset exports reuse the same manifest shape but add
`public_export: true` plus a `private_artifacts_removed` list so downstream
tooling can tell that the corpus is intentionally stripped and not suitable for
local hidden-goal scoring.

### Benchmark outputs

The JSON output written by [run-benchmark](benchmark_task.md) is the
machine-readable benchmark result artifact. It is meant to support aggregation,
regression tracking, and downstream auditing.

Its top-level sections separate concerns cleanly:

- `task`: which benchmark contract was executed
- `dataset`: which slice of which packaged corpus was used
- `target`: how the evaluated system was invoked
- `scoring`: any backend override applied by the evaluator
- `summary`, `by_split`, and `by_family`: aggregate metrics
- `worlds`: one detailed record per evaluated world

The per-world records deliberately store a candidate digest and not the full
candidate text, so outputs stay portable even on thousand-world runs.

### Packaged world metadata

Each packaged world includes a small set of JSON artifacts that complement the
ABW text files.

`metadata.json`
: Lightweight identity and generation provenance such as world id, family, seed,
  depth bound, hidden-step settings, and distractor status.

`formal/signature.json`
: The many-sorted signature serialized into a machine-readable form so tooling
  can inspect sorts, functions, and predicates without reparsing the DSL text.

`formal/hidden_bridge.json`
: The hidden gold bridge surface used by scoring. This file is the answer key
  for evaluation, so it should be treated as private benchmark state even inside
  a local packaged world.

`formal/proof_fixtures.json`
: Generator-side metadata that explains the hidden construction pattern behind a
  family. This is where anti-unification outputs, step depths, and other family
  fixtures live when downstream tooling needs them.

`formal/scoring_config.json`
: The scoring budget and weight schedule. Edit this only if you intend to
  change the benchmark's reward trade-offs, not just generation details.

`nl/nl_alignment.json`
: Alignment records between rendered natural-language statements and their
  formal ABW sources. This is the main debugging surface for checking whether
  NL packaging stayed faithful to the formal track.

## Concrete Example

When you inspect a packaged world, the intended reading order is:

1. `metadata.json` to learn what kind of world you are looking at
2. the `.abw` formal files to understand the logical surface
3. `scoring_config.json` to see how candidates will be judged
4. `proof_fixtures.json` if you need generator-side construction details
5. `nl_alignment.json` to confirm how the natural-language rendering maps back
   to formal statements

That order moves from high-level identity to formal content to evaluation and
finally to interpretation aids.

## Editing Guidance

When changing a structured artifact, keep these boundaries in mind:

- If a file is machine-consumed JSON, prefer documenting it here rather than
  adding non-standard comments that may break parsers.
- If a YAML file expresses policy or configuration, keep the header comments in
  sync with the real workflow it controls.
- If you change the meaning of packaged JSON outputs, update both the generator
  code and this document so future readers know the contract moved.
- If you add a new structured artifact class, add a short explanation here even
  if the file itself is self-describing.

## What Not To Assume

- A world package is not just formal logic text; its JSON sidecars are part of
  the runtime contract.
- A terse structured file is not necessarily underexplained on purpose; often it
  is constrained by parser compatibility and should be explained in surrounding
  docs instead.
