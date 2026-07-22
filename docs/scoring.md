# Scoring

Candidates are judged on usefulness, not exact string match. For dataset-level
evaluation against an external target system, see the
[benchmark task guide](benchmark_task.md).

## Per-World Metrics

| Metric | What it measures |
| --- | --- |
| `validity_score` | Candidate parses, typechecks, avoids private names, and its lemmas are sound over the bounded world. Unsound clauses get grounded counterexample witnesses; the optional `z3`/`cvc5` backends also reject clauses that only look valid because the bounded least model makes their premises vacuous. |
| `hidden_goal_solve_rate` | Fraction of hidden goals provable under the proof budget. |
| `proof_cost_reduction` | Aggregate reduction in positive proof steps. |
| `compression_score` | Benefit relative to candidate size. |
| `semantic_equivalence_score` | Bounded semantic overlap against the hidden bridge (see below). |
| `novelty_score` | Bounded, alias-aware penalty for shallow definitions. |
| `minimality_score` | Smaller candidates score better when they stay useful. |

**Semantic equivalence** compares definitions by the extension they induce over
the bounded closure, and lemmas/theorems by their grounded consequences; matching
is symmetric, so extra unmatched candidate structure lowers the score. Morphisms
combine theorem-transport validity with mapping overlap. Bridge tasks also check
a small counterfactual suite (ablating visible facts/theorems) to separate
bridges that only fit the packaged world from bridges that stay aligned across
nearby public worlds.

**Novelty:** direct single-atom wrappers around visible predicates score near
zero (even when syntactically disguised but extension-equal); multi-atom visible
conjunctions earn credit, reduced if they collapse back to one visible relation
across the diagnostic suite.

Failed goals can also be inspected outside scoring via
`python -m abw_core countermodel-goal`, which returns the bounded model where the
queried goal stays false.

## Interactive Sessions

Sessions add one metric outside the candidate score —
`exploration_efficiency_score`: the fraction of unused interactive queries left
when `finish-session` closes. Exploration is public-only:

- `validate` — parse, typecheck, reject private names, return bounded clause
  counterexamples (and public structural validation for morphisms)
- `equivalence` — how stably a candidate behaves across the public diagnostic
  suite
- `examples` — bounded positive examples for a requested predicate
- `countermodel` — the bounded public model for a failed visible goal or atom

Hidden-goal scoring still happens only at final submission.

## Backends

The default prover is the in-process bounded forward chainer. The CLI can
delegate proof work through a subprocess protocol, or use the optional `z3`/`cvc5`
backends, which keep proof-cost closure on the local engine but add bounded
finite-model search for counterexamples:

```bash
python -m abw_core score-candidate \
  --world examples/tiny_world \
  --candidate examples/predicate_invention/gold_candidate.abw \
  --prover-backend z3        # or: cvc5
```

The same search is available through the subprocess drivers
`abw_core.prover.z3_driver` and `abw_core.prover.cvc5_driver`. See
[Workflows](workflows.md) for the full subprocess invocation.

## Caveats

Semantic equivalence is bounded by the generated term universe, not full theorem
equivalence; the counterfactual suite is small and local; solver paths upgrade
counterexamples to bounded finite-model search, not complete theorem proving;
interactive queries stay bounded and public-only; novelty is a bounded heuristic.

## Dataset-Level Aggregation

When run as a benchmark, per-world JSON records roll up into dataset, split, and
family summaries:

- the primary leaderboard metric is the mean of `total_score`
- target invocations that crash, time out, or emit malformed output contribute
  zero metric values
- invalid candidates still contribute their scored metrics (usually zero total
  score, but preserved operational accounting)
