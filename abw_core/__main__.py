# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Allow `python -m abw_core ...` as a small packaging convenience wrapper."""

from __future__ import annotations

from abw_core.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
