# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Canonical entry point for dataset generation.

Running this script with no arguments uses the repository's canonical dataset
generation config and its default output directory. Callers may still override
the config path or the output root when they need a different target.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from abw_core.cli import main


DEFAULT_CONFIG = REPO_ROOT / "configs" / "mvp.yaml"


def build_parser() -> argparse.ArgumentParser:
    """Build the thin CLI wrapper around the canonical dataset-generation command."""

    parser = argparse.ArgumentParser(description="Generate the ABW dataset from the canonical config.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    output_root = Path(args.output) if args.output else None
    if output_root is None and Path(args.config) == DEFAULT_CONFIG:
        output_root = REPO_ROOT / "datasets" / "mvp"
    if output_root is not None and output_root.exists():
        shutil.rmtree(output_root)
    forwarded = ["generate-dataset", "--config", args.config]
    if output_root is not None:
        forwarded.extend(["--output", str(output_root)])
    raise SystemExit(main(forwarded))
