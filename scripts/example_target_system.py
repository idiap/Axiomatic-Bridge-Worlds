# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Example target-system adapter for the ABW benchmark runner.

This is a smoke-test and protocol-demonstration adapter, not a fair benchmark
participant. It deliberately loads the packaged private bridge, replaces hidden
names, and emits the result so integration tests can exercise the full scorer.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from abw_core import ir
from abw_core.dsl.printer import format_document
from abw_core.packager import load_world

def _renamed_example_candidate(world: ir.World) -> str:
    """Build a valid smoke-test candidate without reusing private bridge names."""

    definition_names = {
        definition.name: f"CandidateDef{index}"
        for index, definition in enumerate(world.hidden_bridge.definitions)
    }

    def rename_atom(atom: ir.Atom) -> ir.Atom:
        return ir.Atom(definition_names.get(atom.predicate, atom.predicate), atom.terms)

    definitions = tuple(
        ir.Definition(
            name=definition_names[definition.name],
            parameters=definition.parameters,
            body=tuple(rename_atom(atom) for atom in definition.body),
        )
        for definition in world.hidden_bridge.definitions
    )
    lemmas = tuple(
        ir.HornClause(
            name=f"candidate_lemma_{index}",
            variables=lemma.variables,
            premises=tuple(rename_atom(atom) for atom in lemma.premises),
            conclusion=rename_atom(lemma.conclusion),
        )
        for index, lemma in enumerate(world.hidden_bridge.lemmas)
    )
    morphisms = tuple(
        ir.SignatureMorphism(
            name=f"CandidateMap{index}",
            source_theory=morphism.source_theory,
            target_theory=morphism.target_theory,
            mapping=morphism.mapping,
        )
        for index, morphism in enumerate(world.hidden_bridge.mappings)
    )
    return format_document(ir.Document(definitions=definitions, lemmas=lemmas, morphisms=morphisms))


def main() -> int:
    """Read one benchmark request and emit one candidate response."""

    payload = json.load(sys.stdin)
    evaluation = payload.get("evaluation")
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    family = str(payload["family"])
    signature_path = Path(payload["public_artifacts"]["formal"]["signature"])
    world_root = signature_path.parent.parent
    candidate_text = _renamed_example_candidate(load_world(world_root))
    response = {
        "candidate": candidate_text,
        "metadata": {
            "adapter": "example_private_oracle_fixture",
            "family": family,
            "candidate_source": "packaged private bridge with hidden names replaced",
            "prompt_condition": evaluation.get("prompt_condition"),
            "exemplar_bank": evaluation.get("exemplar_bank"),
        },
    }
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
