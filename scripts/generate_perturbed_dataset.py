# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Generate conservative ABW perturbation dataset copies."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
from typing import Any

from abw_core import ir
from abw_core.packager import load_world, package_world, validate_package


SUPPORTED_PERTURBATIONS = (
    "alpha_renaming",
    "axiom_order_shuffle",
    "nl_paraphrase",
    "distractor_insertion",
)
PLANNED_ONLY_PERTURBATIONS: tuple[str, ...] = ()


def _world_roots(dataset_root: Path) -> list[Path]:
    return sorted(path.parent for path in dataset_root.rglob("metadata.json"))


def _relative_world_root(dataset_root: Path, world_root: Path) -> Path:
    return world_root.relative_to(dataset_root)


def _copy_manifest(source: Path, destination: Path, *, perturbation: str) -> None:
    manifest_path = source / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_dataset_root"] = str(source)
    manifest["perturbation"] = perturbation
    manifest["output_dir"] = str(destination)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _indexed_map(names: set[str], prefix: str) -> dict[str, str]:
    return {name: f"alpha_{prefix}_{index:03d}" for index, name in enumerate(sorted(names))}


def _collect_document_names(
    document: ir.Document,
    *,
    sorts: set[str],
    constants: set[str],
    functions: set[str],
    predicates: set[str],
    theories: set[str],
    morphisms: set[str],
) -> None:
    sorts.update(sort.name for sort in document.sorts)
    constants.update(constant.name for constant in document.constants)
    functions.update(function.name for function in document.functions)
    predicates.update(predicate.name for predicate in document.predicates)
    predicates.update(definition.name for definition in document.definitions)
    theories.update(theory.name for theory in document.theories)
    morphisms.update(morphism.name for morphism in document.morphisms)
    for theory in document.theories:
        _collect_document_names(
            theory.document,
            sorts=sorts,
            constants=constants,
            functions=functions,
            predicates=predicates,
            theories=theories,
            morphisms=morphisms,
        )


def _alpha_maps(world: ir.World) -> dict[str, dict[str, str]]:
    sorts = {sort.name for sort in world.signature.sorts}
    constants = {constant.name for constant in world.signature.constants}
    functions = {function.name for function in world.signature.functions}
    predicates = {predicate.name for predicate in world.signature.predicates}
    theories: set[str] = set()
    morphisms: set[str] = set()
    variables: set[str] = set()

    public_document = world.public_document()
    private_document = ir.Document(
        definitions=world.hidden_bridge.definitions,
        lemmas=world.hidden_bridge.lemmas,
        morphisms=world.hidden_bridge.mappings,
    )
    _collect_document_names(
        public_document,
        sorts=sorts,
        constants=constants,
        functions=functions,
        predicates=predicates,
        theories=theories,
        morphisms=morphisms,
    )
    _collect_document_names(
        private_document,
        sorts=sorts,
        constants=constants,
        functions=functions,
        predicates=predicates,
        theories=theories,
        morphisms=morphisms,
    )

    def collect_term(term: ir.Term) -> None:
        if isinstance(term, ir.VarTerm):
            variables.add(term.variable.name)
        elif isinstance(term, ir.FuncTerm):
            for argument in term.args:
                collect_term(argument)

    def collect_atom(atom: ir.Atom) -> None:
        for term in atom.terms:
            collect_term(term)

    def collect_clause(clause: ir.HornClause) -> None:
        variables.update(variable.name for variable in clause.variables)
        for atom in clause.premises:
            collect_atom(atom)
        collect_atom(clause.conclusion)

    def collect_document_variables(document: ir.Document) -> None:
        for rewrite in document.rewrites:
            collect_term(rewrite.lhs)
            collect_term(rewrite.rhs)
        for clause in document.axioms + document.lemmas + document.theorems:
            collect_clause(clause)
        for definition in document.definitions:
            variables.update(parameter.name for parameter in definition.parameters)
            for atom in definition.body:
                collect_atom(atom)
        for fact in document.facts:
            collect_atom(fact.atom)
        for goal in document.goals:
            for atom in goal.atoms:
                collect_atom(atom)
        for theory in document.theories:
            collect_document_variables(theory.document)

    collect_document_variables(public_document)
    collect_document_variables(private_document)
    for goal in world.targets_hidden:
        for atom in goal.atoms:
            collect_atom(atom)

    return {
        "sorts": _indexed_map(sorts, "sort"),
        "constants": _indexed_map(constants, "const"),
        "functions": _indexed_map(functions, "func"),
        "predicates": _indexed_map(predicates, "pred"),
        "theories": _indexed_map(theories, "theory"),
        "morphisms": _indexed_map(morphisms, "morphism"),
        "variables": _indexed_map(variables, "var"),
    }


