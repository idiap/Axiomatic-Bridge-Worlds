# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Audit generated ABW datasets for duplicate tasks and split overlap."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from abw_core.benchmark import discover_worlds
from abw_core.generator.variation import benchmark_content_fingerprint, public_content_fingerprint
from abw_core.packager import load_world


def audit_dataset(dataset_root: Path) -> dict[str, Any]:
    records: list[dict[str, str]] = []
    for reference in discover_worlds(dataset_root):
        world = load_world(reference.root)
        records.append(
            {
                "split": reference.split,
                "family": reference.family,
                "world_id": reference.world_id,
                "schema": str(world.metadata.get("schema_fingerprint", "")),
                "public": public_content_fingerprint(world),
                "content": benchmark_content_fingerprint(world),
            }
        )

    by_family: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        by_family[record["family"]].append(record)

    families: dict[str, Any] = {}
    valid = True
    for family, rows in sorted(by_family.items()):
        splits: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            splits[row["split"]].add(row["schema"])
        split_names = sorted(splits)
        overlap = (
            set.intersection(*(splits[split] for split in split_names))
            if len(split_names) > 1
            else set()
        )
        family_report = {
            "worlds": len(rows),
            "unique_schema_fingerprints": len({row["schema"] for row in rows if row["schema"]}),
            "unique_public_tasks": len({row["public"] for row in rows}),
            "unique_full_tasks": len({row["content"] for row in rows}),
            "missing_schema_fingerprints": sum(not row["schema"] for row in rows),
            "schema_overlap_across_splits": len(overlap),
            "split_counts": {
                split: sum(row["split"] == split for row in rows) for split in split_names
            },
        }
        family_valid = (
            family_report["unique_schema_fingerprints"] == len(rows)
            and family_report["unique_public_tasks"] == len(rows)
            and family_report["unique_full_tasks"] == len(rows)
            and family_report["missing_schema_fingerprints"] == 0
            and family_report["schema_overlap_across_splits"] == 0
        )
        family_report["valid"] = family_valid
        valid = valid and family_valid
        families[family] = family_report

    return {
        "dataset_root": str(dataset_root.resolve()),
        "world_count": len(records),
        "family_count": len(families),
        "valid": valid and bool(records),
        "families": families,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = audit_dataset(args.dataset_root)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
