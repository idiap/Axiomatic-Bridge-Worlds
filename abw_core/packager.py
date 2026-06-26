# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Package ABW worlds into the on-disk benchmark format and load them back.

ABW worlds are born as rich in-memory objects, but the benchmark, docs, and
external evaluation workflow all depend on a stable filesystem layout. This
module is the boundary between those two representations.

Core idea
---------
The packager turns one typed `ir.World` into a reproducible directory with:
- formal artifacts such as `.abw` files and JSON payloads
- natural-language renderings for the public and private surfaces
- metadata needed by scoring, sessions, and benchmark orchestration

The loader performs the inverse move, reconstructing the typed world so the
runtime can score, inspect, or validate packaged artifacts later.

Concrete example
----------------
A generated world might be written as:

    <world_root>/
      formal/signature.json
      formal/axioms.abw
      formal/hidden_bridge.json
      nl/problem.md
      nl/examples.md
      metadata.json

The benchmark runner then points target systems only at the public subset,
while the scorer reloads the full package through `load_world(...)`.

Paper-style framing
-------------------
The packager embodies a simple ABW discipline:

    the benchmark artifact should be inspectable as files, but those files
    should still round-trip back into one trustworthy typed world object.

Limitations
-----------
- The package layout is repo-defined and intentionally explicit rather than a
  generalized dataset serialization standard.
- JSON fields are trusted to match the runtime types; malformed packages fail
  during load or validation.
- The loader reconstructs the ABW package format, not arbitrary external world
  layouts.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from abw_core import ir
from abw_core.dsl import format_document, parse_document
from abw_core.nl import render_world
from abw_core.typecheck import check_world


REQUIRED_FILES = {
    "formal/signature.json",
    "formal/axioms.abw",
    "formal/visible_theorems.abw",
    "formal/visible_facts.abw",
    "formal/targets_visible.abw",
    "formal/targets_hidden.abw",
    "formal/hidden_bridge.json",
    "formal/gold_solution.abw",
    "formal/proof_fixtures.json",
    "formal/scoring_config.json",
    "nl/problem.md",
    "nl/examples.md",
    "nl/theorem_cards.md",
    "nl/hidden_bridge_private.md",
    "nl/gold_informal_solution_private.md",
    "nl/nl_alignment.json",
    "metadata.json",
}

PUBLIC_WORLD_FILES = {
    "formal/signature.json",
    "formal/axioms.abw",
    "formal/visible_theorems.abw",
    "formal/visible_facts.abw",
    "formal/targets_visible.abw",
    "nl/problem.md",
    "nl/examples.md",
    "nl/theorem_cards.md",
    "nl/nl_alignment.json",
    "metadata.json",
}

PRIVATE_WORLD_FILES = REQUIRED_FILES - PUBLIC_WORLD_FILES


def _private_bridge_names(world: ir.World) -> list[str]:
    """Collect hidden bridge names so leakage checks can be packaged explicitly.

    These names are stored alongside the hidden bridge payload so downstream
    tooling can detect private-symbol leakage without reverse-engineering the
    bridge object each time.
    """

    names = {
        definition.name for definition in world.hidden_bridge.definitions
    } | {
        mapping.name for mapping in world.hidden_bridge.mappings
    }
    return sorted(names)


def _term_from_dict(payload: dict[str, Any]) -> ir.Term:
    """Reconstruct one serialized term from the packaged JSON representation.

    The loader uses explicit per-node reconstruction rather than generic object
    casting so malformed payloads fail close to the real structural boundary.
    """

    kind = payload["kind"]
    if kind == "var":
        variable = payload["variable"]
        return ir.VarTerm(ir.Variable(variable["name"], variable["sort"]))
    if kind == "const":
        return ir.ConstTerm(payload["name"])
    if kind == "func":
        return ir.FuncTerm(payload["name"], tuple(_term_from_dict(argument) for argument in payload["args"]))
    raise ValueError(f"Unknown term payload kind {kind!r}.")


def _atom_from_dict(payload: dict[str, Any]) -> ir.Atom:
    """Reconstruct one serialized atom from its packaged JSON form."""

    return ir.Atom(payload["predicate"], tuple(_term_from_dict(term) for term in payload["terms"]))


