# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Backend adapters for ABW proof operations.

The default ABW runtime uses the in-process bounded Horn prover. This module
adds a thin adapter layer around that local engine so the rest of the system
can speak in terms of proof operations rather than in terms of one hard-coded
backend implementation.

Why this file exists
--------------------
Different ABW workflows want different evidence sources:
- the local closure builder for proof-cost accounting
- solver-backed finite-model checks for stronger diagnostics
- subprocess drivers for delegated or isolated proof work

This module gives those modes one shared interface.

Concrete example
----------------
- The evaluator asks for `find_clause_counterexamples_with_backend(...)`
  without caring whether the answer comes from the local prover, Z3, cvc5, or
  a subprocess.
- The session layer can request a bounded countermodel through the same
  backend-selection surface.

Paper-style framing
-------------------
The design principle is:

    keep the benchmark's reasoning API stable while allowing the evidence
    source underneath that API to vary in controlled, explicit ways.

Limitations
-----------
- Solver backends strengthen diagnostics, but proof-cost metrics still rely on
  the local derivation graph.
- The subprocess protocol is JSON-over-stdin/stdout, intentionally simple and
  local rather than a general RPC framework.
- Only the operations listed in this file are supported across backends.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
import sys
from typing import Any

from abw_core import ir
from abw_core.prover.countermodels import find_goal_countermodel
from abw_core.prover.horn import ProofResult, build_closure, find_clause_counterexamples
from abw_core.serde import (
    atom_from_dict,
    atom_to_dict,
    clause_from_dict,
    clause_to_dict,
    definition_from_dict,
    definition_to_dict,
    fact_from_dict,
    fact_to_dict,
    proof_result_from_dict,
    proof_result_to_dict,
    rewrite_from_dict,
    rewrite_to_dict,
    signature_from_dict,
    signature_to_dict,
)


@dataclass(frozen=True)
class BackendConfig:
    """Select one proof backend and its optional invocation command.

    Most ABW code only needs to know "local, solver-backed, or subprocess."
    This small config object carries exactly that decision without coupling the
    rest of the runtime to any one backend-specific detail structure.
    """

    name: str = "local"
    command: tuple[str, ...] = ()


