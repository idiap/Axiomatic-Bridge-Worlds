# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Budgeted interactive refinement sessions for ABW worlds.

This module turns a packaged ABW world into a small interactive environment.
The guiding idea is that theory formation is not only a one-shot submission
problem. A system may benefit from asking a bounded number of public questions
before it commits to a final bridge candidate.

Core interaction model
----------------------
Sessions are intentionally asymmetric:

1. public queries may inspect only the visible world
2. those queries consume a fixed budget
3. the final submission is still scored against the private hidden targets

This creates a lightweight refinement loop without collapsing the benchmark
into full-information tutoring.

Concrete example
----------------
A session can:
- validate a candidate definition or theorem against the public surface
- ask for public examples of a predicate
- request a bounded public countermodel for a visible goal
- probe public equivalence stability across diagnostic models

Then, once the exploration budget is spent or the system is ready, the session
can be closed with a final candidate that is scored normally.

Paper-style framing
-------------------
One concise description of this module is:

    interactive ABW sessions provide bounded public evidence while preserving a
    private final evaluation surface.

Limitations
-----------
- This is a bounded public-query loop, not a full proof-assistant environment.
- Queries are limited to the shipped public surfaces and backend capabilities.
- Structural and logical candidates are supported, but they are still validated
  through local bounded checks rather than open-ended search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Sequence

from abw_core import ir
from abw_core.dsl import parse_document
from abw_core.packager import load_world
from abw_core.prover import (
    BackendConfig,
    build_closure_with_backend,
    find_clause_counterexamples_with_backend,
    find_goal_countermodel_with_backend,
    goal_cost,
    public_diagnostic_models,
)
from abw_core.scorer.equivalence import visible_goal_agreement_score
from abw_core.scorer import evaluate_candidate, load_candidate_text
from abw_core.typecheck import build_theory_signatures, check_document, reject_hidden_symbol_names

DEFAULT_QUERY_BUDGET = 20
SESSION_STATE_FILENAME = "session.json"
TRANSCRIPT_FILENAME = "transcript.jsonl"
FINAL_REPORT_FILENAME = "final_report.json"