def _clause_from_dict(payload: dict[str, Any]) -> ir.HornClause:
    """Reconstruct one Horn clause from packaged structured data.

    Clause payloads appear in hidden-bridge JSON and proof fixtures, so this
    helper centralizes the round-trip logic.
    """

    return ir.HornClause(
        name=payload["name"],
        variables=tuple(ir.Variable(item["name"], item["sort"]) for item in payload["variables"]),
        premises=tuple(_atom_from_dict(item) for item in payload["premises"]),
        conclusion=_atom_from_dict(payload["conclusion"]),
    )


def _rewrite_from_dict(payload: dict[str, Any]) -> ir.RewriteRule:
    """Reconstruct one rewrite rule from its packaged JSON representation."""

    return ir.RewriteRule(
        name=payload["name"],
        lhs=_term_from_dict(payload["lhs"]),
        rhs=_term_from_dict(payload["rhs"]),
    )


def _definition_from_dict(payload: dict[str, Any]) -> ir.Definition:
    """Reconstruct one bridge definition from structured package data."""

    return ir.Definition(
        name=payload["name"],
        parameters=tuple(ir.Variable(item["name"], item["sort"]) for item in payload["parameters"]),
        body=tuple(_atom_from_dict(item) for item in payload["body"]),
    )


def _morphism_from_dict(payload: dict[str, Any]) -> ir.SignatureMorphism:
    """Reconstruct one packaged signature morphism.

    Morphisms are stored as plain symbol maps on disk but need to come back as
    typed IR objects for scoring and validation.
    """

    return ir.SignatureMorphism(
        name=payload["name"],
        source_theory=payload["source_theory"],
        target_theory=payload["target_theory"],
        mapping={str(key): str(value) for key, value in dict(payload["mapping"]).items()},
    )


def _document_from_dict(payload: dict[str, Any]) -> ir.Document:
    """Reconstruct one packaged document tree from structured JSON.

    This is the recursive heart of JSON-side package loading. It is used for
    hidden bridges and nested theory documents where `.abw` surface files are
    not the chosen serialization.
    """

    return ir.Document(
        sorts=tuple(ir.Sort(item["name"]) for item in payload.get("sorts", [])),
        constants=tuple(
            ir.ConstantSymbol(item["name"], item["sort"]) for item in payload.get("constants", [])
        ),
        functions=tuple(
            ir.FunctionSymbol(item["name"], tuple(item["input_sorts"]), item["output_sort"])
            for item in payload.get("functions", [])
        ),
        predicates=tuple(
            ir.PredicateSymbol(item["name"], tuple(item["input_sorts"])) for item in payload.get("predicates", [])
        ),
        rewrites=tuple(_rewrite_from_dict(item) for item in payload.get("rewrites", [])),
        axioms=tuple(_clause_from_dict(item) for item in payload.get("axioms", [])),
        lemmas=tuple(_clause_from_dict(item) for item in payload.get("lemmas", [])),
        theorems=tuple(_clause_from_dict(item) for item in payload.get("theorems", [])),
        definitions=tuple(_definition_from_dict(item) for item in payload.get("definitions", [])),
        facts=tuple(
            ir.Fact(item["name"], _atom_from_dict(item["atom"])) for item in payload.get("facts", [])
        ),
        goals=tuple(
            ir.Goal(
                name=item["name"],
                atoms=tuple(_atom_from_dict(atom) for atom in item["atoms"]),
                budget=item.get("budget"),
                description=item.get("description", ""),
            )
            for item in payload.get("goals", [])
        ),
        theories=tuple(
            ir.Theory(item["name"], _document_from_dict(item["document"])) for item in payload.get("theories", [])
        ),
        morphisms=tuple(_morphism_from_dict(item) for item in payload.get("morphisms", [])),
    )


def _signature_from_dict(payload: dict[str, Any]) -> ir.Signature:
    """Reconstruct the world signature from the packaged JSON artifact.

    The signature is stored separately because many tools need it directly and
    because it is a compact, stable entrypoint into the world's type surface.
    """

    return ir.Signature(
        sorts=tuple(ir.Sort(item["name"]) for item in payload["sorts"]),
        constants=tuple(ir.ConstantSymbol(item["name"], item["sort"]) for item in payload["constants"]),
        functions=tuple(
            ir.FunctionSymbol(item["name"], tuple(item["input_sorts"]), item["output_sort"])
            for item in payload["functions"]
        ),
        predicates=tuple(ir.PredicateSymbol(item["name"], tuple(item["input_sorts"])) for item in payload["predicates"]),
    )


