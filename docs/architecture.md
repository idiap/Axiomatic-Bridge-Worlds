# Architecture

ABW follows one rule: formal truth comes first.

## Pipeline

1. Build a typed world — [abw_core/ir.py](../abw_core/ir.py)
2. Validate it — [abw_core/typecheck.py](../abw_core/typecheck.py)
3. Compute proof fixtures — [abw_core/prover](../abw_core/prover/__init__.py)
4. Render public and private artifacts — [abw_core/packager.py](../abw_core/packager.py)
5. Run public interactive refinement — [abw_core/session.py](../abw_core/session.py)
6. Score candidate bridges — [abw_core/scorer](../abw_core/scorer/__init__.py)

## Why The Prover Is Bounded

The benchmark wants controllable proof cost, not maximal proving power. A bounded
forward-chaining engine over generated terms keeps worlds deterministic,
auditable, and cheap to regenerate. Definitions are zero-cost abbreviations;
axioms and lemmas cost one proof step each — so a good bridge reduces proof cost
by sharing structure rather than renaming an atom.

That same bounded closure doubles as a finite Herbrand-style model. When a goal
is not derivable, the runtime serializes the closure as a bounded
**countermodel** (term domains by sort, predicate extensions, and the goal atoms
that stay false). This local, cheap diagnostic also underpins the interactive
session API.

The optional `z3` and `cvc5` backends add one stronger diagnostic step: proof-cost
scoring stays on the local derivation graph, but they can search for finite
first-order models over the bounded term palette when a less local
counterexample is needed.

## Public vs Private Artifacts

- **Public:** signature, axioms, visible theorems, visible facts, visible
  targets, and the public NL track.
- **Private:** hidden bridge, hidden targets, proof fixtures, and gold solution.

The NL renderer runs leakage checks against private bridge names before
packaging. Interactive sessions keep the same split: exploration stays on visible
behavior, and hidden-goal scoring is reserved for the final submission step.
