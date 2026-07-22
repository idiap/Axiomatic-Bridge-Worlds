# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Command-line entrypoints for the ABW runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from abw_core import ir
from abw_core.benchmark import run_benchmark
from abw_core.config import load_config, manifest_payload
from abw_core.dsl import parse_document
from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.generator.variation import (
    GENERATOR_VERSION,
    benchmark_content_fingerprint,
    public_content_fingerprint,
)
from abw_core.packager import export_public_dataset, load_world, package_world, validate_package
from abw_core.prover import BackendConfig, find_goal_countermodel_with_backend
from abw_core.scorer import evaluate_candidate, load_candidate_text
from abw_core.session import finish_session, interactive_world_settings, run_session_query, start_session
from abw_core.typecheck import build_theory_signatures, check_document, reject_hidden_symbol_names


def _parse_hidden_steps(raw: str) -> tuple[int, ...]:
    """Parse a comma-separated hidden-target depth list from the CLI."""

    return tuple(int(item.strip()) for item in raw.split(",") if item.strip())


def _configured_backend(
    world: ir.World,
    *,
    backend_name: str | None = None,
    backend_command: Sequence[str] = (),
) -> BackendConfig:
    """Resolve the prover backend requested by CLI flags or world config."""

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


def _goal_named(world: ir.World, name: str) -> ir.Goal | None:
    """Look up one goal by name across the visible and hidden target sets."""

    for goal in world.targets_hidden + world.targets_visible:
        if goal.name == name:
            return goal
    return None


def _probe_atoms(
    signature: ir.Signature,
    *,
    world: ir.World,
    goal_name: str | None,
    atoms_text: str | None,
) -> tuple[str, tuple[ir.Atom, ...], list[str]]:
    """Resolve a CLI goal query into a label, atom tuple, and validation errors."""

    if goal_name:
        goal = _goal_named(world, goal_name)
        if goal is None:
            return goal_name, (), [f"Unknown goal {goal_name!r}."]
        return goal.name, goal.atoms, []
    if atoms_text is None:
        return "probe", (), ["No goal query was provided."]
    try:
        document = parse_document(f"goal probe: {atoms_text}")
        check_document(document, base_signature=signature)
    except Exception as error:  # noqa: BLE001
        return "probe", (), [str(error)]
    return "probe", document.goals[0].atoms, []


def _hidden_names(world: ir.World) -> set[str]:
    """Collect the hidden bridge symbols that public probes must not mention."""

    return {
        definition.name for definition in world.hidden_bridge.definitions
    } | {
        mapping.name for mapping in world.hidden_bridge.mappings
    }


