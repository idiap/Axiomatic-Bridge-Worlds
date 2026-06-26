# ABW DSL

The ABW core is a small, typed, many-sorted Horn language extended with
rewrites, named theories, and signature morphisms. The recursive-descent parser
in [abw_core/dsl/parser.py](../abw_core/dsl/parser.py) is normative;
[abw_core/dsl/grammar.ebnf](../abw_core/dsl/grammar.ebnf) is an overview of the
accepted surface.

## Supported Statements

```text
sort S0
const c0 : S0
func f0 : S0 -> S0
pred P0 : S0
rewrite r1: a(b(x)) -> n(x)
axiom a1: forall x:S0. P0(x) -> P0(f0(x))
lemma l1: forall x:S0 y:S1. R(x,y) & P0(x) -> R(f0(x), y)
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
fact base: P0(c0)
goal hidden_step_2: R(f0(f0(c0)), f1(f1(d0))) & P0(f0(f0(c0))) & P1(f1(f1(d0)))
theory Left {
  sort L0
  func lf : L0 -> L0
  pred LP : L0
  theorem keep: forall x:L0. LP(x) -> LP(lf(x))
}
morphism M : Left -> Left {
  L0 -> L0
  lf -> lf
  LP -> LP
}
```

## Language Layers

- **`v0`** — many-sorted Horn clauses, conjunctive definitions, ground facts,
  conjunctive goals.
- **`v1`** — equality atoms, rewrite rules, and rewrite-aware proving for
  normal-form worlds.
- **`v2`** — named theory blocks and signature morphisms for analogy and
  theorem transport.

## Model-Output Tolerances

The parser is strict, but model candidates arrive in varied surface styles
(trailing commas, JSON-style separators, code fences). Tolerance is applied
**outside** the parser, at the scoring boundary, so the grammar stays strict:

- `_normalize_candidate_surface` (in
  [abw_core/scorer/evaluator.py](../abw_core/scorer/evaluator.py)) is the
  normative step — it strips trailing `,`/`;` after morphism mapping entries
  before parsing.
- Target adapters may additionally unwrap Markdown code fences and a
  `{"candidate": "..."}` JSON envelope.

These tolerances are intentional and load-bearing for cross-model evaluation.

## Design Constraints

- the prover is bounded forward chaining, not a full first-order prover
- definitions remain conjunctive
- equality support is rewrite-driven and intentionally local
- the external-backend surface (subprocess protocol plus optional Z3/cvc5
  finite-model diagnostics) is not a complete SMT or proof-assistant workflow
