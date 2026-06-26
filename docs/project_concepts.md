# Project Concepts

This guide explains the idea behind Axiomatic Bridge Worlds from the project
level rather than from one file or one command. It is meant for a reader who
wants to understand what the benchmark is trying to measure, why the runtime is
structured the way it is, and how the pieces of the repository fit together.

## Why This Project Exists

Most reasoning benchmarks ask a narrow question: can a system derive a target
statement from the facts and rules it is given? That is useful, but it leaves
out an important scientific behavior. In real theory building, progress often
comes from inventing a concept that reorganizes several low-level facts into a
more useful abstraction.

Axiomatic Bridge Worlds focuses on that missing step.

The project asks a model or agent to discover a bridge:

- a predicate that names a recurring conjunction
- a lemma that packages a repeated derivation pattern
- a mapping that transports structure from one theory to another
- an invariant, quotient, normal form, or multi-step bridge that reorganizes
  visible clauses into reusable structure

The benchmark is not satisfied by proving one theorem in isolation. It asks
whether the candidate abstraction makes several downstream facts cheaper,
cleaner, or more reusable.

## The Core Idea: A Bridge Concept

At the center of the project is one simple thought:

> A good theory is not just a pile of correct statements. It contains the right
> intermediate concepts.

In ABW, a world is built so that a hidden bridge really does organize the
visible structure. The bridge is then removed from the public package. The task
is to recover something like it from the remaining evidence.

For example, a world might publicly expose:

```text
R(x,y)
P0(x)
P1(y)
R(x,y) -> R(f0(x), f1(y))
P0(x) -> P0(f0(x))
P1(y) -> P1(f1(y))
```

The intended hidden bridge could be:

```text
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
```

That bridge is useful because it groups the repeated proof burden into one
named object. Instead of reproving the full conjunction at every step, the
candidate can route several hidden goals through the bridge predicate.

The benchmark therefore rewards a form of abstraction-sensitive reasoning:
notice the repeated pattern, package it, and use the package to make later
reasoning cheaper.

## What One World Represents

Each generated world is a small synthetic scientific micro-domain. It contains
enough visible structure to make the hidden bridge discoverable, but not so
much structure that discovery becomes trivial.

Conceptually, a world has four layers:

1. Public theory
   The visible signature, visible axioms, visible theorems, visible facts, and
   visible goals that the agent is allowed to inspect.

2. Hidden bridge
   The intended abstraction. This may be a definition, lemma, theorem, or
   analogy morphism that is not shown to the solver during normal exploration.

3. Hidden targets
   Goals used for evaluation. These are where the abstraction should pay off.

4. Interpretive packaging
   Natural-language renderings, theorem cards, metadata, proof fixtures, and
   scoring configuration that make the world usable as a benchmark artifact.

The project is built around the tension between the first two layers. Public
structure contains clues; the hidden bridge contains the organizing principle.

## Why The Public/Private Split Matters

The benchmark would collapse if the bridge were visible everywhere. The
public/private packaging split exists to preserve a real discovery task.

Public artifacts teach the agent what the world looks like:

- the available sorts, constants, functions, and predicates
- the visible rules and facts
- public targets and examples
- the public natural-language problem statement

Private artifacts preserve evaluation honesty:

- the hidden bridge
- hidden targets
- proof fixtures that explain how the world was constructed
- the gold-style formal and informal solutions

This separation is what makes ABW a benchmark for latent concept recovery
instead of a benchmark for copying a supplied answer format.

## Why The Runtime Is Deterministic

The project deliberately prefers determinism over raw expressive power.

The worlds are generated from symbolic templates, not from open-ended search or
remote model calls. The prover is bounded. The natural-language renderer is
deterministic. Seeds matter. This design gives the repository three important
properties:

- worlds are cheap to regenerate
- scoring behavior is inspectable
- evaluation disagreements can be debugged locally

That is why ABW uses a bounded forward-chaining backbone instead of a large,
opaque theorem-proving stack by default. The benchmark is trying to isolate a
reasoning behavior, not maximize solver strength at any cost.

## What The Task Families Add

The project is not one task with seven filenames. Each paper-core family isolates a
different way that a bridge concept can be useful.

