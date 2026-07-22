# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Evaluate ABW candidate bridges against public worlds and hidden targets.

This module is the point where the ABW benchmark turns a candidate file into a
judgment. It coordinates parsing, safety checks, bounded proof search, family-
specific scoring logic, and report assembly.

Why this file matters
---------------------
ABW is not a single-task benchmark. Some worlds expect a definition or lemma,
and analogy worlds expect a morphism. The evaluator therefore acts as the
benchmark's central arbitration layer: it decides which scoring regime applies,
gathers the right diagnostic evidence, and normalizes the result into one
report shape.

Conceptual flow
---------------
1. load or receive one packaged world
2. parse the candidate and reject private-name leakage
3. choose the prover backend that should supply bounded evidence
4. route to the appropriate candidate family evaluation:
   - bridge definitions and lemmas
   - theory morphisms
5. aggregate semantic, structural, and operational metrics into one score

Concrete example
----------------
- In a predicate-invention world, the evaluator checks whether a proposed
  definition and lemma make hidden targets cheaper or solvable within budget.
- In an analogy world, the evaluator treats the candidate as a morphism and
  asks whether transported theorems stay valid in the target theory.

Paper-style framing
-------------------
One concise way to describe the evaluator is:

    A bridge is good when it is valid, useful on the hidden targets, compact
    enough to count as an abstraction, and semantically aligned with the
    structure the world was built to hide.

This file operationalizes that sentence in a bounded, deterministic way.

Limitations
-----------
- The proof and model checks are intentionally bounded by packaged depth limits.
- Semantic and novelty judgments are local heuristics, not full theorem
  equivalence procedures.
- Family routing is driven by the hidden-bridge shape in the packaged world,
  so mixed bridge styles are not jointly optimized here.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from abw_core import ir
from abw_core.dsl import parse_document
from abw_core.packager import load_world
from abw_core.prover import (
    BackendConfig,
    ProofResult,
    build_closure_with_backend,
    find_clause_counterexamples_with_backend,
    goal_cost,
    public_diagnostic_models,
)
from abw_core.prover.backends import backend_from_payload
from abw_core.scorer.compression import compression_score
from abw_core.scorer.equivalence import semantic_equivalence_score
from abw_core.scorer.metrics import candidate_size, minimality_score, proof_cost_reduction
from abw_core.scorer.novelty import novelty_score
from abw_core.scorer.weights import ANALOGY_WEIGHTS, NON_ANALOGY_WEIGHTS, composite_score, effective_weights
from abw_core.typecheck import (
    TypecheckError,
    build_theory_signatures,
    check_document,
    reject_hidden_symbol_names,
    validate_morphism,
)


def load_candidate_text(path: str | Path) -> str:
    """Load the raw candidate surface that will later be parsed and scored.

    The evaluator keeps file I/O separate from parsing so CLI and programmatic
    callers can share the same downstream evaluation path while choosing
    whether the candidate originates from disk, memory, or a subprocess.
    """

    return Path(path).read_text(encoding="utf-8")


def _normalize_candidate_surface(candidate_text: str) -> str:
    """Apply narrow, model-output-only cleanup before parsing.

    The canonical ABW printer writes one morphism mapping per line without
    separators. Small LLMs often add JSON/list-style commas after each mapping.
    Those commas do not change the intended symbol map, so the evaluator strips
    trailing comma/semicolon separators only inside morphism bodies. The core
    DSL parser remains strict; this is just an adapter tolerance at the scoring
    boundary.
    """

    normalized: list[str] = []
    in_morphism = False
    for line in candidate_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("morphism ") and stripped.endswith("{"):
            in_morphism = True
            normalized.append(line)
            continue
        if in_morphism and stripped == "}":
            in_morphism = False
            normalized.append(line)
            continue
        if in_morphism and "->" in stripped:
            line = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\s*[,;]\s*$", r"\1", line)
        normalized.append(line)
    return "\n".join(normalized)