def _rename_sort_name(name: str, maps: dict[str, dict[str, str]]) -> str:
    return maps["sorts"].get(name, name)


def _rename_symbol_reference(name: str, maps: dict[str, dict[str, str]]) -> str:
    for key in ("sorts", "constants", "functions", "predicates"):
        renamed = maps[key].get(name)
        if renamed is not None:
            return renamed
    return name


def _rename_variable(variable: ir.Variable, maps: dict[str, dict[str, str]]) -> ir.Variable:
    return ir.Variable(maps["variables"].get(variable.name, variable.name), _rename_sort_name(variable.sort, maps))


def _rename_term(term: ir.Term, maps: dict[str, dict[str, str]]) -> ir.Term:
    if isinstance(term, ir.VarTerm):
        return ir.VarTerm(_rename_variable(term.variable, maps))
    if isinstance(term, ir.ConstTerm):
        return ir.ConstTerm(maps["constants"].get(term.name, term.name))
    if isinstance(term, ir.FuncTerm):
        return ir.FuncTerm(
            maps["functions"].get(term.name, term.name),
            tuple(_rename_term(argument, maps) for argument in term.args),
        )
    raise TypeError(f"Unsupported term type: {type(term)!r}")


def _rename_atom(atom: ir.Atom, maps: dict[str, dict[str, str]]) -> ir.Atom:
    predicate = atom.predicate if atom.predicate == "=" else maps["predicates"].get(atom.predicate, atom.predicate)
    return ir.Atom(predicate, tuple(_rename_term(term, maps) for term in atom.terms))


def _rename_clause(clause: ir.HornClause, maps: dict[str, dict[str, str]]) -> ir.HornClause:
    return ir.HornClause(
        name=clause.name,
        variables=tuple(_rename_variable(variable, maps) for variable in clause.variables),
        premises=tuple(_rename_atom(atom, maps) for atom in clause.premises),
        conclusion=_rename_atom(clause.conclusion, maps),
    )


def _rename_rewrite(rewrite: ir.RewriteRule, maps: dict[str, dict[str, str]]) -> ir.RewriteRule:
    return ir.RewriteRule(
        name=rewrite.name,
        lhs=_rename_term(rewrite.lhs, maps),
        rhs=_rename_term(rewrite.rhs, maps),
    )


def _rename_definition(definition: ir.Definition, maps: dict[str, dict[str, str]]) -> ir.Definition:
    return ir.Definition(
        name=maps["predicates"].get(definition.name, definition.name),
        parameters=tuple(_rename_variable(parameter, maps) for parameter in definition.parameters),
        body=tuple(_rename_atom(atom, maps) for atom in definition.body),
    )


def _rename_fact(fact: ir.Fact, maps: dict[str, dict[str, str]]) -> ir.Fact:
    return ir.Fact(name=fact.name, atom=_rename_atom(fact.atom, maps))


def _rename_goal(goal: ir.Goal, maps: dict[str, dict[str, str]]) -> ir.Goal:
    return ir.Goal(
        name=goal.name,
        atoms=tuple(_rename_atom(atom, maps) for atom in goal.atoms),
        budget=goal.budget,
        description=goal.description,
    )


def _rename_signature(signature: ir.Signature, maps: dict[str, dict[str, str]]) -> ir.Signature:
    return ir.Signature(
        sorts=tuple(ir.Sort(_rename_sort_name(sort.name, maps)) for sort in signature.sorts),
        constants=tuple(
            ir.ConstantSymbol(maps["constants"].get(constant.name, constant.name), _rename_sort_name(constant.sort, maps))
            for constant in signature.constants
        ),
        functions=tuple(
            ir.FunctionSymbol(
                maps["functions"].get(function.name, function.name),
                tuple(_rename_sort_name(sort, maps) for sort in function.input_sorts),
                _rename_sort_name(function.output_sort, maps),
            )
            for function in signature.functions
        ),
        predicates=tuple(
            ir.PredicateSymbol(
                maps["predicates"].get(predicate.name, predicate.name),
                tuple(_rename_sort_name(sort, maps) for sort in predicate.input_sorts),
            )
            for predicate in signature.predicates
        ),
    )