When you open a world from one of these families, the fastest way to orient
yourself is to ask two questions: what kind of bridge is probably hidden here,
and what visible clue should make me suspect it?

| Family | Typical hidden bridge | What to notice in this world |
| --- | --- | --- |
| `predicate_invention` | A new conjunctive predicate that names a recurring pattern. | Notice whether the same bundle of visible atoms keeps reappearing inside several targets or transition steps. |
| `lemma_invention` | A reusable derived rule rather than a new predicate. | Notice whether one multi-hop proof pattern keeps being replayed and could be collapsed into one theorem. |
| `analogy` | A transport map or morphism between two visible theories. | Notice whether two theory blocks look structurally parallel even though their symbols have been renamed. |
| `invariant` | A preserved property that survives transitions. | Notice which facts stay stable as the world steps forward, because that stability usually is the bridge. |
| `quotient` | A canonicalization or equivalence view over surface objects. | Notice whether several visible objects or terms differ syntactically but behave as if they should be treated as the same thing. |
| `normal_form` | A rewrite-aware abstraction over normalized structure. | Notice whether the real action happens after rewriting, not in the raw unreduced syntax you first read. |
| `multi_step` | A bridge whose value grows with depth. | Notice whether shallow visible steps are easy but deeper targets keep repeating the same expansion pattern. |

Together, these families make the project a benchmark suite about abstraction,
not a single puzzle type repeated at scale.

## Family Examples

The descriptions above explain what each family is trying to measure. This
section gives one concrete example for every disclosed paper-core family so the
cases do not stay abstract.

### Predicate invention example

Representative files:

- [strong candidate](../examples/predicate_invention/gold_candidate.abw)
- [weak candidate](../examples/predicate_invention/trivial_candidate.abw)

Strong candidate:

```abw
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
```

Weak candidate:

```abw
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_step: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), f1(y))
```

The strong version names a genuinely useful conjunction. The weak one mainly
wraps a visible relation, which is why ABW treats it as a much less interesting
bridge.

### Lemma invention example

Representative file:

- [gold candidate](../examples/lemma_invention/gold_candidate.abw)

Example:

```abw
lemma chain3_candidate: forall x:S0. A(x) -> D(h(g(f(x))))
```

The bridge here is a reusable shortcut theorem. No new predicate is introduced;
the conceptual gain comes from collapsing a visible multi-hop derivation into
one rule that can be reused everywhere.

### Analogy example

Representative file:

- [gold candidate](../examples/analogy/gold_candidate.abw)

Example:

```abw
morphism Guess : Left -> Right {
  L0 -> R0
  l0 -> r0
  lf -> rf
  lg -> rg
  LP -> RP
  LQ -> RQ
}
```

This family asks whether the candidate can discover a structure-preserving map
between two theories. The bridge is not a local theorem but a transport
relationship.

### Invariant example

Representative file:

- [gold candidate](../examples/invariant/gold_candidate.abw)

Example:

```abw
define Preserved(x:S0) := A(x) & B(x) & C(x)
lemma preserved_step: forall x:S0. Preserved(x) -> Preserved(step(x))
```

This is close to predicate invention, but the missing abstraction is
specifically about persistence across transitions. The candidate discovers the
combined invariant rather than a one-off conjunction.

### Quotient example

Representative file:

- [gold candidate](../examples/quotient/gold_candidate.abw)

Example:

```abw
define Equivalent(x:S0, y:S0) := R(x,y)
define Canonical(x:S0) := norm(x) = x
lemma good_on_canonical: forall x:S0. Good(x) -> Good(norm(x))
```

Here the abstraction is about better representatives. The hidden bridge says
that the solver should reason on canonical forms instead of on every raw term
variant separately.

### Normal form example

Representative file:

- [gold candidate](../examples/normal_form/gold_candidate.abw)

Example:

```abw
define IsNormal(x:T) := n(x) = x
lemma done_after_normalize: forall x:T. IsNormal(x) -> Done(x)
```

This case makes the rewrite layer matter directly. The bridge concept is that
already-normal terms have a useful downstream property, which lets the solver
talk about normalized structure at a higher level.

### Multi-step example

Representative file:

