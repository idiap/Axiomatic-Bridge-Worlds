# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Leakage detection for ABW public NL outputs."""

from __future__ import annotations

import re


def detect_hidden_name_leaks(public_texts: dict[str, str], hidden_names: set[str]) -> list[dict[str, str]]:
    """Report hidden bridge names that accidentally appear in public NL text."""

    findings: list[dict[str, str]] = []
    for hidden_name in hidden_names:
        pattern = re.compile(rf"\b{re.escape(hidden_name)}\b", re.IGNORECASE)
        for path, text in public_texts.items():
            if pattern.search(text):
                findings.append({"path": path, "hidden_name": hidden_name})
    return findings