def _parse_candidate(candidate_text: str) -> ir.Document:
    """Parse a candidate and enforce the benchmark's allowed submission shape.

    Candidate files are meant to propose bridges, not redefine the public world
    itself. This helper therefore rejects any candidate that tries to smuggle
    in signature declarations, public axioms, visible facts, or rewrite rules.
    The accepted surface is deliberately narrow: definitions, lemmas, theorems,
    and morphisms.
    """

    document = parse_document(_normalize_candidate_surface(candidate_text))
    if (
        document.sorts
        or document.constants
        or document.functions
        or document.predicates
        or document.axioms
        or document.facts
        or document.goals
        or document.theories
        or document.rewrites
    ):
        raise TypecheckError("Candidate files may only contain definitions, lemmas, theorems, or morphisms.")
    return document


def _backend_config(
    world: ir.World,
    *,
    backend_name: str | None = None,
    backend_command: tuple[str, ...] = (),
) -> BackendConfig:
    """Resolve which prover backend should supply bounded evidence.

    The benchmark allows three sources of backend choice:
    1. an explicit runtime override from the caller
    2. a packaged backend profile stored in the world metadata
    3. the default local prover

    This precedence rule keeps benchmark execution reproducible while still
    allowing controlled experiments with solver-backed diagnostics.
    """

    if backend_name is not None:
        return BackendConfig(name=backend_name, command=backend_command)
    configured = world.scoring_config.get("prover_backend")
    if isinstance(configured, dict):
        return backend_from_payload(configured)
    return BackendConfig()


def _theory_named(world: ir.World, name: str) -> ir.Theory | None:
    """Look up one named public theory inside a packaged world.

    Morphism evaluation needs to recover the source and target theory blocks
    referenced by the candidate. Returning `None` rather than raising keeps the
    caller free to fold the failure into normal benchmark JSON results.
    """

    for theory in world.theories:
        if theory.name == name:
            return theory
    return None


def _translate_term(term: ir.Term, mapping: dict[str, str]) -> ir.Term:
    """Transport one term through a morphism's symbol mapping.

    Morphism worlds are evaluated by translating source-theory theorems into
    the target vocabulary and then checking whether the translated theorems
    hold. This helper performs the term-level part of that transport.
    """

    if isinstance(term, ir.VarTerm):
        mapped_sort = mapping.get(term.variable.sort, term.variable.sort)
        return ir.VarTerm(ir.Variable(term.variable.name, mapped_sort))
    if isinstance(term, ir.ConstTerm):
        return ir.ConstTerm(mapping.get(term.name, term.name))
    if isinstance(term, ir.FuncTerm):
        return ir.FuncTerm(mapping.get(term.name, term.name), tuple(_translate_term(arg, mapping) for arg in term.args))
    raise TypeError(f"Unsupported term type: {type(term)!r}")


def _translate_atom(atom: ir.Atom, mapping: dict[str, str]) -> ir.Atom:
    """Transport one atom through a morphism while preserving equality atoms.

    Equality is treated specially because it is logical structure, not a named
    predicate that should be remapped through the user-provided symbol map.
    """

    if atom.predicate == "=":
        return ir.Atom("=", tuple(_translate_term(term, mapping) for term in atom.terms))
    return ir.Atom(mapping.get(atom.predicate, atom.predicate), tuple(_translate_term(term, mapping) for term in atom.terms))


def _translate_clause(clause: ir.HornClause, morphism: ir.SignatureMorphism) -> ir.HornClause:
    """Translate one theorem clause into the target side of a candidate morphism.

    The resulting clause is what the evaluator actually proves or refutes inside
    the target theory. Prefixing the clause name with the morphism name keeps
    transported proof obligations traceable in reports and diagnostics.
    """

    translated_variables = tuple(
        ir.Variable(variable.name, morphism.mapping.get(variable.sort, variable.sort)) for variable in clause.variables
    )
    return ir.HornClause(
        name=f"{morphism.name}_{clause.name}",
        variables=translated_variables,
        premises=tuple(_translate_atom(atom, morphism.mapping) for atom in clause.premises),
        conclusion=_translate_atom(clause.conclusion, morphism.mapping),
    )


def _zero_metrics(candidate: ir.Document, *, minimality: float | None = None) -> dict[str, float]:
    """Build the all-zero metric block used for invalid or failed candidates.

    `minimality` defaults to the candidate's own minimality score, which is
    still well defined for a structurally invalid candidate. Pass `0.0` for the
    no-candidate case where no minimality credit should be reported.
    """

    return {
        "validity_score": 0.0,
        "hidden_goal_solve_rate": 0.0,
        "proof_cost_reduction": 0.0,
        "compression_score": 0.0,
        "semantic_equivalence_score": 0.0,
        "novelty_score": 0.0,
        "minimality_score": minimality_score(candidate) if minimality is None else minimality,
        "candidate_size": candidate_size(candidate),
        "total_score": 0.0,
    }