- [gold candidate](../examples/multi_step/gold_candidate.abw)

Example:

```abw
define PairStable(x:S0, y:S1) := A(x) & B(y) & R(x,y)
lemma pair_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f(x), g(y))
lemma pair_to_k: forall x:S0 y:S1. PairStable(x,y) -> K(h(x,y))
```

The bridge is now a small ladder rather than one isolated object. The candidate
builds an intermediate abstraction and then reuses it for a second theorem.

## Shipped Example Anchors By Family

The formal candidates above show what a good bridge looks like. The table below
keeps the references inside the tracked repository surface by pointing to the
family example candidates under `examples/`.

If you want the full packaged public/private renderings for one family, generate
a local world and inspect its `nl/` directory:

```bash
python -m abw_core generate-world \
  --family <family> \
  --seed 7 \
  --output artifacts/<family>_world
```

Then open the generated `nl/problem.md`, `nl/theorem_cards.md`,
`nl/examples.md`, `nl/hidden_bridge_private.md`, and
`nl/gold_informal_solution_private.md` files under that world root.

| Family | What to notice in this world | Shipped example |
| --- | --- | --- |
| `predicate_invention` | Notice how the visible facts and targets keep circling back to the same cross-sort conjunction, which is the cue that the world wants one new named predicate. | [gold candidate](../examples/predicate_invention/gold_candidate.abw), [weak candidate](../examples/predicate_invention/trivial_candidate.abw) |
| `lemma_invention` | Notice how the visible story keeps replaying the same derived jump, which makes the missing bridge feel more like a reusable theorem than a new predicate. | [gold candidate](../examples/lemma_invention/gold_candidate.abw) |
| `analogy` | Notice how two visible theory blocks rhyme with each other so strongly that the real task is spotting the transport map hidden behind the renaming. | [gold candidate](../examples/analogy/gold_candidate.abw) |
| `invariant` | Notice how the public dynamics keep preserving the same cluster of properties, which is the tell that the bridge is an invariant rather than a one-off coincidence. | [gold candidate](../examples/invariant/gold_candidate.abw) |
| `quotient` | Notice how several surface forms behave as though they ought to collapse to one representative, which is the cue to think in terms of equivalence and canonicalization. | [gold candidate](../examples/quotient/gold_candidate.abw) |
| `normal_form` | Notice how the public rules become simpler only after rewriting, which is the sign that the bridge lives at the normalized level instead of the raw syntax. | [gold candidate](../examples/normal_form/gold_candidate.abw) |
| `multi_step` | Notice how shallow reasoning works locally but deeper targets keep repeating the same ladder, which is the clue that the missing bridge compounds across several steps. | [gold candidate](../examples/multi_step/gold_candidate.abw) |

## How Scoring Reflects The Concept

ABW does not score candidates by exact string match. That would miss the whole
point of bridge discovery. Instead, the score asks whether the candidate is
doing the job of the hidden bridge.

The scoring logic combines several pressures:

- validity: the candidate must parse, typecheck, avoid private names, and be
  sound on the bounded world
- hidden-goal utility: the candidate should help solve hidden targets or reduce
  their proof cost
- compression: useful abstractions should simplify reasoning relative to their
  own size
- novelty: trivial wrappers around visible predicates should not get credit
- bounded semantic equivalence: a good candidate should behave like the hidden
  bridge on the public world and nearby counterfactual variants
- minimality: unnecessary candidate bulk is penalized

This is why the benchmark can reward a candidate even if it does not reproduce
the exact gold name. What matters is whether it captures the same organizing
role.

## Why Counterexamples And Countermodels Exist

A benchmark about theory formation is hard to use if failure gives no useful
feedback. ABW therefore includes bounded diagnostics.

When a lemma or theorem candidate is invalid, the runtime can return a grounded
counterexample witness: one substitution where the premises hold but the
conclusion fails.

When a goal is not derivable, the runtime can return a bounded public
countermodel: the generated term universe, predicate extensions, and the atoms
that remain false.

These are not decorative debugging extras. They are part of the project’s
philosophy: abstraction research is easier to iterate on when the benchmark can
show where a candidate goes wrong.

## What The Solver Backends Change