@dataclass
class SessionState:
    """Persist the state of one interactive refinement conversation.

    The session state is the minimal durable record needed to resume a session:
    which world is being explored, how much query budget remains, what transcript
    has accumulated, and whether a final submission has already closed the loop.
    """

    session_id: str
    world_path: str
    world_id: str
    family: str
    query_budget: int
    queries_used: int = 0
    countermodels_enabled: bool = True
    transcript: list[dict[str, Any]] = field(default_factory=list)
    final_submission: dict[str, Any] | None = None

    def remaining_queries(self) -> int:
        """Return how much public exploration budget remains.

        This is the single operational constraint that shapes session behavior:
        once it reaches zero, no further exploratory queries should be accepted.
        """

        return max(self.query_budget - self.queries_used, 0)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session into the repo's stable on-disk state format.

        Sessions are persisted as JSON so CLI tools and tests can inspect them
        without importing Python objects directly.
        """

        return {
            "session_id": self.session_id,
            "world": self.world_path,
            "world_id": self.world_id,
            "family": self.family,
            "query_budget": self.query_budget,
            "queries_used": self.queries_used,
            "countermodels_enabled": self.countermodels_enabled,
            "transcript": list(self.transcript),
            "final_submission": self.final_submission,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionState":
        """Rehydrate one stored session payload back into the typed state form.

        This is the inverse of `to_dict` and underpins session resumption.
        """

        return cls(
            session_id=str(payload["session_id"]),
            world_path=str(payload["world"]),
            world_id=str(payload["world_id"]),
            family=str(payload["family"]),
            query_budget=int(payload["query_budget"]),
            queries_used=int(payload.get("queries_used", 0)),
            countermodels_enabled=bool(payload.get("countermodels_enabled", True)),
            transcript=list(payload.get("transcript", [])),
            final_submission=payload.get("final_submission"),
        )


def _session_state_path(session_dir: str | Path) -> Path:
    """Return the canonical location of the persisted session-state JSON."""

    return Path(session_dir) / SESSION_STATE_FILENAME


def _transcript_path(session_dir: str | Path) -> Path:
    """Return the canonical location of the append-only session transcript."""

    return Path(session_dir) / TRANSCRIPT_FILENAME


def _final_report_path(session_dir: str | Path) -> Path:
    """Return the canonical location of the final scored submission artifact."""

    return Path(session_dir) / FINAL_REPORT_FILENAME


def _append_transcript_entry(session_dir: str | Path, entry: dict[str, Any]) -> None:
    """Append one structured event to the session's JSONL transcript.

    The transcript is intentionally append-only so later debugging can inspect
    the exact public interaction history in temporal order.
    """

    with _transcript_path(session_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def save_session(session_dir: str | Path, state: SessionState) -> None:
    """Persist the latest session state into the session directory.

    This writes the authoritative resumable state, not the human-style event
    log. The transcript is maintained separately.
    """

    root = Path(session_dir)
    root.mkdir(parents=True, exist_ok=True)
    _session_state_path(root).write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_session(session_dir: str | Path) -> SessionState:
    """Load one previously created session from its persisted state file.

    Session commands use this helper so every query operates on the latest
    durable state rather than on transient process memory.
    """

    state_path = _session_state_path(session_dir)
    if not state_path.exists():
        raise FileNotFoundError(f"Missing session state file at {state_path}.")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return SessionState.from_dict(payload)


def _interactive_settings(world: ir.World) -> dict[str, Any]:
    """Resolve the interactive-query policy packaged with one world.

    Worlds can optionally carry explicit session settings in scoring config.
    This helper fills in defaults so the session layer always sees a complete
    interactive-policy record.
    """

    raw = world.scoring_config.get("interactive")
    if not isinstance(raw, dict):
        return {
            "enabled": True,
            "query_budget": DEFAULT_QUERY_BUDGET,
            "countermodels": True,
        }
    return {
        "enabled": bool(raw.get("enabled", True)),
        "query_budget": int(raw.get("query_budget", DEFAULT_QUERY_BUDGET)),
        "countermodels": bool(raw.get("countermodels", True)),
    }


def _configured_backend(
    world: ir.World,
    *,
    backend_name: str | None = None,
    backend_command: Sequence[str] = (),
) -> BackendConfig:
    """Resolve which backend should answer public session queries.

    Session queries follow the same precedence pattern as scoring:
    explicit override first, packaged world default second, local backend last.
    """

    if backend_name is not None:
        return BackendConfig(name=backend_name, command=tuple(backend_command))
    configured = world.scoring_config.get("prover_backend")
    if not isinstance(configured, dict):
        return BackendConfig()
    raw_command = configured.get("command", ())
    if isinstance(raw_command, (list, tuple)):
        command = tuple(str(item) for item in raw_command)
    elif raw_command:
        command = (str(raw_command),)
    else:
        command = ()
    return BackendConfig(name=str(configured.get("name", "local")), command=command)


def _hidden_names(world: ir.World) -> set[str]:
    """Collect private bridge names that must stay off the public query surface.

    Sessions are allowed to expose bounded public evidence, not the hidden
    answer. This helper powers the leakage check for query-time candidates.
    """

    return {
        definition.name for definition in world.hidden_bridge.definitions
    } | {
        mapping.name for mapping in world.hidden_bridge.mappings
    }


def _candidate_shape(document: ir.Document) -> dict[str, int]:
    """Summarize the candidate's structural footprint for session responses.

    Public query results often benefit from a compact explanation of what kind
    of object was analyzed: definition-heavy, lemma-heavy, morphism-based, and
    so on.
    """

    return {
        "definitions": len(document.definitions),
        "lemmas": len(document.lemmas),
        "theorems": len(document.theorems),
        "morphisms": len(document.morphisms),
    }


def _analysis_mode(document: ir.Document) -> str:
    """Classify the candidate as logical, structural, or empty for query logic.

    Session endpoints treat logical candidates and structural candidates
    differently, so this small classifier keeps that distinction explicit.
    """

    if document.definitions or document.lemmas or document.theorems:
        return "logical"
    if document.morphisms:
        return "structural_only"
    return "empty"


def _candidate_surface_errors(document: ir.Document, *, logical_only: bool) -> list[str]:
    """Reject candidate shapes that the public query layer should not accept.

    The interactive surface is intentionally narrower than the full ABW DSL:
    users may submit bridge candidates, but not redefine the public world.
    Some queries also only make sense for logical candidates, which is why the
    `logical_only` flag exists.
    """

    if (
        document.sorts
        or document.constants
        or document.functions
        or document.predicates
        or document.rewrites
        or document.axioms
        or document.facts
        or document.goals
        or document.theories
    ):
        return [
            "Interactive candidate queries may only contain bridge items: definitions, lemmas, theorems, or mappings."
        ]
    if (document.definitions or document.lemmas or document.theorems) and document.morphisms:
        return ["Interactive candidate queries must use either logical items or structural items, not both together."]
    if logical_only and document.morphisms:
        return ["This query surface only supports definitions, lemmas, or theorems as candidate extensions."]
    return []


def _theory_named(world: ir.World, name: str) -> ir.Theory | None:
    """Find one named theory block inside the public world package.

    This mirrors the scorer-side helper and supports morphism-oriented public
    validation in the interactive setting.
    """

    for theory in world.theories:
        if theory.name == name:
            return theory
    return None


def _translate_term(term: ir.Term, mapping: dict[str, str]) -> ir.Term:
    """Translate one term through a public morphism candidate's symbol map."""

    if isinstance(term, ir.VarTerm):
        mapped_sort = mapping.get(term.variable.sort, term.variable.sort)
        return ir.VarTerm(ir.Variable(term.variable.name, mapped_sort))
    if isinstance(term, ir.ConstTerm):
        return ir.ConstTerm(mapping.get(term.name, term.name))
    if isinstance(term, ir.FuncTerm):
        return ir.FuncTerm(mapping.get(term.name, term.name), tuple(_translate_term(arg, mapping) for arg in term.args))
    raise TypeError(f"Unsupported term type: {type(term)!r}")