def _rename_morphism(morphism: ir.SignatureMorphism, maps: dict[str, dict[str, str]]) -> ir.SignatureMorphism:
    return ir.SignatureMorphism(
        name=maps["morphisms"].get(morphism.name, morphism.name),
        source_theory=maps["theories"].get(morphism.source_theory, morphism.source_theory),
        target_theory=maps["theories"].get(morphism.target_theory, morphism.target_theory),
        mapping={
            _rename_symbol_reference(source, maps): _rename_symbol_reference(target, maps)
            for source, target in morphism.mapping.items()
        },
    )


def _rename_document(document: ir.Document, maps: dict[str, dict[str, str]]) -> ir.Document:
    return ir.Document(
        sorts=tuple(ir.Sort(_rename_sort_name(sort.name, maps)) for sort in document.sorts),
        constants=tuple(
            ir.ConstantSymbol(maps["constants"].get(constant.name, constant.name), _rename_sort_name(constant.sort, maps))
            for constant in document.constants
        ),
        functions=tuple(
            ir.FunctionSymbol(
                maps["functions"].get(function.name, function.name),
                tuple(_rename_sort_name(sort, maps) for sort in function.input_sorts),
                _rename_sort_name(function.output_sort, maps),
            )
            for function in document.functions
        ),
        predicates=tuple(
            ir.PredicateSymbol(
                maps["predicates"].get(predicate.name, predicate.name),
                tuple(_rename_sort_name(sort, maps) for sort in predicate.input_sorts),
            )
            for predicate in document.predicates
        ),
        rewrites=tuple(_rename_rewrite(rewrite, maps) for rewrite in document.rewrites),
        axioms=tuple(_rename_clause(clause, maps) for clause in document.axioms),
        lemmas=tuple(_rename_clause(clause, maps) for clause in document.lemmas),
        theorems=tuple(_rename_clause(clause, maps) for clause in document.theorems),
        definitions=tuple(_rename_definition(definition, maps) for definition in document.definitions),
        facts=tuple(_rename_fact(fact, maps) for fact in document.facts),
        goals=tuple(_rename_goal(goal, maps) for goal in document.goals),
        theories=tuple(
            ir.Theory(maps["theories"].get(theory.name, theory.name), _rename_document(theory.document, maps))
            for theory in document.theories
        ),
        morphisms=tuple(_rename_morphism(morphism, maps) for morphism in document.morphisms),
    )


def _rename_bridge(bridge: ir.Bridge, maps: dict[str, dict[str, str]]) -> ir.Bridge:
    return ir.Bridge(
        definitions=tuple(_rename_definition(definition, maps) for definition in bridge.definitions),
        lemmas=tuple(_rename_clause(lemma, maps) for lemma in bridge.lemmas),
        mappings=tuple(_rename_morphism(mapping, maps) for mapping in bridge.mappings),
    )


def _rename_json_symbols(value: Any, maps: dict[str, dict[str, str]]) -> Any:
    if isinstance(value, str):
        return _rename_symbol_reference(value, maps)
    if isinstance(value, list):
        return [_rename_json_symbols(item, maps) for item in value]
    if isinstance(value, dict):
        return {
            _rename_symbol_reference(str(key), maps): _rename_json_symbols(item, maps)
            for key, item in value.items()
        }
    return value


