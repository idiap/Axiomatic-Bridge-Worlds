# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Tiny stdin/stdout driver for the subprocess prover backend protocol."""

from __future__ import annotations

import sys

from abw_core.prover.backends import run_subprocess_backend_operation


def main() -> int:
    """Serve exactly one backend protocol request over stdin/stdout."""

    sys.stdout.write(run_subprocess_backend_operation(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
