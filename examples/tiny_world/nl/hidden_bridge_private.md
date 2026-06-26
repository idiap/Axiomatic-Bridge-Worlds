# Hidden Bridge

- define Aligned(x:S0, y:S1) := R(x, y) & P0(x) & P1(y)
- lemma aligned_step: forall x:S0 y:S1. Aligned(x, y) -> Aligned(f0(x), f1(y))