def _invalid_report(errors: list[str], candidate: ir.Document, *, minimality: float | None = None) -> dict[str, Any]:
    """Assemble a full invalid score-report with a zeroed metric block."""

    return {
        "valid": False,
        "errors": errors,
        "metrics": _zero_metrics(candidate, minimality=minimality),
        "goals": [],
        "counterexamples": [],
    }


def _evaluate_morphism_candidate(
    world: ir.World,
    candidate: ir.Document,
    errors: list[str],
    *,
    backend: BackendConfig,
) -> dict[str, Any]:
    """Evaluate morphism candidates by transporting source theorems.

    Morphism worlds are not about inventing a new local predicate. They are
    about discovering a structure-preserving translation between two public
    theories. The candidate is therefore judged on three linked questions:

    1. Is the morphism well-typed against the public theories?
    2. Do transported source theorems remain valid in the target theory?
    3. How closely does the mapping align with the hidden gold transport?

    The output still uses the common ABW score-report shape so downstream
    tooling can aggregate morphism worlds with the rest of the benchmark.
    """

    theory_signatures = build_theory_signatures(world.public_document())
    if not candidate.morphisms:
        errors.append("This world expects at least one candidate morphism.")

    best_report: dict[str, Any] | None = None
    gold_mapping = world.hidden_bridge.mappings[0].mapping if world.hidden_bridge.mappings else {}
    max_term_depth = int(world.metadata.get("max_term_depth", 3))

    for morphism in candidate.morphisms:
        morphism_errors = validate_morphism(morphism, theory_signatures)
        if morphism_errors:
            report = _invalid_report(morphism_errors, candidate)
            if best_report is None or report["metrics"]["total_score"] > best_report["metrics"]["total_score"]:
                best_report = report
            continue

        source_theory = _theory_named(world, morphism.source_theory)
        target_theory = _theory_named(world, morphism.target_theory)
        if source_theory is None or target_theory is None:
            local_errors = [f"Morphism {morphism.name!r} refers to unavailable public theories."]
            report = _invalid_report(local_errors, candidate)
            if best_report is None or report["metrics"]["total_score"] > best_report["metrics"]["total_score"]:
                best_report = report
            continue

        translated_theorems = tuple(_translate_clause(clause, morphism) for clause in source_theory.document.theorems)
        target_signature = theory_signatures[morphism.target_theory]
        target_clauses = target_theory.document.axioms + target_theory.document.lemmas + target_theory.document.theorems
        target_facts = target_theory.document.facts
        target_rewrites = target_theory.document.rewrites

        successful_transports = 0
        goal_reports: list[dict[str, Any]] = []
        counterexample_reports: list[dict[str, Any]] = []
        # Each transported theorem becomes a proof obligation in the target
        # theory. Counterexamples here are the main debugging artifact for a
        # near-miss morphism.
        for clause in translated_theorems:
            counterexamples = find_clause_counterexamples_with_backend(
                signature=target_signature,
                facts=target_facts,
                base_clauses=target_clauses,
                definitions=(),
                clause=clause,
                rewrites=target_rewrites,
                max_term_depth=max_term_depth,
                backend=backend,
            )
            failures = [str(item["message"]) for item in counterexamples]
            success = not counterexamples
            if success:
                successful_transports += 1
            counterexample_reports.extend(counterexamples)
            goal_reports.append(
                {
                    "name": clause.name,
                    "transport_valid": success,
                    "errors": failures,
                    "counterexamples": list(counterexamples),
                }
            )

        validity = 1.0
        transport_rate = successful_transports / len(translated_theorems) if translated_theorems else 0.0
        semantic_score = (
            sum(1 for source, target in morphism.mapping.items() if gold_mapping.get(source) == target) / len(gold_mapping)
            if gold_mapping
            else 1.0
        )
        minimality = minimality_score(candidate)
        weights = effective_weights(world.scoring_config.get("weights"), ANALOGY_WEIGHTS)
        metrics = {
            "validity_score": validity,
            "hidden_goal_solve_rate": transport_rate,
            "proof_cost_reduction": 0.0,
            "compression_score": 0.0,
            "semantic_equivalence_score": semantic_score,
            "novelty_score": 0.0,
            "minimality_score": minimality,
            "candidate_size": candidate_size(candidate),
        }
        metrics["total_score"] = validity * composite_score(metrics, weights)
        report = {
            "valid": True,
            "errors": [],
            "metrics": metrics,
            "goals": goal_reports,
            "counterexamples": counterexample_reports,
        }
        if best_report is None or report["metrics"]["total_score"] > best_report["metrics"]["total_score"]:
            best_report = report

    if best_report is None:
        return _invalid_report(errors, candidate, minimality=0.0)
    if errors:
        best_report["valid"] = False
        best_report["errors"] = errors + best_report["errors"]
        best_report["metrics"]["validity_score"] = 0.0
        best_report["metrics"]["total_score"] = 0.0
    return best_report


