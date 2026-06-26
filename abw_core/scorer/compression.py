# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Compression-style utility metrics for ABW candidate bridges."""

from __future__ import annotations


def compression_score(baseline_costs: list[int], candidate_costs: list[int], candidate_size: int) -> float:
    """Reward candidates that save proof cost without growing too large."""

    baseline_total = sum(baseline_costs)
    candidate_total = sum(candidate_costs)
    denominator = baseline_total + candidate_size
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, (baseline_total - candidate_total) / denominator))