def package_world(world: ir.World, output_dir: str | Path) -> Path:
    """Write one generated world into the canonical ABW package layout.

    This function is where the abstract runtime world becomes benchmark data.
    It writes the formal public or private artifacts, the natural-language
    renderings, and the metadata required for later loading and evaluation.
    """

    root = Path(output_dir)
    formal_dir = root / "formal"
    nl_dir = root / "nl"
    formal_dir.mkdir(parents=True, exist_ok=True)
    nl_dir.mkdir(parents=True, exist_ok=True)

    rendered = render_world(world)

    # The formal directory preserves the typed benchmark structure in a mix of
    # ABW syntax and JSON so both humans and tools can inspect it easily.
    (formal_dir / "signature.json").write_text(json.dumps(world.signature.to_dict(), indent=2) + "\n", encoding="utf-8")
    (formal_dir / "axioms.abw").write_text(
        format_document(
            ir.Document(
                rewrites=world.rewrites,
                axioms=world.axioms,
                theories=world.theories,
                morphisms=world.visible_morphisms,
            )
        ),
        encoding="utf-8",
    )
    (formal_dir / "visible_theorems.abw").write_text(
        format_document(ir.Document(theorems=world.visible_theorems)),
        encoding="utf-8",
    )
    (formal_dir / "visible_facts.abw").write_text(format_document(ir.Document(facts=world.visible_facts)), encoding="utf-8")
    (formal_dir / "targets_visible.abw").write_text(
        format_document(ir.Document(goals=world.targets_visible)),
        encoding="utf-8",
    )
    (formal_dir / "targets_hidden.abw").write_text(
        format_document(ir.Document(goals=world.targets_hidden)),
        encoding="utf-8",
    )
    hidden_bridge_payload = world.hidden_bridge.to_dict() | {"private_names": _private_bridge_names(world)}
    (formal_dir / "hidden_bridge.json").write_text(
        json.dumps(hidden_bridge_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    (formal_dir / "gold_solution.abw").write_text(
        format_document(
            ir.Document(
                definitions=world.hidden_bridge.definitions,
                lemmas=world.hidden_bridge.lemmas,
                morphisms=world.hidden_bridge.mappings,
            )
        ),
        encoding="utf-8",
    )
    (formal_dir / "proof_fixtures.json").write_text(json.dumps(world.proof_fixtures, indent=2) + "\n", encoding="utf-8")
    (formal_dir / "scoring_config.json").write_text(json.dumps(world.scoring_config, indent=2) + "\n", encoding="utf-8")

    # The NL directory is the public-facing interpretive layer used by humans
    # and target systems that consume the task through rendered text.
    (nl_dir / "problem.md").write_text(rendered.problem_md, encoding="utf-8")
    (nl_dir / "examples.md").write_text(rendered.examples_md, encoding="utf-8")
    (nl_dir / "theorem_cards.md").write_text(rendered.theorem_cards_md, encoding="utf-8")
    (nl_dir / "hidden_bridge_private.md").write_text(rendered.hidden_bridge_private_md, encoding="utf-8")
    (nl_dir / "gold_informal_solution_private.md").write_text(
        rendered.gold_informal_solution_private_md,
        encoding="utf-8",
    )
    (nl_dir / "nl_alignment.json").write_text(json.dumps(rendered.alignment, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "world_id": world.world_id,
        "family": world.family,
        **world.metadata,
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return root


def load_world(world_root: str | Path) -> ir.World:
    """Load one packaged world back into the typed runtime representation.

    The loader accepts either the world root itself or one of its child paths.
    It rebuilds the formal components, reattaches metadata and proof fixtures,
    and then typechecks the reconstructed world so downstream code can trust
    that the package still represents a valid ABW instance.
    """

    root = Path(world_root)
    if (root / "formal").is_dir():
        world_path = root
    else:
        world_path = root.parent
    formal_dir = world_path / "formal"
    signature = _signature_from_dict(json.loads((formal_dir / "signature.json").read_text(encoding="utf-8")))

    axioms_doc = parse_document((formal_dir / "axioms.abw").read_text(encoding="utf-8"))
    theorems_doc = parse_document((formal_dir / "visible_theorems.abw").read_text(encoding="utf-8"))
    facts_doc = parse_document((formal_dir / "visible_facts.abw").read_text(encoding="utf-8"))
    targets_visible_doc = parse_document((formal_dir / "targets_visible.abw").read_text(encoding="utf-8"))
    targets_hidden_doc = parse_document((formal_dir / "targets_hidden.abw").read_text(encoding="utf-8"))
    hidden_bridge_payload = json.loads((formal_dir / "hidden_bridge.json").read_text(encoding="utf-8"))
    hidden_bridge = ir.Bridge(
        definitions=tuple(_definition_from_dict(item) for item in hidden_bridge_payload.get("definitions", [])),
        lemmas=tuple(_clause_from_dict(item) for item in hidden_bridge_payload.get("lemmas", [])),
        mappings=tuple(_morphism_from_dict(item) for item in hidden_bridge_payload.get("mappings", [])),
    )
    proof_fixtures = json.loads((formal_dir / "proof_fixtures.json").read_text(encoding="utf-8"))
    scoring_config = json.loads((formal_dir / "scoring_config.json").read_text(encoding="utf-8"))
    metadata = json.loads((world_path / "metadata.json").read_text(encoding="utf-8"))
    hidden_goals = tuple(
        ir.Goal(
            name=goal.name,
            atoms=goal.atoms,
            budget=proof_fixtures.get(goal.name, {}).get("budget"),
            description=goal.description,
        )
        for goal in targets_hidden_doc.goals
    )
    world = ir.World(
        world_id=metadata["world_id"],
        family=metadata["family"],
        signature=signature,
        rewrites=axioms_doc.rewrites,
        axioms=axioms_doc.axioms,
        visible_theorems=theorems_doc.theorems,
        visible_facts=facts_doc.facts,
        targets_visible=targets_visible_doc.goals,
        targets_hidden=hidden_goals,
        hidden_bridge=hidden_bridge,
        theories=axioms_doc.theories,
        visible_morphisms=axioms_doc.morphisms,
        proof_fixtures=proof_fixtures,
        scoring_config=scoring_config,
        metadata={key: value for key, value in metadata.items() if key not in {"world_id", "family"}},
    )
    # Re-validating at load time keeps package corruption or drift from leaking
    # silently into later evaluation stages.
    check_world(world)
    return world


def validate_package(world_root: str | Path) -> dict[str, Any]:
    """Check that a packaged world has the expected files and reloads cleanly.

    This is the filesystem-oriented integrity check used by CLI validation and
    packaging smoke tests. It answers a practical question: is this directory a
    complete, parseable ABW world package?
    """

    root = Path(world_root)
    missing = [relative_path for relative_path in sorted(REQUIRED_FILES) if not (root / relative_path).exists()]
    world = load_world(root)
    return {
        "world_id": world.world_id,
        "family": world.family,
        "missing_files": missing,
        "valid": not missing,
    }


def export_public_world(world_root: str | Path, output_dir: str | Path) -> Path:
    """Copy only the public subset of one packaged world into a new directory."""

    source_root = Path(world_root)
    destination_root = Path(output_dir)
    destination_root.mkdir(parents=True, exist_ok=True)

    missing = sorted(path for path in PUBLIC_WORLD_FILES if not (source_root / path).exists())
    if missing:
        raise FileNotFoundError(f"World at {source_root} is missing public export files: {missing!r}")

    for relative_path in sorted(PUBLIC_WORLD_FILES):
        source = source_root / relative_path
        destination = destination_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return destination_root


def export_public_dataset(dataset_root: str | Path, output_dir: str | Path) -> Path:
    """Export a packaged dataset with all private benchmark artifacts removed."""

    source_root = Path(dataset_root)
    destination_root = Path(output_dir)
    manifest_path = source_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Dataset root {source_root} does not contain manifest.json.")

    if destination_root.exists():
        shutil.rmtree(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_dir"] = str(destination_root)
    manifest["public_export"] = True
    manifest["private_artifacts_removed"] = sorted(PRIVATE_WORLD_FILES)
    (destination_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    world_roots = sorted(path.parent for path in source_root.rglob("metadata.json"))
    for world_path in world_roots:
        export_public_world(world_path, destination_root / world_path.relative_to(source_root))
    return destination_root