def evaluate_candidate(
    world_or_path: ir.World | str | Path,
    candidate_text: str,
    *,
    backend_name: str | None = None,
    backend_command: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Score one candidate bridge against the packaged world contract.

    This is the public evaluator entrypoint used by the CLI, benchmark runner,
    and tests. It normalizes every candidate into the same report shape while
    still honoring family-specific semantics under the hood.

    Broadly, the function:
    - rejects hidden-name leakage
    - parses and typechecks the candidate against the public theory
    - routes morphism worlds into their specialized evaluator
    - evaluates definition or lemma worlds with bounded proof, equivalence, and
      novelty logic

    The returned dictionary is deliberately machine-oriented so benchmark
    runners, reports, and interactive tools can consume it directly.
    """

    world = load_world(world_or_path) if not isinstance(world_or_path, ir.World) else world_or_path
    hidden_names = {
        definition.name for definition in world.hidden_bridge.definitions
    } | {
        mapping.name for mapping in world.hidden_bridge.mappings
    }
    leak_names = reject_hidden_symbol_names(candidate_text, hidden_names)
    errors: list[str] = []
    if leak_names:
        errors.append(f"Candidate uses private hidden symbol names: {', '.join(leak_names)}.")

    public_document = world.public_document()
    theory_signatures = build_theory_signatures(public_document)
    backend = _backend_config(world, backend_name=backend_name, backend_command=backend_command)

    try:
        candidate = _parse_candidate(candidate_text)
        extended_signature = check_document(
            candidate,
            base_signature=world.signature,
            theory_signatures=theory_signatures,
        )
    except Exception as error:  # noqa: BLE001
        errors.append(str(error))
        candidate = ir.Document()
        extended_signature = world.signature

    # The hidden bridge decides which family-specific evaluator should interpret
    # the submission. This keeps the public API simple while preserving the
    # different semantics of morphism tasks.
    if world.hidden_bridge.mappings:
        return _evaluate_morphism_candidate(world, candidate, errors, backend=backend)
    return _evaluate_definition_candidate(
        world,
        candidate,
        extended_signature,
        errors,
        backend=backend,
    )


def _evaluate_definition_candidate(
    world: ir.World,
    candidate: ir.Document,
    extended_signature: ir.Signature,
    errors: list[str],
    *,
    backend: BackendConfig,
) -> dict[str, Any]:
    """Score a definition/lemma bridge candidate against the hidden targets.

    This is the non-analogy scoring path: candidate lemmas are checked for local
    soundness, then hidden-goal utility, proof-cost reduction, compression,
    semantic agreement, novelty, and minimality are combined into the composite
    score. `errors` already carries any leakage or parse/typecheck failures, and
    a non-empty `errors` list gates the candidate to zero total score.
    """

    soundness_failures: list[str] = []
    counterexample_reports: list[dict[str, Any]] = []
    if not errors:
        # Candidate lemmas are checked for local soundness before they are
        # allowed to influence hidden-goal scoring.
        for lemma in candidate.lemmas + candidate.theorems:
            clause_counterexamples = find_clause_counterexamples_with_backend(
                signature=extended_signature,
                facts=world.visible_facts,
                base_clauses=world.public_clauses(),
                definitions=candidate.definitions,
                clause=lemma,
                rewrites=world.rewrites,
                max_term_depth=int(world.metadata.get("max_term_depth", 3)),
                backend=backend,
            )
            counterexample_reports.extend(clause_counterexamples)
            soundness_failures.extend(str(item["message"]) for item in clause_counterexamples)
        errors.extend(soundness_failures)

    public_closure = build_closure_with_backend(
        world.signature,
        facts=world.visible_facts,
        clauses=world.public_clauses(),
        rewrites=world.rewrites,
        max_term_depth=int(world.metadata.get("max_term_depth", 3)),
        backend=backend,
    )
    candidate_closure = build_closure_with_backend(
        extended_signature if not errors else world.signature,
        facts=world.visible_facts,
        clauses=world.public_clauses() + candidate.lemmas + candidate.theorems if not errors else world.public_clauses(),
        definitions=candidate.definitions if not errors else (),
        rewrites=world.rewrites,
        max_term_depth=int(world.metadata.get("max_term_depth", 3)),
        backend=backend,
    )
    diagnostic_candidate_closures: tuple[ProofResult, ...] = ()
    if not errors:
        # Novelty is intentionally measured not only on the exact public world
        # but also on nearby diagnostic variants, so shallow aliases get less
        # flattering scores.
        diagnostic_candidate_closures = tuple(
            build_closure_with_backend(
                extended_signature,
                facts=model.facts,
                clauses=model.clauses + candidate.lemmas + candidate.theorems,
                definitions=candidate.definitions,
                rewrites=model.rewrites,
                max_term_depth=model.max_term_depth,
                backend=backend,
            )
            for model in public_diagnostic_models(world)[1:]
        )

    goal_reports: list[dict[str, Any]] = []
    baseline_costs: list[int] = []
    candidate_costs: list[int] = []
    solved_within_budget = 0
    # Hidden targets are the benchmark's utility test: a bridge should make
    # these downstream obligations cheaper or newly solvable.
    for goal in world.targets_hidden:
        baseline_cost = goal_cost(public_closure.derivations, goal.atoms, world.rewrites)
        candidate_goal_cost = goal_cost(candidate_closure.derivations, goal.atoms, world.rewrites)
        if baseline_cost is not None:
            baseline_costs.append(baseline_cost)
        if candidate_goal_cost is not None:
            candidate_costs.append(candidate_goal_cost)
        within_budget = candidate_goal_cost is not None and (goal.budget is None or candidate_goal_cost <= goal.budget)
        if within_budget:
            solved_within_budget += 1
        goal_reports.append(
            {
                "name": goal.name,
                "baseline_cost": baseline_cost,
                "candidate_cost": candidate_goal_cost,
                "budget": goal.budget,
                "solved_within_budget": within_budget,
            }
        )

    validity = 0.0 if errors else 1.0
    solve_rate = solved_within_budget / len(world.targets_hidden) if world.targets_hidden else 0.0
    reduction = proof_cost_reduction(baseline_costs, candidate_costs) if baseline_costs and candidate_costs else 0.0
    size = candidate_size(candidate)
    compression = compression_score(baseline_costs, candidate_costs, size) if baseline_costs and candidate_costs else 0.0
    semantic_score = semantic_equivalence_score(
        world,
        candidate,
        extended_signature if not errors else world.signature,
        candidate_closure,
        backend=backend,
    )
    novelty = novelty_score(
        candidate.definitions,
        world,
        candidate_closure,
        rewrites=world.rewrites,
        diagnostic_closures=diagnostic_candidate_closures,
    )
    minimality = minimality_score(candidate)

    weights = effective_weights(world.scoring_config.get("weights"), NON_ANALOGY_WEIGHTS)
    metrics = {
        "validity_score": validity,
        "hidden_goal_solve_rate": solve_rate,
        "proof_cost_reduction": reduction,
        "compression_score": compression,
        "semantic_equivalence_score": semantic_score,
        "novelty_score": novelty,
        "minimality_score": minimality,
        "candidate_size": size,
    }
    metrics["total_score"] = validity * composite_score(metrics, weights)

    return {
        "valid": not errors,
        "errors": errors,
        "metrics": metrics,
        "goals": goal_reports,
        "counterexamples": counterexample_reports,
    }