def _analysis_candidate_document(world: ir.World, path: str | Path) -> tuple[ir.Document, ir.Signature, list[str]]:
    """Parse and typecheck an analysis-only candidate file for countermodel queries."""

    candidate_text = Path(path).read_text(encoding="utf-8")
    errors: list[str] = []
    leak_names = reject_hidden_symbol_names(candidate_text, _hidden_names(world))
    if leak_names:
        errors.append(f"Candidate uses private hidden symbol names: {', '.join(leak_names)}.")
    try:
        document = parse_document(candidate_text)
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
            or document.morphisms
        ):
            raise ValueError("Countermodel analysis candidates may only contain definitions, lemmas, or theorems.")
        extended_signature = check_document(
            document,
            base_signature=world.signature,
            theory_signatures=build_theory_signatures(world.public_document()),
        )
    except Exception as error:  # noqa: BLE001
        errors.append(str(error))
        return ir.Document(), world.signature, errors
    return document, extended_signature, errors


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line surface for the ABW runtime."""

    parser = argparse.ArgumentParser(description="Axiomatic Bridge Worlds runtime.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    world_parser = subparsers.add_parser("generate-world", help="Generate and package one ABW world.")
    world_parser.add_argument("--family", default="predicate_invention")
    world_parser.add_argument("--seed", type=int, required=True)
    world_parser.add_argument("--output", required=True)
    world_parser.add_argument("--world-id")
    world_parser.add_argument("--max-term-depth", type=int, default=3)
    world_parser.add_argument("--proof-budget", type=int, default=3)
    world_parser.add_argument("--hidden-steps", default="2,3")
    world_parser.add_argument("--no-distractors", action="store_true")

    dataset_parser = subparsers.add_parser("generate-dataset", help="Generate a small packaged ABW dataset.")
    dataset_parser.add_argument("--config", required=True)
    dataset_parser.add_argument("--output")

    export_parser = subparsers.add_parser(
        "export-public-dataset",
        help="Copy a packaged dataset into a public-only export with private artifacts removed.",
    )
    export_parser.add_argument("--dataset", required=True)
    export_parser.add_argument("--output", required=True)

    benchmark_parser = subparsers.add_parser(
        "run-benchmark",
        help="Run one external target system across a packaged ABW dataset and aggregate the scores.",
    )
    benchmark_parser.add_argument("--dataset", required=True)
    benchmark_parser.add_argument(
        "--target-command",
        action="append",
        required=True,
        default=[],
        help="Repeat once per token to define the evaluated system command.",
    )
    benchmark_parser.add_argument("--output")
    benchmark_parser.add_argument("--split", action="append", default=[])
    benchmark_parser.add_argument("--family", action="append", default=[])
    benchmark_parser.add_argument("--limit", type=int)
    benchmark_parser.add_argument("--timeout-seconds", type=float, default=60.0)
    benchmark_parser.add_argument("--prover-backend")
    benchmark_parser.add_argument(
        "--backend-command",
        action="append",
        default=[],
        help="Repeat once per token when overriding the scorer backend with subprocess.",
    )
    score_parser = subparsers.add_parser("score-candidate", help="Score a candidate bridge against a packaged world.")
    score_parser.add_argument("--world", required=True)
    score_parser.add_argument("--candidate", required=True)
    score_parser.add_argument("--prover-backend")
    score_parser.add_argument(
        "--backend-command",
        action="append",
        default=[],
        help="Repeat once per token when using --prover-backend subprocess.",
    )

    countermodel_parser = subparsers.add_parser(
        "countermodel-goal",
        help="Return a bounded countermodel for a goal that is not derivable in the current bounded world.",
    )
    countermodel_parser.add_argument("--world", required=True)
    goal_group = countermodel_parser.add_mutually_exclusive_group(required=True)
    goal_group.add_argument("--goal")
    goal_group.add_argument("--atoms")
    countermodel_parser.add_argument("--candidate")
    countermodel_parser.add_argument("--prover-backend")
    countermodel_parser.add_argument(
        "--backend-command",
        action="append",
        default=[],
        help="Repeat once per token when using --prover-backend subprocess.",
    )

    start_session_parser = subparsers.add_parser(
        "start-session",
        help="Create a budgeted interactive refinement session for a packaged world.",
    )
    start_session_parser.add_argument("--world", required=True)
    start_session_parser.add_argument("--output", required=True)
    start_session_parser.add_argument("--session-id")
    start_session_parser.add_argument("--query-budget", type=int)

    session_query_parser = subparsers.add_parser(
        "session-query",
        help="Spend one interactive query on validation, equivalence, examples, or a bounded public countermodel.",
    )
    session_query_parser.add_argument("--session", required=True)
    session_query_parser.add_argument(
        "--kind",
        choices=("validate", "equivalence", "countermodel", "examples"),
        required=True,
    )
    session_query_parser.add_argument("--candidate")
    session_query_parser.add_argument("--goal")
    session_query_parser.add_argument("--atoms")
    session_query_parser.add_argument("--predicate")
    session_query_parser.add_argument("--limit", type=int, default=5)
    session_query_parser.add_argument("--prover-backend")
    session_query_parser.add_argument(
        "--backend-command",
        action="append",
        default=[],
        help="Repeat once per token when using --prover-backend subprocess.",
    )

    finish_session_parser = subparsers.add_parser(
        "finish-session",
        help="Score one final submission for an existing interactive session.",
    )
    finish_session_parser.add_argument("--session", required=True)
    finish_session_parser.add_argument("--candidate", required=True)
    finish_session_parser.add_argument("--prover-backend")
    finish_session_parser.add_argument(
        "--backend-command",
        action="append",
        default=[],
        help="Repeat once per token when using --prover-backend subprocess.",
    )

    inspect_parser = subparsers.add_parser("inspect-world", help="Print a JSON summary for a packaged world.")
    inspect_parser.add_argument("--world", required=True)

    validate_parser = subparsers.add_parser("validate-world", help="Validate the required packaged world files.")
    validate_parser.add_argument("--world", required=True)
    return parser


def _cmd_generate_world(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    request = WorldGenerationRequest(
        family=args.family,
        seed=args.seed,
        world_id=args.world_id,
        max_term_depth=args.max_term_depth,
        proof_budget=args.proof_budget,
        hidden_steps=_parse_hidden_steps(args.hidden_steps),
        include_distractors=not args.no_distractors,
    )
    world = generate_world(request)
    output = package_world(world, args.output)
    print(json.dumps({"world_id": world.world_id, "output": str(output)}, indent=2))
    return 0


def _cmd_generate_dataset(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    config = load_config(args.config)
    output_root = Path(args.output or config.output_dir)
    split_counts: dict[str, int] = {}
    seed = config.start_seed
    family_count = len(config.families)
    family_index = 0
    seen_schema: dict[str, set[str]] = {family: set() for family in config.families}
    seen_content: dict[str, set[str]] = {family: set() for family in config.families}
    seen_public: dict[str, set[str]] = {family: set() for family in config.families}
    split_schema: dict[str, dict[str, set[str]]] = {}
    duplicate_resamples = 0
    for split, count in config.splits.items():
        split_counts[split] = count
        split_schema[split] = {family: set() for family in config.families}
        if config.split_start_seeds and split in config.split_start_seeds:
            seed = config.split_start_seeds[split]
        for index in range(count):
            family = config.families[family_index % family_count]
            world_id = f"abw_{split}_{index:04d}"
            for _attempt in range(10_000):
                request = WorldGenerationRequest(
                    family=family,
                    seed=seed,
                    world_id=world_id,
                    max_term_depth=config.max_term_depth,
                    proof_budget=config.proof_budget,
                    hidden_steps=config.hidden_steps,
                    include_distractors=config.include_distractors,
                    interactive_enabled=config.interactive_enabled,
                    interactive_query_budget=config.interactive_query_budget,
                    interactive_countermodels=config.interactive_countermodels,
                    prover_backend_name=config.prover_backend_name,
                    prover_backend_command=config.prover_backend_command,
                )
                world = generate_world(request)
                schema_fingerprint = str(world.metadata.get("schema_fingerprint", ""))
                content_fingerprint = benchmark_content_fingerprint(world)
                public_fingerprint = public_content_fingerprint(world)
                if not schema_fingerprint:
                    raise ValueError(f"Generated {family} world is missing schema_fingerprint metadata.")
                if (
                    schema_fingerprint not in seen_schema[family]
                    and content_fingerprint not in seen_content[family]
                    and public_fingerprint not in seen_public[family]
                ):
                    break
                duplicate_resamples += 1
                seed += 1
            else:
                raise RuntimeError(f"Could not find a unique {family} schema after 10,000 seeds.")

            world.metadata["content_fingerprint"] = content_fingerprint
            world.metadata["public_content_fingerprint"] = public_fingerprint
            package_world(world, output_root / split / family / world_id)
            seen_schema[family].add(schema_fingerprint)
            seen_content[family].add(content_fingerprint)
            seen_public[family].add(public_fingerprint)
            split_schema[split][family].add(schema_fingerprint)
            seed += 1
            family_index += 1
    manifest = manifest_payload(config, split_counts, output_dir=output_root)
    split_names = list(split_schema)
    overlap_by_family = {
        family: len(
            set.intersection(*(split_schema[split][family] for split in split_names))
            if len(split_names) > 1
            else set()
        )
        for family in config.families
    }
    manifest["diversity"] = {
        "generator_version": GENERATOR_VERSION,
        "schema_unique_per_family": {family: len(values) for family, values in seen_schema.items()},
        "content_unique_per_family": {family: len(values) for family, values in seen_content.items()},
        "public_content_unique_per_family": {family: len(values) for family, values in seen_public.items()},
        "schema_overlap_across_splits_per_family": overlap_by_family,
        "duplicate_seed_resamples": duplicate_resamples,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_root), "manifest": str(output_root / 'manifest.json')}, indent=2))
    return 0


def _cmd_export_public_dataset(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    output_root = export_public_dataset(args.dataset, args.output)
    print(
        json.dumps(
            {
                "dataset": str(Path(args.dataset).resolve()),
                "output": str(output_root.resolve()),
                "manifest": str((output_root / "manifest.json").resolve()),
            },
            indent=2,
        )
    )
    return 0


def _cmd_run_benchmark(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    results = run_benchmark(
        args.dataset,
        target_command=tuple(args.target_command),
        splits=tuple(args.split),
        families=tuple(args.family),
        limit=args.limit,
        timeout_seconds=args.timeout_seconds,
        backend_name=args.prover_backend,
        backend_command=tuple(args.backend_command),
        output_path=args.output,
    )
    if args.output:
        payload: dict[str, object] = {"summary": results["summary"]}
        payload["output"] = str(Path(args.output))
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(results, indent=2))
    return 0


def _cmd_score_candidate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    report = evaluate_candidate(
        args.world,
        load_candidate_text(args.candidate),
        backend_name=args.prover_backend,
        backend_command=tuple(args.backend_command),
    )
    print(json.dumps(report, indent=2))
    return 0


def _cmd_countermodel_goal(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    world = load_world(args.world)
    backend = _configured_backend(
        world,
        backend_name=args.prover_backend,
        backend_command=args.backend_command,
    )
    candidate_document = ir.Document()
    signature = world.signature
    errors: list[str] = []
    if args.candidate:
        candidate_document, signature, errors = _analysis_candidate_document(world, args.candidate)
    label, goal_atoms, goal_errors = _probe_atoms(
        signature,
        world=world,
        goal_name=args.goal,
        atoms_text=args.atoms,
    )
    errors.extend(goal_errors)

    countermodel = None
    if not errors:
        countermodel = find_goal_countermodel_with_backend(
            signature=signature,
            facts=world.visible_facts,
            clauses=world.public_clauses() + candidate_document.lemmas + candidate_document.theorems,
            goal_atoms=goal_atoms,
            definitions=candidate_document.definitions,
            rewrites=world.rewrites,
            max_term_depth=int(world.metadata.get("max_term_depth", 3)),
            label=label,
            backend=backend,
        )
    print(
        json.dumps(
            {
                "goal": label,
                "goal_atoms": [atom.to_dict() for atom in goal_atoms],
                "candidate": str(args.candidate) if args.candidate else None,
                "candidate_valid": not errors,
                "errors": errors,
                "proved": not errors and countermodel is None,
                "countermodel": countermodel,
            },
            indent=2,
        )
    )
    return 0


def _cmd_start_session(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    payload = start_session(
        args.world,
        args.output,
        session_id=args.session_id,
        query_budget=args.query_budget,
    )
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_session_query(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.kind in {"validate", "equivalence"} and not args.candidate:
        parser.error(f"session-query --kind {args.kind} requires --candidate.")
    if args.kind == "countermodel":
        if bool(args.goal) == bool(args.atoms):
            parser.error("session-query --kind countermodel requires exactly one of --goal or --atoms.")
    elif args.goal or args.atoms:
        parser.error("--goal and --atoms are only valid with session-query --kind countermodel.")
    if args.kind == "examples" and not args.predicate:
        parser.error("session-query --kind examples requires --predicate.")
    if args.kind != "examples" and args.predicate:
        parser.error("--predicate is only valid with session-query --kind examples.")

    payload = run_session_query(
        args.session,
        kind=args.kind,
        candidate_path=args.candidate,
        goal_name=args.goal,
        atoms_text=args.atoms,
        predicate=args.predicate,
        limit=args.limit,
        backend_name=args.prover_backend,
        backend_command=tuple(args.backend_command),
    )
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_finish_session(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    payload = finish_session(
        args.session,
        candidate_path=args.candidate,
        backend_name=args.prover_backend,
        backend_command=tuple(args.backend_command),
    )
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_inspect_world(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    world = load_world(args.world)
    print(
        json.dumps(
            {
                "world_id": world.world_id,
                "family": world.family,
                "visible_fact_count": len(world.visible_facts),
                "hidden_goal_count": len(world.targets_hidden),
                "hidden_definition_count": len(world.hidden_bridge.definitions),
                "hidden_mapping_count": len(world.hidden_bridge.mappings),
                "proof_fixtures": world.proof_fixtures,
                "interactive": interactive_world_settings(world),
                "prover_backend": world.scoring_config.get("prover_backend", {"name": "local", "command": []}),
            },
            indent=2,
        )
    )
    return 0


def _cmd_validate_world(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    print(json.dumps(validate_package(args.world), indent=2))
    return 0


# Subcommand name -> handler. `build_parser` already restricts `args.command` to
# these keys, so the dispatch stays a simple, exhaustive table.
_COMMANDS = {
    "generate-world": _cmd_generate_world,
    "generate-dataset": _cmd_generate_dataset,
    "export-public-dataset": _cmd_export_public_dataset,
    "run-benchmark": _cmd_run_benchmark,
    "score-candidate": _cmd_score_candidate,
    "countermodel-goal": _cmd_countermodel_goal,
    "start-session": _cmd_start_session,
    "session-query": _cmd_session_query,
    "finish-session": _cmd_finish_session,
    "inspect-world": _cmd_inspect_world,
    "validate-world": _cmd_validate_world,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ABW CLI with one parsed argument vector."""

    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.error("Unknown command.")
        return 2
    return handler(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())
