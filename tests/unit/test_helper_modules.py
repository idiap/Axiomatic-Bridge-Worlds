# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Focused regression tests for small helper modules across the runtime.

The ABW stack has many tiny helpers whose individual failures are easy to miss
in end-to-end tests. This file keeps those local contracts explicit so support
utilities can evolve without silently changing semantics.
"""

from pathlib import Path

import pytest

from abw_core import ir
from abw_core.dsl.lexer import LexError, tokenize
from abw_core.dsl.parser import parse_document as parse_dsl_document
from abw_core.dsl.printer import format_document
from abw_core.generator.distractors import predicate_invention_distractors
from abw_core.generator.obfuscation import default_world_id
from abw_core.generator.templates import iterate_term, unary_clause
from abw_core.nl.align import entry
from abw_core.nl.leakage import detect_hidden_name_leaks
from abw_core.nl.naming import build_naming
from abw_core.prover.backends import BackendConfig, backend_from_payload, build_closure_with_backend
from abw_core.prover.horn import build_closure
from abw_core.prover.proofs import goal_cost, missing_goal_atoms
from abw_core.scorer.compression import compression_score
from abw_core.scorer.evaluator import load_candidate_text
from abw_core.serde import proof_result_from_dict, proof_result_to_dict, term_from_dict, term_to_dict


def test_lexer_parser_and_printer_helpers_round_trip() -> None:
    source = """
sort S
const c : S
func step : S -> S
pred Hold : S
axiom keep: forall x:S. Hold(x) -> Hold(step(x))
"""

    tokens = tokenize(source)
    document = parse_dsl_document(source)
    rendered = format_document(document)

    assert tokens[-1].kind == "EOF"
    assert parse_dsl_document(rendered) == document


def test_lexer_rejects_unexpected_character() -> None:
    with pytest.raises(LexError):
        tokenize("sort S\n@")


def test_generation_and_nl_helpers_produce_stable_shapes() -> None:
    signature = ir.Signature(
        sorts=(ir.Sort("S0"), ir.Sort("S1")),
        constants=(ir.ConstantSymbol("c0", "S0"), ir.ConstantSymbol("d0", "S1")),
        functions=(ir.FunctionSymbol("step", ("S0",), "S0"),),
        predicates=(
            ir.PredicateSymbol("P0", ("S0",)),
            ir.PredicateSymbol("R", ("S0", "S1")),
        ),
    )
    x = ir.Variable("x", "S0")

    naming = build_naming(signature)
    stepped = iterate_term("step", ir.ConstTerm("c0"), 2)
    clause = unary_clause("keep", x, "P0", "P0", "step")
    distractors = predicate_invention_distractors()

    assert default_world_id("predicate_invention", 7) == "abw_predicate_invention_0007"
    assert naming.sorts["S0"]
    assert naming.predicates["P0"] == "P0"
    assert naming.predicates["R"] == "R"
    assert naming.constants["c0"].startswith(naming.sorts["S0"])
    assert stepped == ir.FuncTerm("step", (ir.FuncTerm("step", (ir.ConstTerm("c0"),)),))
    assert clause.name == "keep"
    assert len(distractors[0]) == 2
    assert entry("A", "B", "C") == {"nl": "A", "formal": "B", "source": "C"}
    assert detect_hidden_name_leaks({"problem.md": "PairStable holds."}, {"PairStable"}) == [
        {"path": "problem.md", "hidden_name": "PairStable"}
    ]


def test_prover_backend_proofs_and_serde_helpers_round_trip(tmp_path: Path) -> None:
    signature = ir.Signature(
        sorts=(ir.Sort("S"),),
        constants=(ir.ConstantSymbol("c", "S"),),
        predicates=(ir.PredicateSymbol("P", ("S",)),),
    )
    fact = ir.Fact("base", ir.Atom("P", (ir.ConstTerm("c"),)))
    goal = (ir.Atom("P", (ir.ConstTerm("c"),)),)

    direct = build_closure(signature, facts=(fact,), clauses=())
    through_backend = build_closure_with_backend(
        signature,
        facts=(fact,),
        clauses=(),
        backend=BackendConfig(),
    )
    serialized = proof_result_to_dict(through_backend)
    restored = proof_result_from_dict(serialized)
    term = iterate_term("step", ir.ConstTerm("c"), 1)

    assert through_backend == direct
    assert restored == through_backend
    assert missing_goal_atoms(through_backend.derivations, goal) == ()
    assert goal_cost(through_backend.derivations, goal) == 0
    assert term_from_dict(term_to_dict(term)) == term
    assert backend_from_payload({"name": "local", "command": ["python", "-m", "demo"]}) == BackendConfig(
        name="local",
        command=("python", "-m", "demo"),
    )
    assert compression_score([5, 3], [2, 1], candidate_size=2) > 0.0

    candidate_path = tmp_path / "candidate.abw"
    candidate_path.write_text("define Keep(x:S) := P(x)\n", encoding="utf-8")
    assert load_candidate_text(candidate_path) == "define Keep(x:S) := P(x)\n"
