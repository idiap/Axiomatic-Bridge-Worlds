# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Alignment helpers for pairing NL renderings with formal sources."""

from __future__ import annotations


def entry(nl: str, formal: str, source: str) -> dict[str, str]:
    """Build one NL-to-formal alignment record for packaged artifacts."""

    return {"nl": nl, "formal": formal, "source": source}
