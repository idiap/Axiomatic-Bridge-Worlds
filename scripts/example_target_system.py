# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Example target-system adapter for the ABW benchmark runner.

This is a smoke-test and protocol-demonstration adapter, not a fair benchmark
participant. It reads one world request from stdin, chooses the matching family
fixture under [examples](../examples), and emits that candidate as JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Read one benchmark request and emit one candidate response."""

    payload = json.load(sys.stdin)
    family = str(payload["family"])
    candidate_path = REPO_ROOT / "examples" / family / "gold_candidate.abw"
    candidate_text = candidate_path.read_text(encoding="utf-8")
    response = {
        "candidate": candidate_text,
        "metadata": {
            "adapter": "example_family_fixture",
            "family": family,
            "candidate_source": str(candidate_path.resolve()),
        },
    }
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