def _translate_atom(atom: ir.Atom, mapping: dict[str, str]) -> ir.Atom:
    """Translate one atom through a public morphism candidate's symbol map."""

    if atom.predicate == "=":
        return ir.Atom("=", tuple(_translate_term(term, mapping) for term in atom.terms))
    return ir.Atom(mapping.get(atom.predicate, atom.predicate), tuple(_translate_term(term, mapping) for term in atom.terms))


def _translate_clause(clause: ir.HornClause, morphism: ir.SignatureMorphism) -> ir.HornClause:
    """Translate one theorem clause into the target side of a public morphism.

    Public morphism validation reuses the same transported-theorem idea as the
    private evaluator, but only over public theory structure.
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


def _parse_session_candidate(
    world: ir.World,
    candidate_text: str,
    *,
    logical_only: bool,
) -> tuple[ir.Document, ir.Signature, list[str]]:
    """Parse and typecheck one session candidate against the public surface.

    This is the session-side gateway for candidate text. It combines hidden-name
    leakage checks, query-surface restrictions, and public typechecking so every
    interactive endpoint starts from the same validated candidate state.
    """

    errors: list[str] = []
    leak_names = reject_hidden_symbol_names(candidate_text, _hidden_names(world))
    if leak_names:
        errors.append(f"Candidate uses private hidden symbol names: {', '.join(leak_names)}.")
    try:
        document = parse_document(candidate_text)
        errors.extend(_candidate_surface_errors(document, logical_only=logical_only))
        if errors:
            return document, world.signature, errors
        extended_signature = check_document(
            document,
            base_signature=world.signature,
            theory_signatures=build_theory_signatures(world.public_document()),
        )
    except Exception as error:  # noqa: BLE001
        errors.append(str(error))
        return ir.Document(), world.signature, errors
    return document, extended_signature, errors


def _goal_named(world: ir.World, name: str, *, visible_only: bool) -> ir.Goal | None:
    """Resolve one visible or known goal name inside the packaged world."""

    goals = world.targets_visible if visible_only else world.targets_visible + world.targets_hidden
    for goal in goals:
        if goal.name == name:
            return goal
    return None


def _probe_atoms(
    signature: ir.Signature,
    *,
    world: ir.World,
    goal_name: str | None,
    atoms_text: str | None,
    visible_only: bool,
) -> tuple[str, tuple[ir.Atom, ...], list[str]]:
    """Resolve a countermodel probe into a concrete atom tuple.

    Countermodel queries can target either a named packaged goal or an ad hoc
    atom string. This helper normalizes both entry modes into one probe target.
    """

    if goal_name:
        goal = _goal_named(world, goal_name, visible_only=visible_only)
        if goal is None:
            scope = "visible" if visible_only else "known"
            return goal_name, (), [f"Unknown {scope} goal {goal_name!r}."]
        return goal.name, goal.atoms, []
    if atoms_text is None:
        return "probe", (), ["No goal query was provided."]
    try:
        document = parse_document(f"goal probe: {atoms_text}")
        check_document(document, base_signature=signature)
    except Exception as error:  # noqa: BLE001
        return "probe", (), [str(error)]
    return "probe", document.goals[0].atoms, []


def _proof_budget(world: ir.World, goal: ir.Goal) -> int | None:
    """Resolve the effective proof budget for one public goal report.

    Goals may carry explicit budgets, but the session layer also supports a
    world-level fallback so reports can still say what "within budget" means.
    """

    if goal.budget is not None:
        return goal.budget
    configured = world.scoring_config.get("proof_budget")
    if isinstance(configured, int):
        return configured
    if isinstance(configured, str) and configured.isdigit():
        return int(configured)
    return None


def _max_term_depth(world: ir.World) -> int:
    """Return the bounded term depth that session queries should respect."""

    return int(world.metadata.get("max_term_depth", 3))


def _atom_sort_key(atom: ir.Atom) -> str:
    """Produce a stable sort key for ordering example atoms in responses.

    Session outputs should be deterministic so that repeated queries and tests
    do not shuffle examples arbitrarily.
    """

    return json.dumps(atom.to_dict(), sort_keys=True)


def _public_validate_morphisms(
    world: ir.World,
    document: ir.Document,
    *,
    backend: BackendConfig,
) -> dict[str, Any]:
    """Validate candidate morphisms using only public theory structure.

    This query endpoint mirrors morphism scoring conceptually, but it never
    touches hidden targets. Instead, it asks whether transported public theorems
    remain valid in the target theory and returns the resulting evidence.
    """

    theory_signatures = build_theory_signatures(world.public_document())
    errors: list[str] = []
    transport_reports: list[dict[str, Any]] = []
    counterexample_reports: list[dict[str, Any]] = []

    if not document.morphisms:
        errors.append("This query surface expects at least one morphism.")

    from abw_core.typecheck import validate_morphism

    for morphism in document.morphisms:
        source_theory = _theory_named(world, morphism.source_theory)
        target_theory = _theory_named(world, morphism.target_theory)
        if source_theory is None or target_theory is None:
            transport_reports.append(
                {
                    "name": morphism.name,
                    "valid": False,
                    "errors": ["Morphism refers to unavailable public theories."],
                }
            )
            continue

        morphism_errors = validate_morphism(morphism, theory_signatures)
        if morphism_errors:
            transport_reports.append({"name": morphism.name, "valid": False, "errors": morphism_errors})
            continue

        translated_theorems = tuple(_translate_clause(clause, morphism) for clause in source_theory.document.theorems)
        target_signature = theory_signatures[morphism.target_theory]
        target_clauses = target_theory.document.axioms + target_theory.document.lemmas + target_theory.document.theorems
        target_facts = target_theory.document.facts
        clause_reports = []
        # Each transported public theorem becomes a visible proof obligation.
        for clause in translated_theorems:
            counterexamples = find_clause_counterexamples_with_backend(
                signature=target_signature,
                facts=target_facts,
                base_clauses=target_clauses,
                definitions=(),
                clause=clause,
                rewrites=target_theory.document.rewrites,
                max_term_depth=_max_term_depth(world),
                backend=backend,
            )
            clause_reports.append(
                {
                    "name": clause.name,
                    "valid": not counterexamples,
                    "errors": [str(item["message"]) for item in counterexamples],
                    "counterexamples": list(counterexamples),
                }
            )
            counterexample_reports.extend(counterexamples)
        transport_reports.append(
            {
                "name": morphism.name,
                "valid": all(report["valid"] for report in clause_reports),
                "source_theory": morphism.source_theory,
                "target_theory": morphism.target_theory,
                "transported_theorems": clause_reports,
            }
        )

    return {
        "valid": not errors and all(report["valid"] for report in transport_reports),
        "errors": errors,
        "analysis_mode": _analysis_mode(document),
        "candidate_shape": _candidate_shape(document),
        "visible_goals": [],
        "counterexamples": counterexample_reports,
        "transport_reports": transport_reports,
    }


def public_validate_candidate(
    world: ir.World,
    candidate_text: str,
    *,
    backend: BackendConfig | None = None,
) -> dict[str, Any]:
    """Validate a candidate against the public world only.

    This is the main public "sanity check" query. It answers:
    - does the candidate parse and typecheck publicly?
    - are its clauses locally sound on the public surface?
    - what happens to the visible goals if we add it?

    Hidden targets are intentionally excluded.
    """

    document, extended_signature, errors = _parse_session_candidate(world, candidate_text, logical_only=False)
    counterexample_reports: list[dict[str, Any]] = []
    backend = backend or BackendConfig()
    if not errors and document.morphisms:
        return _public_validate_morphisms(world, document, backend=backend)
    if not errors:
        # Logical candidates are checked for public clause soundness before they
        # are allowed to influence visible-goal reports.
        for clause in document.lemmas + document.theorems:
            counterexamples = find_clause_counterexamples_with_backend(
                signature=extended_signature,
                facts=world.visible_facts,
                base_clauses=world.public_clauses(),
                definitions=document.definitions,
                clause=clause,
                rewrites=world.rewrites,
                max_term_depth=_max_term_depth(world),
                backend=backend,
            )
            counterexample_reports.extend(counterexamples)
        errors.extend(str(item["message"]) for item in counterexample_reports)

    baseline_closure = build_closure_with_backend(
        world.signature,
        facts=world.visible_facts,
        clauses=world.public_clauses(),
        rewrites=world.rewrites,
        max_term_depth=_max_term_depth(world),
        backend=backend,
    )
    candidate_closure = build_closure_with_backend(
        extended_signature if not errors else world.signature,
        facts=world.visible_facts,
        clauses=world.public_clauses() + document.lemmas + document.theorems if not errors else world.public_clauses(),
        definitions=document.definitions if not errors else (),
        rewrites=world.rewrites,
        max_term_depth=_max_term_depth(world),
        backend=backend,
    )

    visible_goals = []
    for goal in world.targets_visible:
        baseline_cost = goal_cost(baseline_closure.derivations, goal.atoms, world.rewrites)
        candidate_cost = goal_cost(candidate_closure.derivations, goal.atoms, world.rewrites)
        budget = _proof_budget(world, goal)
        visible_goals.append(
            {
                "name": goal.name,
                "baseline_cost": baseline_cost,
                "candidate_cost": candidate_cost,
                "budget": budget,
                "proved": candidate_cost is not None,
                "solved_within_budget": candidate_cost is not None and (budget is None or candidate_cost <= budget),
            }
        )

    return {
        "valid": not errors,
        "errors": errors,
        "analysis_mode": _analysis_mode(document),
        "candidate_shape": _candidate_shape(document),
        "visible_goals": visible_goals,
        "counterexamples": counterexample_reports,
    }


def public_equivalence_query(
    world: ir.World,
    candidate_text: str,
    *,
    backend: BackendConfig | None = None,
) -> dict[str, Any]:
    """Probe whether a logical candidate behaves stably across public variants.

    The point is not full theorem equivalence. The point is a bounded, public
    answer to a softer question: does this candidate keep roughly the same
    visible behavior across the nearby diagnostic models shipped with the world?
    """

    document, signature, errors = _parse_session_candidate(world, candidate_text, logical_only=True)
    backend = backend or BackendConfig()
    if errors:
        return {
            "valid": False,
            "errors": errors,
            "analysis_mode": _analysis_mode(document),
            "candidate_shape": _candidate_shape(document),
            "stability_score": 0.0,
            "model_reports": [],
        }

    suite = public_diagnostic_models(world)
    public_closures = tuple(
        build_closure_with_backend(
            world.signature,
            facts=model.facts,
            clauses=model.clauses,
            rewrites=model.rewrites,
            max_term_depth=model.max_term_depth,
            backend=backend,
        )
        for model in suite
    )
    candidate_closures = tuple(
        build_closure_with_backend(
            signature,
            facts=model.facts,
            clauses=model.clauses + document.lemmas + document.theorems,
            definitions=document.definitions,
            rewrites=model.rewrites,
            max_term_depth=model.max_term_depth,
            backend=backend,
        )
        for model in suite
    )

    baseline_candidate = candidate_closures[0]
    model_reports: list[dict[str, Any]] = []
    stability_scores: list[float] = []
    for model, public_closure, candidate_closure in zip(suite, public_closures, candidate_closures):
        goal_alignment = visible_goal_agreement_score(
            world.targets_visible,
            baseline_candidate,
            candidate_closure,
            world.rewrites,
        )
        public_alignment = visible_goal_agreement_score(
            world.targets_visible,
            public_closure,
            candidate_closure,
            world.rewrites,
        )
        if goal_alignment is None:
            goal_alignment = 1.0
        if public_alignment is None:
            public_alignment = 1.0
        stability = 0.5 * goal_alignment + 0.5 * public_alignment
        stability_scores.append(stability)
        visible_goals = []
        for goal in world.targets_visible:
            public_cost = goal_cost(public_closure.derivations, goal.atoms, world.rewrites)
            candidate_cost = goal_cost(candidate_closure.derivations, goal.atoms, world.rewrites)
            visible_goals.append(
                {
                    "name": goal.name,
                    "public_cost": public_cost,
                    "candidate_cost": candidate_cost,
                    "changed": public_cost != candidate_cost,
                }
            )
        model_reports.append(
            {
                "model": model.name,
                "stability_score": stability,
                "goal_alignment": goal_alignment,
                "public_alignment": public_alignment,
                "visible_goals": visible_goals,
            }
        )

    return {
        "valid": True,
        "errors": [],
        "analysis_mode": _analysis_mode(document),
        "candidate_shape": _candidate_shape(document),
        "stability_score": sum(stability_scores) / len(stability_scores) if stability_scores else 1.0,
        "model_reports": model_reports,
    }


def public_countermodel_query(
    world: ir.World,
    *,
    goal_name: str | None = None,
    atoms_text: str | None = None,
    candidate_text: str | None = None,
    backend: BackendConfig | None = None,
) -> dict[str, Any]:
    """Return a bounded public countermodel for a visible goal or atom probe.

    This is the session-side debugging query for "why is this still false on the
    public surface?" It may be asked about a packaged visible goal or an ad hoc
    atom tuple, optionally in the presence of a candidate extension.
    """

    document = ir.Document()
    signature = world.signature
    errors: list[str] = []
    if candidate_text is not None:
        document, signature, errors = _parse_session_candidate(world, candidate_text, logical_only=True)

    label, goal_atoms, goal_errors = _probe_atoms(
        signature,
        world=world,
        goal_name=goal_name,
        atoms_text=atoms_text,
        visible_only=True,
    )
    errors.extend(goal_errors)

    backend = backend or BackendConfig()
    countermodel = None
    if not errors:
        countermodel = find_goal_countermodel_with_backend(
            signature=signature,
            facts=world.visible_facts,
            clauses=world.public_clauses() + document.lemmas + document.theorems,
            goal_atoms=goal_atoms,
            definitions=document.definitions,
            rewrites=world.rewrites,
            max_term_depth=_max_term_depth(world),
            label=label,
            backend=backend,
        )

    return {
        "valid": not errors,
        "errors": errors,
        "goal": label,
        "goal_atoms": [atom.to_dict() for atom in goal_atoms],
        "candidate_shape": _candidate_shape(document),
        "proved": not errors and countermodel is None,
        "countermodel": countermodel,
    }


def public_examples(
    world: ir.World,
    *,
    predicate: str,
    limit: int = 5,
    candidate_text: str | None = None,
    backend: BackendConfig | None = None,
) -> dict[str, Any]:
    """Return bounded public examples witnessing one predicate's extension.

    Example queries help a user see what their candidate or the public theory is
    actually deriving. The results are drawn from the current bounded closure
    and include lightweight derivation metadata.
    """

    document = ir.Document()
    signature = world.signature
    errors: list[str] = []
    if limit <= 0:
        errors.append("Example queries require a positive --limit.")
    if candidate_text is not None:
        document, signature, candidate_errors = _parse_session_candidate(world, candidate_text, logical_only=True)
        errors.extend(candidate_errors)
    predicate_names = signature.predicate_map()
    if predicate not in predicate_names:
        errors.append(f"Unknown predicate {predicate!r}.")

    backend = backend or BackendConfig()
    examples: list[dict[str, Any]] = []
    truncated = False
    if not errors:
        closure = build_closure_with_backend(
            signature,
            facts=world.visible_facts,
            clauses=world.public_clauses() + document.lemmas + document.theorems,
            definitions=document.definitions,
            rewrites=world.rewrites,
            max_term_depth=_max_term_depth(world),
            backend=backend,
        )
        matching_atoms = sorted(
            (atom for atom in closure.derivations if atom.predicate == predicate),
            key=_atom_sort_key,
        )
        truncated = len(matching_atoms) > limit
        for atom in matching_atoms[:limit]:
            derivation = closure.derivations[atom]
            examples.append(
                {
                    "atom": atom.to_dict(),
                    "total_cost": derivation.total_cost,
                    "rule_kind": derivation.rule_kind,
                    "rule_name": derivation.rule_name,
                }
            )

    return {
        "valid": not errors,
        "errors": errors,
        "predicate": predicate,
        "candidate_shape": _candidate_shape(document),
        "examples": examples,
        "truncated": truncated,
    }


def exploration_efficiency_score(queries_used: int, query_budget: int) -> float:
    """Reward sessions that reached a final answer with less public probing.

    This is not meant as a deep cognitive metric. It is a simple normalized
    signal saying that a system which solves the task with fewer queries used
    its public exploration budget more sparingly.
    """

    if query_budget <= 0:
        return 1.0
    remaining = max(query_budget - queries_used, 0)
    return remaining / query_budget


def interactive_world_settings(world_or_path: ir.World | str | Path) -> dict[str, Any]:
    """Expose the packaged interactive policy for a world or world path.

    This gives callers a cheap way to inspect whether sessions are enabled and
    what their default query settings are before actually starting one.
    """

    world = load_world(world_or_path) if not isinstance(world_or_path, ir.World) else world_or_path
    return _interactive_settings(world)


def start_session(
    world_path: str | Path,
    output_dir: str | Path,
    *,
    session_id: str | None = None,
    query_budget: int | None = None,
) -> dict[str, Any]:
    """Create a new interactive session rooted in one packaged public world.

    Starting a session does not score anything yet. It initializes the bounded
    public exploration context, writes the state files, and records a first
    transcript event so later debugging can reconstruct the session lifecycle.
    """

    world = load_world(world_path)
    settings = _interactive_settings(world)
    if not settings["enabled"]:
        raise ValueError(f"Interactive sessions are disabled for world {world.world_id!r}.")
    budget = settings["query_budget"] if query_budget is None else int(query_budget)
    if budget < 0:
        raise ValueError("Interactive query budget must be non-negative.")

    root = Path(output_dir)
    state_path = _session_state_path(root)
    if state_path.exists():
        raise FileExistsError(f"Session already exists at {state_path}.")

    state = SessionState(
        session_id=session_id or f"{world.world_id}-session",
        world_path=str(Path(world_path).resolve()),
        world_id=world.world_id,
        family=world.family,
        query_budget=budget,
        countermodels_enabled=bool(settings["countermodels"]),
    )
    event = {
        "type": "start",
        "session_id": state.session_id,
        "world_id": state.world_id,
        "family": state.family,
        "query_budget": state.query_budget,
        "countermodels_enabled": state.countermodels_enabled,
    }
    state.transcript.append(event)
    save_session(root, state)
    _append_transcript_entry(root, event)
    return {
        "session_id": state.session_id,
        "world": state.world_path,
        "world_id": state.world_id,
        "family": state.family,
        "query_budget": state.query_budget,
        "queries_used": state.queries_used,
        "remaining_queries": state.remaining_queries(),
        "countermodels_enabled": state.countermodels_enabled,
        "output": str(root),
        "state_file": str(state_path),
        "transcript_file": str(_transcript_path(root)),
    }


def run_session_query(
    session_dir: str | Path,
    *,
    kind: str,
    candidate_path: str | Path | None = None,
    goal_name: str | None = None,
    atoms_text: str | None = None,
    predicate: str | None = None,
    limit: int = 5,
    backend_name: str | None = None,
    backend_command: Sequence[str] = (),
) -> dict[str, Any]:
    """Execute one public session query and record it durably.

    This is the session loop's operational center. It enforces the remaining
    query budget, dispatches to the appropriate public query surface, updates
    the transcript, and persists the resulting state.
    """

    state = load_session(session_dir)
    world = load_world(state.world_path)
    request = {
        "kind": kind,
        "candidate": str(candidate_path) if candidate_path is not None else None,
        "goal": goal_name,
        "atoms": atoms_text,
        "predicate": predicate,
        "limit": limit,
        "backend_name": backend_name,
        "backend_command": list(backend_command),
    }

    if state.final_submission is not None:
        payload = {
            "accepted": False,
            "error": "This session is already closed by a final submission.",
            "query_budget": state.query_budget,
            "queries_used": state.queries_used,
            "remaining_queries": state.remaining_queries(),
        }
        event = {"type": "query", "consumed": False, "request": request, "response": payload}
        state.transcript.append(event)
        save_session(session_dir, state)
        _append_transcript_entry(session_dir, event)
        return payload

    if state.remaining_queries() <= 0:
        payload = {
            "accepted": False,
            "error": "Query budget exhausted.",
            "query_budget": state.query_budget,
            "queries_used": state.queries_used,
            "remaining_queries": state.remaining_queries(),
        }
        event = {"type": "query", "consumed": False, "request": request, "response": payload}
        state.transcript.append(event)
        save_session(session_dir, state)
        _append_transcript_entry(session_dir, event)
        return payload

    backend = _configured_backend(world, backend_name=backend_name, backend_command=backend_command)
    candidate_text = load_candidate_text(candidate_path) if candidate_path is not None else None

    if kind == "validate":
        response = public_validate_candidate(world, candidate_text or "", backend=backend)
    elif kind == "equivalence":
        response = public_equivalence_query(world, candidate_text or "", backend=backend)
    elif kind == "countermodel":
        if not state.countermodels_enabled:
            response = {
                "valid": False,
                "errors": ["Countermodel queries are disabled for this world."],
                "goal": goal_name or "probe",
                "goal_atoms": [],
                "candidate_shape": _candidate_shape(ir.Document()),
                "proved": False,
                "countermodel": None,
            }
        else:
            response = public_countermodel_query(
                world,
                goal_name=goal_name,
                atoms_text=atoms_text,
                candidate_text=candidate_text,
                backend=backend,
            )
    elif kind == "examples":
        response = public_examples(
            world,
            predicate=predicate or "",
            limit=limit,
            candidate_text=candidate_text,
            backend=backend,
        )
    else:
        raise ValueError(f"Unsupported interactive query kind {kind!r}.")

    # Only successful dispatches consume budget; rejected queries above return
    # early without changing the session count.
    state.queries_used += 1
    payload = {
        "accepted": True,
        "query_budget": state.query_budget,
        "queries_used": state.queries_used,
        "remaining_queries": state.remaining_queries(),
        "response": response,
    }
    event = {"type": "query", "consumed": True, "request": request, "response": payload}
    state.transcript.append(event)
    save_session(session_dir, state)
    _append_transcript_entry(session_dir, event)
    return payload


def finish_session(
    session_dir: str | Path,
    *,
    candidate_path: str | Path,
    backend_name: str | None = None,
    backend_command: Sequence[str] = (),
) -> dict[str, Any]:
    """Score the final candidate for a session and close further exploration.

    Finishing a session converts the exploratory interaction into a standard
    benchmark submission. After this point, no more public queries are accepted,
    and the final report is written both into session state and to a standalone
    JSON artifact for inspection.
    """

    state = load_session(session_dir)
    if state.final_submission is not None:
        return {
            "session_id": state.session_id,
            "error": "This session already has a final submission.",
            "query_budget": state.query_budget,
            "queries_used": state.queries_used,
            "remaining_queries": state.remaining_queries(),
            "exploration_efficiency_score": exploration_efficiency_score(state.queries_used, state.query_budget),
            "final_report": state.final_submission.get("final_report"),
        }

    report = evaluate_candidate(
        state.world_path,
        load_candidate_text(candidate_path),
        backend_name=backend_name,
        backend_command=tuple(backend_command),
    )
    final_payload = {
        "session_id": state.session_id,
        "candidate": str(candidate_path),
        "query_budget": state.query_budget,
        "queries_used": state.queries_used,
        "remaining_queries": state.remaining_queries(),
        "exploration_efficiency_score": exploration_efficiency_score(state.queries_used, state.query_budget),
        "final_report": report,
    }
    state.final_submission = final_payload
    event = {"type": "finish", "candidate": str(candidate_path), "response": final_payload}
    state.transcript.append(event)
    save_session(session_dir, state)
    _append_transcript_entry(session_dir, event)
    _final_report_path(session_dir).write_text(json.dumps(final_payload, indent=2) + "\n", encoding="utf-8")
    return final_payload