def build_closure_with_backend(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...] = (),
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
    backend: BackendConfig | None = None,
) -> ProofResult:
    """Build the bounded derivation closure through the chosen backend surface.

    The closure itself remains a local-proof concept because ABW uses it for
    derivation traces and proof-cost accounting. Even when the selected backend
    is `z3` or `cvc5`, this function still returns the local closure because the
    external solver path is used to strengthen diagnostics, not replace the
    benchmark's native proof graph.
    """

    backend = backend or BackendConfig()
    if backend.name == "local":
        return build_closure(
            signature,
            facts=facts,
            clauses=clauses,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
    if backend.name in {"z3", "cvc5"}:
        if backend.name == "z3":
            from abw_core.prover.z3_finite_models import require_z3

            require_z3()
        else:
            from abw_core.prover.cvc5_finite_models import require_cvc5

            require_cvc5()
        # External solver backends strengthen finite-model diagnostics, but the
        # score's proof-cost metrics still need the local derivation graph.
        return build_closure(
            signature,
            facts=facts,
            clauses=clauses,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
    if backend.name != "subprocess":
        raise ValueError(f"Unsupported prover backend {backend.name!r}.")
    if not backend.command:
        raise ValueError("Subprocess prover backend requires a command.")

    payload = {
        "operation": "build_closure",
        "signature": signature_to_dict(signature),
        "facts": [fact_to_dict(fact) for fact in facts],
        "clauses": [clause_to_dict(clause) for clause in clauses],
        "definitions": [definition_to_dict(definition) for definition in definitions],
        "rewrites": [rewrite_to_dict(rule) for rule in rewrites],
        "max_term_depth": max_term_depth,
    }
    result = subprocess.run(
        list(backend.command),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return proof_result_from_dict(json.loads(result.stdout))


def find_clause_counterexamples_with_backend(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    base_clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...],
    clause: ir.HornClause,
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
    backend: BackendConfig | None = None,
) -> tuple[dict[str, Any], ...]:
    """Find grounded counterexamples for one clause using the selected backend.

    This is one of the benchmark's main evidence channels for invalid bridges.
    The returned payloads are normalized into plain dictionaries so callers such
    as the scorer, session layer, and subprocess drivers can share them without
    depending on backend-specific object types.
    """

    backend = backend or BackendConfig()
    if backend.name == "local":
        return tuple(
            item.to_dict()
            for item in find_clause_counterexamples(
                signature=signature,
                facts=facts,
                base_clauses=base_clauses,
                definitions=definitions,
                clause=clause,
                rewrites=rewrites,
                max_term_depth=max_term_depth,
            )
        )
    if backend.name == "z3":
        from abw_core.prover.z3_finite_models import find_clause_counterexamples_via_z3

        return find_clause_counterexamples_via_z3(
            signature=signature,
            facts=facts,
            base_clauses=base_clauses,
            definitions=definitions,
            clause=clause,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
    if backend.name == "cvc5":
        from abw_core.prover.cvc5_finite_models import find_clause_counterexamples_via_cvc5

        return find_clause_counterexamples_via_cvc5(
            signature=signature,
            facts=facts,
            base_clauses=base_clauses,
            definitions=definitions,
            clause=clause,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
    if backend.name != "subprocess":
        raise ValueError(f"Unsupported prover backend {backend.name!r}.")
    if not backend.command:
        raise ValueError("Subprocess prover backend requires a command.")

    payload = {
        "operation": "find_clause_counterexamples",
        "signature": signature_to_dict(signature),
        "facts": [fact_to_dict(fact) for fact in facts],
        "base_clauses": [clause_to_dict(item) for item in base_clauses],
        "definitions": [definition_to_dict(definition) for definition in definitions],
        "clause": clause_to_dict(clause),
        "rewrites": [rewrite_to_dict(rule) for rule in rewrites],
        "max_term_depth": max_term_depth,
    }
    result = subprocess.run(
        list(backend.command),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    response = json.loads(result.stdout)
    return tuple(dict(item) for item in response["counterexamples"])


def find_goal_countermodel_with_backend(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    clauses: tuple[ir.HornClause, ...],
    goal_atoms: tuple[ir.Atom, ...],
    definitions: tuple[ir.Definition, ...] = (),
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
    label: str = "",
    backend: BackendConfig | None = None,
) -> dict[str, Any] | None:
    """Find a bounded countermodel showing why a goal is still false.

    Clause counterexamples explain invalid rules. Goal countermodels explain
    unsolved targets. This function exposes the latter through the same backend
    selection surface so interactive tooling and scoring can ask the question
    consistently.
    """

    backend = backend or BackendConfig()
    if backend.name == "local":
        model = find_goal_countermodel(
            signature=signature,
            facts=facts,
            clauses=clauses,
            goal_atoms=goal_atoms,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
            label=label,
        )
        return model.to_dict() if model is not None else None
    if backend.name == "z3":
        from abw_core.prover.z3_finite_models import find_goal_countermodel_via_z3

        return find_goal_countermodel_via_z3(
            signature=signature,
            facts=facts,
            clauses=clauses,
            goal_atoms=goal_atoms,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
            label=label,
        )
    if backend.name == "cvc5":
        from abw_core.prover.cvc5_finite_models import find_goal_countermodel_via_cvc5

        return find_goal_countermodel_via_cvc5(
            signature=signature,
            facts=facts,
            clauses=clauses,
            goal_atoms=goal_atoms,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
            label=label,
        )
    if backend.name != "subprocess":
        raise ValueError(f"Unsupported prover backend {backend.name!r}.")
    if not backend.command:
        raise ValueError("Subprocess prover backend requires a command.")

    payload = {
        "operation": "find_goal_countermodel",
        "signature": signature_to_dict(signature),
        "facts": [fact_to_dict(fact) for fact in facts],
        "clauses": [clause_to_dict(item) for item in clauses],
        "goal_atoms": [atom_to_dict(atom) for atom in goal_atoms],
        "definitions": [definition_to_dict(definition) for definition in definitions],
        "rewrites": [rewrite_to_dict(rule) for rule in rewrites],
        "max_term_depth": max_term_depth,
        "label": label,
    }
    result = subprocess.run(
        list(backend.command),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    response = json.loads(result.stdout)
    countermodel = response.get("countermodel")
    return dict(countermodel) if isinstance(countermodel, dict) else None


def validate_clause_soundness_with_backend(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    base_clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...],
    clause: ir.HornClause,
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
    backend: BackendConfig | None = None,
) -> list[str]:
    """Return only the readable error messages for a clause-soundness check.

    Some callers only care whether a clause is locally invalid and how to say
    that to a human, not about the full structured counterexample payload.
    """

    return [
        str(item["message"])
        for item in find_clause_counterexamples_with_backend(
            signature=signature,
            facts=facts,
            base_clauses=base_clauses,
            definitions=definitions,
            clause=clause,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
            backend=backend,
        )
    ]


def _counterexample_payload(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    definitions: tuple[ir.Definition, ...],
    rewrites: tuple[ir.RewriteRule, ...],
    max_term_depth: int,
    *,
    base_clauses: tuple[ir.HornClause, ...],
    clause: ir.HornClause,
) -> str:
    """Serialize local clause-counterexample results for backend protocol use.

    The subprocess protocol wants JSON strings, while the in-process logic works
    naturally with typed objects. This helper is the narrow bridge between those
    two representations.
    """

    counterexamples = find_clause_counterexamples(
        signature=signature,
        facts=facts,
        base_clauses=base_clauses,
        definitions=definitions,
        clause=clause,
        rewrites=rewrites,
        max_term_depth=max_term_depth,
    )
    return json.dumps({"counterexamples": [item.to_dict() for item in counterexamples]})


def backend_from_payload(payload: dict[str, object]) -> BackendConfig:
    """Decode a JSON-compatible backend payload into the runtime config shape.

    Packaged worlds store backend defaults in plain structured data. This helper
    turns that stored configuration back into the typed `BackendConfig` used by
    the runtime.
    """

    name = str(payload.get("name", "local"))
    raw_command = payload.get("command", ())
    if isinstance(raw_command, (list, tuple)):
        command = tuple(str(item) for item in raw_command)
    elif raw_command:
        command = (str(raw_command),)
    else:
        command = ()
    return BackendConfig(name=name, command=command)


def _decode_common(payload: dict[str, object]) -> tuple[
    ir.Signature,
    tuple[ir.Fact, ...],
    tuple[ir.Definition, ...],
    tuple[ir.RewriteRule, ...],
    int,
]:
    """Decode the backend-protocol fields shared by every operation type.

    The protocol repeats the same world ingredients across closure building,
    counterexample search, and countermodel search. Centralizing that decoding
    keeps the per-operation branches small and consistent.
    """

    signature = signature_from_dict(dict(payload["signature"]))
    facts = tuple(fact_from_dict(dict(item)) for item in payload.get("facts", []))
    definitions = tuple(definition_from_dict(dict(item)) for item in payload.get("definitions", []))
    rewrites = tuple(rewrite_from_dict(dict(item)) for item in payload.get("rewrites", []))
    max_term_depth = int(payload.get("max_term_depth", 3))
    return signature, facts, definitions, rewrites, max_term_depth


def run_subprocess_backend_operation(raw_payload: str) -> str:
    """Execute one backend-protocol request against the local prover surface.

    This function is the implementation behind the bundled subprocess driver.
    It receives JSON over stdin or stdout, dispatches the requested operation,
    and returns JSON again so another process can outsource bounded proof work
    without importing the whole evaluator directly.
    """

    payload = json.loads(raw_payload)
    operation = payload["operation"]
    signature, facts, definitions, rewrites, max_term_depth = _decode_common(payload)

    if operation == "build_closure":
        clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("clauses", []))
        result = build_closure(
            signature,
            facts=facts,
            clauses=clauses,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
        return json.dumps(proof_result_to_dict(result))

    if operation == "find_goal_countermodel":
        clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("clauses", []))
        goal_atoms = tuple(atom_from_dict(dict(item)) for item in payload.get("goal_atoms", []))
        result = find_goal_countermodel(
            signature=signature,
            facts=facts,
            clauses=clauses,
            goal_atoms=goal_atoms,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
            label=str(payload.get("label", "")),
        )
        return json.dumps({"countermodel": result.to_dict() if result is not None else None})

    if operation == "find_clause_counterexamples":
        base_clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("base_clauses", []))
        clause = clause_from_dict(dict(payload["clause"]))
        return _counterexample_payload(
            signature,
            facts,
            definitions,
            rewrites,
            max_term_depth,
            base_clauses=base_clauses,
            clause=clause,
        )

    if operation == "validate_clause_soundness":
        base_clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("base_clauses", []))
        clause = clause_from_dict(dict(payload["clause"]))
        response = json.loads(
            _counterexample_payload(
                signature,
                facts,
                definitions,
                rewrites,
                max_term_depth,
                base_clauses=base_clauses,
                clause=clause,
            )
        )
        return json.dumps({"failures": [str(item["message"]) for item in response["counterexamples"]]})

    raise ValueError(f"Unsupported subprocess prover operation {operation!r}.")


def run_z3_backend_operation(raw_payload: str) -> str:
    """Execute one backend-protocol request using the optional Z3 search path.

    Z3 is only used for the operations where finite-model search adds value,
    while closure building still routes through the local prover for consistency
    with proof-cost accounting.
    """

    from abw_core.prover.z3_finite_models import find_clause_counterexamples_via_z3, find_goal_countermodel_via_z3

    payload = json.loads(raw_payload)
    operation = payload["operation"]
    signature, facts, definitions, rewrites, max_term_depth = _decode_common(payload)

    if operation == "build_closure":
        clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("clauses", []))
        result = build_closure(
            signature,
            facts=facts,
            clauses=clauses,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
        return json.dumps(proof_result_to_dict(result))

    if operation == "find_goal_countermodel":
        clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("clauses", []))
        goal_atoms = tuple(atom_from_dict(dict(item)) for item in payload.get("goal_atoms", []))
        result = find_goal_countermodel_via_z3(
            signature=signature,
            facts=facts,
            clauses=clauses,
            goal_atoms=goal_atoms,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
            label=str(payload.get("label", "")),
        )
        return json.dumps({"countermodel": result})

    if operation == "find_clause_counterexamples":
        base_clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("base_clauses", []))
        clause = clause_from_dict(dict(payload["clause"]))
        result = find_clause_counterexamples_via_z3(
            signature=signature,
            facts=facts,
            base_clauses=base_clauses,
            definitions=definitions,
            clause=clause,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
        return json.dumps({"counterexamples": list(result)})

    if operation == "validate_clause_soundness":
        base_clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("base_clauses", []))
        clause = clause_from_dict(dict(payload["clause"]))
        result = find_clause_counterexamples_via_z3(
            signature=signature,
            facts=facts,
            base_clauses=base_clauses,
            definitions=definitions,
            clause=clause,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
        return json.dumps({"failures": [str(item["message"]) for item in result]})

    raise ValueError(f"Unsupported Z3 prover operation {operation!r}.")


def run_cvc5_backend_operation(raw_payload: str) -> str:
    """Execute one backend-protocol request using the optional cvc5 search path.

    This mirrors the Z3 operation surface so the rest of ABW can swap between
    solver backends without changing call sites or payload shapes.
    """

    from abw_core.prover.cvc5_finite_models import find_clause_counterexamples_via_cvc5, find_goal_countermodel_via_cvc5

    payload = json.loads(raw_payload)
    operation = payload["operation"]
    signature, facts, definitions, rewrites, max_term_depth = _decode_common(payload)

    if operation == "build_closure":
        clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("clauses", []))
        result = build_closure(
            signature,
            facts=facts,
            clauses=clauses,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
        return json.dumps(proof_result_to_dict(result))

    if operation == "find_goal_countermodel":
        clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("clauses", []))
        goal_atoms = tuple(atom_from_dict(dict(item)) for item in payload.get("goal_atoms", []))
        result = find_goal_countermodel_via_cvc5(
            signature=signature,
            facts=facts,
            clauses=clauses,
            goal_atoms=goal_atoms,
            definitions=definitions,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
            label=str(payload.get("label", "")),
        )
        return json.dumps({"countermodel": result})

    if operation == "find_clause_counterexamples":
        base_clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("base_clauses", []))
        clause = clause_from_dict(dict(payload["clause"]))
        result = find_clause_counterexamples_via_cvc5(
            signature=signature,
            facts=facts,
            base_clauses=base_clauses,
            definitions=definitions,
            clause=clause,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
        return json.dumps({"counterexamples": list(result)})

    if operation == "validate_clause_soundness":
        base_clauses = tuple(clause_from_dict(dict(item)) for item in payload.get("base_clauses", []))
        clause = clause_from_dict(dict(payload["clause"]))
        result = find_clause_counterexamples_via_cvc5(
            signature=signature,
            facts=facts,
            base_clauses=base_clauses,
            definitions=definitions,
            clause=clause,
            rewrites=rewrites,
            max_term_depth=max_term_depth,
        )
        return json.dumps({"failures": [str(item["message"]) for item in result]})

    raise ValueError(f"Unsupported cvc5 prover operation {operation!r}.")


def z3_backend_command() -> tuple[str, ...]:
    """Return the default subprocess command for the bundled Z3 driver.

    Keeping this command in one helper means configs and CLI callers can ask
    for the repo's canonical Z3 driver invocation rather than reconstruct it.
    """

    return (sys.executable, "-m", "abw_core.prover.z3_driver")


def cvc5_backend_command() -> tuple[str, ...]:
    """Return the default subprocess command for the bundled cvc5 driver.

    This is the cvc5 sibling of `z3_backend_command`, exposing the canonical
    repo-local subprocess entrypoint for that solver backend.
    """

    return (sys.executable, "-m", "abw_core.prover.cvc5_driver")
