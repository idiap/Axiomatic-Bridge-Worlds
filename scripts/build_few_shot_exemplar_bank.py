# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Build a public-only few-shot exemplar bank for ABW prompt conditions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from abw_core.benchmark import discover_worlds
from abw_core.dsl.parser import parse_document
from abw_core.nl.controlled_candidate import (
    CandidateVocabulary,
    convert_controlled_nl,
    render_controlled_nl_candidate,
)


PAPER_FAMILIES = (
    "predicate_invention",
    "lemma_invention",
    "invariant",
    "analogy",
    "normal_form",
    "quotient",
    "multi_step",
)
PUBLIC_FORMAL_FILES = (
    "signature.json",
    "axioms.abw",
    "visible_facts.abw",
    "visible_theorems.abw",
    "targets_visible.abw",
)
PUBLIC_NL_FILES = (
    "problem.md",
    "examples.md",
    "theorem_cards.md",
)
FORBIDDEN_MARKERS = (
    "hidden_bridge",
    "targets_hidden",
    "gold_informal_solution_private",
    "hidden_bridge_private",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _public_formal_view(world_root: Path) -> tuple[str, dict[str, str]]:
    formal = world_root / "formal"
    sections: list[str] = []
    hashes: dict[str, str] = {}
    for name in PUBLIC_FORMAL_FILES:
        path = formal / name
        text = _read(path)
        hashes[name] = _sha256_text(text)
        sections.extend([f"## {name}", text, ""])
    view = "\n".join(sections).strip()
    lowered = view.lower()
    leaked = [marker for marker in FORBIDDEN_MARKERS if marker in lowered]
    if leaked:
        raise ValueError(f"Public formal view for {world_root} contains forbidden marker(s): {', '.join(leaked)}")
    return view, hashes


def _public_nl_view(world_root: Path) -> tuple[str, dict[str, str]]:
    nl = world_root / "nl"
    sections: list[str] = []
    hashes: dict[str, str] = {}
    for name in PUBLIC_NL_FILES:
        path = nl / name
        text = _read(path)
        hashes[name] = _sha256_text(text)
        sections.extend([f"## {name}", text, ""])
    view = "\n".join(sections).strip()
    lowered = view.lower()
    leaked = [marker for marker in FORBIDDEN_MARKERS if marker in lowered]
    if leaked:
        raise ValueError(f"Public natural-language view for {world_root} contains forbidden marker(s): {', '.join(leaked)}")
    return view, hashes


def _candidate(world_root: Path, *, view_condition: str) -> str:
    gold_candidate = _read(world_root / "formal" / "gold_solution.abw")
    if not gold_candidate:
        raise ValueError(f"Empty exemplar candidate at {world_root}")
    vocabulary = CandidateVocabulary.from_public_artifacts(
        world_root / "formal" / "signature.json",
        world_root / "formal" / "axioms.abw",
    )
    controlled_nl = render_controlled_nl_candidate(parse_document(gold_candidate), vocabulary).strip()
    if view_condition == "natural_language_direct":
        return controlled_nl
    conversion = convert_controlled_nl(controlled_nl, vocabulary)
    if conversion.status != "converted" or not conversion.candidate_dsl:
        raise ValueError(f"Could not normalize exemplar candidate at {world_root}: {conversion.errors}")
    return conversion.candidate_dsl.strip()


def build_exemplar_bank(
    *,
    dataset_root: Path,
    split: str,
    families: tuple[str, ...],
    exemplars_per_family: int,
    view_condition: str = "formal_direct",
) -> dict[str, Any]:
    """Build a solved public exemplar bank from a non-test split."""

    if split == "test_public":
        raise ValueError("Few-shot exemplar bank must not be built from test_public.")
    if view_condition not in {"formal_direct", "natural_language_direct", "cross_track"}:
        raise ValueError(
            "view_condition must be `formal_direct`, `natural_language_direct`, or `cross_track`."
        )
    exemplars: list[dict[str, Any]] = []
    worlds = discover_worlds(dataset_root, splits=(split,), families=families)
    by_family: dict[str, list[Any]] = {family: [] for family in families}
    for world in worlds:
        by_family.setdefault(world.family, []).append(world)

    for family in families:
        selected = sorted(by_family.get(family, []), key=lambda world: world.world_id)[:exemplars_per_family]
        if len(selected) < exemplars_per_family:
            raise ValueError(
                f"Requested {exemplars_per_family} exemplar(s) for {family}, found {len(selected)} in {split}."
        )
        for world in selected:
            metadata = json.loads((world.root / "metadata.json").read_text(encoding="utf-8"))
            schema_fingerprint = metadata.get("schema_fingerprint")
            if not isinstance(schema_fingerprint, str) or not schema_fingerprint:
                raise ValueError(f"Missing schema fingerprint for exemplar world {world.root}")
            if view_condition in {"natural_language_direct", "cross_track"}:
                public_view, artifact_hashes = _public_nl_view(world.root)
                public_view_key = "public_nl_view"
            else:
                public_view, artifact_hashes = _public_formal_view(world.root)
                public_view_key = "public_formal_view"
            candidate = _candidate(world.root, view_condition=view_condition)
            exemplar = {
                "id": f"{world.world_id}_{family}",
                "family": family,
                "source_split": split,
                "world_id": world.world_id,
                "schema_fingerprint": schema_fingerprint,
                public_view_key: public_view,
                "candidate": candidate,
                "public_artifact_hashes": artifact_hashes,
                "candidate_sha256": _sha256_text(candidate),
            }
            exemplars.append(exemplar)

    return {
        "exemplar_bank": f"abw_{view_condition}_few_shot",
        "status": "executable",
        "data_policy": (
            "Solved exemplars are drawn from a non-test split. The public view contains only "
            "artifacts available to the matching direct condition. Candidates "
            "are exemplar answers for the few-shot prompt and are not drawn from the test_public split."
        ),
        "view_condition": view_condition,
        "output_representation": (
            "controlled_natural_language" if view_condition == "natural_language_direct" else "abw_dsl"
        ),
        "dataset_root": str(dataset_root),
        "source_split": split,
        "families": list(families),
        "exemplars_per_family": exemplars_per_family,
        "exemplars": exemplars,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a public-only ABW few-shot exemplar bank.")
    parser.add_argument("--dataset-root", default=str(REPO_ROOT / "dataset" / "abw-formal-nl-core"))
    parser.add_argument("--split", default="dev")
    parser.add_argument("--family", action="append", default=[])
    parser.add_argument("--exemplars-per-family", type=int, default=2)
    parser.add_argument(
        "--view-condition",
        choices=("formal_direct", "natural_language_direct", "cross_track"),
        default="formal_direct",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "configs" / "formal_direct_few_shot_exemplars_seeded_v2.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    families = tuple(args.family) if args.family else PAPER_FAMILIES
    bank = build_exemplar_bank(
        dataset_root=Path(args.dataset_root),
        split=args.split,
        families=families,
        exemplars_per_family=args.exemplars_per_family,
        view_condition=args.view_condition,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bank, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "exemplars": len(bank["exemplars"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
