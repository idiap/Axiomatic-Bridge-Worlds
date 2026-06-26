# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Smoke coverage for support modules that underpin the main runtime.

This file does broad, low-cost contract checks over lexer, parser, naming,
rendering, proving, scoring, and serialization helpers so infrastructure drift
shows up quickly even when higher-level feature tests still pass.
"""

from pathlib import Path

import pytest

from abw_core import ir
from abw_core.generator import WorldGenerationRequest, generate_world
import abw_core.dsl.lexer as lexer
import abw_core.dsl.parser as parser
import abw_core.dsl.printer as printer
import abw_core.generator.distractors as distractors
import abw_core.generator.obfuscation as obfuscation
import abw_core.generator.templates as templates
import abw_core.nl.align as align
import abw_core.nl.leakage as leakage
import abw_core.nl.naming as naming
import abw_core.nl.render as render
import abw_core.prover.backends as backends
import abw_core.prover.horn as horn
import abw_core.prover.proofs as proofs
import abw_core.prover.rewrite as rewrite
import abw_core.scorer.compression as compression
import abw_core.scorer.equivalence as equivalence
import abw_core.scorer.evaluator as evaluator
import abw_core.scorer.novelty as novelty
import abw_core.serde as serde
from abw_core.typecheck import check_document, extend_signature_with_definitions


def _toy_signature() -> ir.Signature:
    return ir.Signature(
        sorts=(ir.Sort("S"), ir.Sort("T")),
        constants=(ir.ConstantSymbol("c", "S"),),
        functions=(ir.FunctionSymbol("step", ("S",), "S"),),
        predicates=(
            ir.PredicateSymbol("P", ("S",)),
            ir.PredicateSymbol("R", ("S", "T")),
        ),
    )


def test_dsl_modules_round_trip_and_reject_bad_tokens() -> None:
    source = "sort S\nconst c : S\npred P : S\nfact base: P(c)\n"

    tokens = lexer.tokenize(source + "# ignored comment\n")
    document = parser.parse_document(source)

    assert tokens[0].kind == "IDENT"
    assert parser.parse_document(printer.format_document(document)) == document

    with pytest.raises(lexer.LexError):
        lexer.tokenize("@")


def test_generation_and_nl_support_modules_behave_deterministically() -> None:
    signature = _toy_signature()
    stepped = templates.iterate_term("step", ir.ConstTerm("c"), 2)
    clause = templates.unary_clause("keep", ir.Variable("x", "S"), "P", "P", "step")
    predicates, axioms, facts, theorems = distractors.predicate_invention_distractors()
    scheme = naming.build_naming(signature)
    leaks = leakage.detect_hidden_name_leaks({"problem.md": "SecretBridge appears here."}, {"SecretBridge"})

    assert obfuscation.default_world_id("predicate_invention", 7) == "abw_predicate_invention_0007"
    assert stepped == ir.FuncTerm("step", (ir.FuncTerm("step", (ir.ConstTerm("c"),)),))
    assert clause.premises[0].predicate == "P"
    assert clause.conclusion.predicate == "P"
    assert len(predicates) == 2
    assert len(axioms) == 2
    assert len(facts) == 2
    assert len(theorems) == 1
    assert scheme.sorts["S"] == "mav"
    assert scheme.predicates["P"] == "P"
    assert scheme.predicates["R"] == "R"
    assert scheme.constants["c"] == "mav-0"
    assert align.entry("alpha", "P(c)", "visible_facts") == {
        "nl": "alpha",
        "formal": "P(c)",
        "source": "visible_facts",
    }
    assert leaks == [{"path": "problem.md", "hidden_name": "SecretBridge"}]


def test_backend_proof_scoring_and_serde_helpers_round_trip() -> None:
    signature = _toy_signature()
    fact = ir.Fact("base", ir.Atom("P", (ir.ConstTerm("c"),)))
    goal_atoms = (ir.Atom("P", (ir.ConstTerm("c"),)),)

    local = horn.build_closure(signature, facts=(fact,), clauses=())
    via_backend = backends.build_closure_with_backend(
        signature,
        facts=(fact,),
        clauses=(),
        backend=backends.BackendConfig(),
    )
    term = templates.iterate_term("step", ir.ConstTerm("c"), 1)
    restored_term = serde.term_from_dict(serde.term_to_dict(term))
    restored_proof = serde.proof_result_from_dict(serde.proof_result_to_dict(local))
    payload_backend = backends.backend_from_payload(
        {"name": "subprocess", "command": ["python", "-m", "driver"]}
    )

    assert via_backend.derivations.keys() == local.derivations.keys()
    assert proofs.missing_goal_atoms(local.derivations, goal_atoms) == ()
    assert proofs.goal_cost(local.derivations, goal_atoms) == 0
    assert restored_term == term
    assert restored_proof.derivations.keys() == local.derivations.keys()
    assert restored_proof.terms_by_sort == local.terms_by_sort
    assert payload_backend == backends.BackendConfig(name="subprocess", command=("python", "-m", "driver"))
    assert compression.compression_score([3, 2], [1, 2], candidate_size=1) > 0.0


def test_render_rewrite_and_scoring_helpers_cover_direct_modules() -> None:
    x = ir.Variable("x", "S")
    rule = ir.RewriteRule(
        "collapse",
        ir.FuncTerm("a", (ir.FuncTerm("b", (ir.VarTerm(x),)),)),
        ir.FuncTerm("n", (ir.VarTerm(x),)),
    )
    subject = ir.FuncTerm("a", (ir.FuncTerm("b", (ir.ConstTerm("c"),)),))
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=7))
    candidate = parser.parse_document(
        """
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
"""
    )
    candidate_signature = extend_signature_with_definitions(world.signature, candidate.definitions)
    check_document(candidate, base_signature=world.signature)
    candidate_closure = horn.build_closure(
        candidate_signature,
        facts=world.visible_facts,
        clauses=world.public_clauses() + candidate.lemmas + candidate.theorems,
        definitions=candidate.definitions,
        rewrites=world.rewrites,
        max_term_depth=int(world.metadata.get("max_term_depth", 3)),
    )
    rendered = render.render_world(world)

    assert rewrite.match_term(rule.lhs, subject) == {"x": ir.ConstTerm("c")}
    assert rewrite.normalize_term(subject, (rule,)) == ir.FuncTerm("n", (ir.ConstTerm("c"),))
    assert rewrite.normalize_atom(
        ir.Atom("=", (ir.FuncTerm("n", (ir.ConstTerm("c"),)), ir.ConstTerm("c"))),
        (),
    ) == ir.Atom("=", (ir.ConstTerm("c"), ir.FuncTerm("n", (ir.ConstTerm("c"),))))
    assert "# Problem" in rendered.problem_md
    assert "P0 holds of" in rendered.examples_md
    assert "R holds between" in rendered.examples_md or "R holds between" in rendered.theorem_cards_md
    assert rendered.alignment
    assert 0.0 <= novelty.novelty_score(
        candidate.definitions,
        world,
        candidate_closure,
        rewrites=world.rewrites,
    ) <= 1.0
    assert 0.0 <= equivalence.semantic_equivalence_score(
        world,
        candidate,
        candidate_signature,
        candidate_closure,
    ) <= 1.0


def test_candidate_text_loader_reads_utf8_files(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.abw"
    candidate.write_text("define X(x:S) := P(x)\n", encoding="utf-8")

    assert evaluator.load_candidate_text(candidate) == "define X(x:S) := P(x)\n"
