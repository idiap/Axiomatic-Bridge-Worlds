# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Tiny stdin/stdout driver for the optional cvc5 backend protocol."""

from __future__ import annotations

import sys

from abw_core.prover.backends import run_cvc5_backend_operation


def main() -> int:
    """Serve exactly one cvc5-backed backend protocol request."""

    sys.stdout.write(run_cvc5_backend_operation(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