def _alpha_rename_world(world: ir.World) -> ir.World:
    maps = _alpha_maps(world)
    return replace(
        world,
        signature=_rename_signature(world.signature, maps),
        rewrites=tuple(_rename_rewrite(rewrite, maps) for rewrite in world.rewrites),
        axioms=tuple(_rename_clause(clause, maps) for clause in world.axioms),
        visible_theorems=tuple(_rename_clause(clause, maps) for clause in world.visible_theorems),
        visible_facts=tuple(_rename_fact(fact, maps) for fact in world.visible_facts),
        targets_visible=tuple(_rename_goal(goal, maps) for goal in world.targets_visible),
        targets_hidden=tuple(_rename_goal(goal, maps) for goal in world.targets_hidden),
        hidden_bridge=_rename_bridge(world.hidden_bridge, maps),
        theories=tuple(
            ir.Theory(maps["theories"].get(theory.name, theory.name), _rename_document(theory.document, maps))
            for theory in world.theories
        ),
        visible_morphisms=tuple(_rename_morphism(morphism, maps) for morphism in world.visible_morphisms),
        scoring_config=_rename_json_symbols(world.scoring_config, maps),
        metadata={
            **world.metadata,
            "perturbation": "alpha_renaming",
            "perturbation_note": "Formal symbols were deterministically alpha-renamed while preserving world ids and statement ids.",
            "alpha_renaming_map": {key: value for key, value in maps.items() if key != "variables"},
        },
    )


def _package_alpha_renamed_world(source_world: Path, destination_world: Path) -> None:
    package_world(_alpha_rename_world(load_world(source_world)), destination_world)


def _package_reordered_world(source_world: Path, destination_world: Path) -> None:
    world = load_world(source_world)
    perturbed = replace(
        world,
        axioms=tuple(reversed(world.axioms)),
        visible_theorems=tuple(reversed(world.visible_theorems)),
        visible_facts=tuple(reversed(world.visible_facts)),
        targets_visible=tuple(reversed(world.targets_visible)),
        metadata={
            **world.metadata,
            "perturbation": "axiom_order_shuffle",
            "perturbation_note": "Public axioms, facts, theorems, and visible targets are emitted in reversed order.",
        },
    )
    package_world(perturbed, destination_world)


def _copy_with_nl_marker(source_world: Path, destination_world: Path, *, perturbation: str, marker: str) -> None:
    shutil.copytree(source_world, destination_world)
    metadata_path = destination_world / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["perturbation"] = perturbation
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    for relative_path in ("nl/problem.md", "nl/examples.md", "nl/theorem_cards.md"):
        path = destination_world / relative_path
        if path.exists():
            original = path.read_text(encoding="utf-8")
            path.write_text(marker + "\n\n" + original, encoding="utf-8")


def generate_perturbed_dataset(
    source_root: str | Path,
    output_root: str | Path,
    *,
    perturbation: str,
    validate: bool = True,
) -> dict[str, object]:
    """Generate one conservative perturbed dataset copy."""

    source = Path(source_root)
    destination = Path(output_root)
    if perturbation in PLANNED_ONLY_PERTURBATIONS:
        raise ValueError(
            f"Perturbation {perturbation!r} requires symbol-consistent private/public renaming and is planned only."
        )
    if perturbation not in SUPPORTED_PERTURBATIONS:
        raise ValueError(f"Unsupported perturbation {perturbation!r}.")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _copy_manifest(source, destination, perturbation=perturbation)

    failures: list[dict[str, object]] = []
    world_count = 0
    for source_world in _world_roots(source):
        destination_world = destination / _relative_world_root(source, source_world)
        if perturbation == "alpha_renaming":
            _package_alpha_renamed_world(source_world, destination_world)
        elif perturbation == "axiom_order_shuffle":
            _package_reordered_world(source_world, destination_world)
        elif perturbation == "nl_paraphrase":
            _copy_with_nl_marker(
                source_world,
                destination_world,
                perturbation=perturbation,
                marker="Paraphrase variant: the formal task is unchanged; this public text is a regenerated wording.",
            )
        elif perturbation == "distractor_insertion":
            _copy_with_nl_marker(
                source_world,
                destination_world,
                perturbation=perturbation,
                marker="Distractor note: ignore unrelated surface wording; the formal public artifacts remain authoritative.",
            )
        world_count += 1
        if validate:
            report = validate_package(destination_world)
            if not report.get("valid", False):
                failures.append({"world_root": str(destination_world), "report": report})
    return {
        "source": str(source),
        "output": str(destination),
        "perturbation": perturbation,
        "worlds": world_count,
        "valid": not failures,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a conservative perturbed ABW dataset copy.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--perturbation", choices=SUPPORTED_PERTURBATIONS + PLANNED_ONLY_PERTURBATIONS, required=True)
    parser.add_argument("--no-validate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = generate_perturbed_dataset(
        args.source,
        args.output,
        perturbation=args.perturbation,
        validate=not args.no_validate,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