The default runtime remains local and bounded. Optional `z3` and `cvc5`
backends add stronger finite-model diagnostics on top of that local backbone.

They do not replace the benchmark’s core proof-cost logic. Instead, they answer
a narrower question: can a stronger bounded model search find a counterexample
or countermodel that the local least-model view misses?

This keeps the project honest about its boundaries:

- the local runtime remains the source of proof-cost accounting
- solver backends upgrade diagnostics, not the whole semantics
- a solver-backed benchmark profile is about stronger failure detection, not a
  different task definition

## How Interactive Sessions Fit In

ABW also includes a first public interactive loop. This matters because bridge
discovery is usually iterative.

The session layer lets a solver:

- validate a candidate on the public surface
- ask for bounded examples
- probe bounded public equivalence behavior
- inspect bounded countermodels

The session keeps a query budget and records a transcript. Hidden scoring still
happens only at the final submission step. That design keeps the exploration
process visible without collapsing the benchmark into direct answer revealing.

## How To Read A Packaged World

A new reader often opens one generated world and sees many files. The intended
reading order is:

1. `metadata.json`
   Learn the family, seed, and generation settings.

2. `nl/problem.md`
   Read the public problem in plain language.

3. `formal/axioms.abw`, `formal/visible_facts.abw`, and
   `formal/visible_theorems.abw`
   Understand the visible symbolic structure.

4. `formal/targets_visible.abw`
   See what the public surface already makes salient.

5. `nl/theorem_cards.md` and `nl/nl_alignment.json`
   Check how formal statements were rendered into natural language.

6. `formal/scoring_config.json`
   Understand what the benchmark will reward.

7. Private bridge and gold-solution files
   Only after exploration, use these to inspect what the intended abstraction
   was and how far a candidate diverged from it.

This order mirrors the project’s conceptual structure: visible evidence first,
hidden organizing principle second.

## What This Project Is Good For

ABW is especially useful when you want to study:

- whether a model can name a latent concept rather than only prove a target
- whether a candidate abstraction reduces future reasoning cost
- whether analogy, invariant, or compositional reasoning emerges from visible local
  structure
- how an interactive symbolic exploration loop changes abstraction quality
- how bounded local reasoning compares to stronger finite-model diagnostics

It is a good fit for research on abstraction, theory formation, latent concept
discovery, symbolic scaffolding, and benchmarkable interactive reasoning.

## What This Project Is Not

ABW is not trying to be:

- a complete first-order theorem prover
- a proof assistant
- a benchmark for open-world natural-language reasoning
- an unbounded model-checking environment
- a substitute for human mathematical discovery

The project succeeds when it stays clear about that scope. It is a controlled,
auditable testbed for abstraction recovery under bounded symbolic conditions.

## Practical Boundaries

Several boundaries are worth keeping explicit when interpreting results.

- Semantic equivalence is bounded by the generated term universe, not full
  theorem equivalence.
- Novelty is heuristic rather than a complete abstraction-quality measure.
- The counterfactual suite is small and local by design.
- Interactive exploration stays public-only.
- Solver-backed profiles strengthen bounded diagnostics, but they do not turn
  ABW into a complete SMT or proof-assistant workflow.

These limitations are not flaws in disguise. They are part of the design
trade-off that makes the benchmark deterministic and locally inspectable.

## How The Repository Fits The Concept

The repository is organized around the conceptual pipeline:

- generation creates worlds whose hidden bridges are genuinely useful
- packaging separates public and private views
- scoring rewards candidates for doing the bridge’s job
- interactive sessions expose bounded public exploration
- docs and examples keep the benchmark readable as a research artifact

That is why the project contains both formal runtime code and concept-facing
documentation. One without the other would leave the benchmark hard to use:
formal machinery without interpretation is opaque, and interpretation without
formal machinery is not a benchmark.

## Where To Go Next

For more detailed follow-up after this guide:

- use `README.md` for practical commands and dataset entrypoints
- use `docs/dsl.md` for the formal language surface
- use `docs/scoring.md` for the detailed evaluation logic
- use `docs/structured_artifacts.md` to understand JSON and YAML sidecars
- use `DISCLOSURE.md` for the disclosure scope and omitted artifact policy
