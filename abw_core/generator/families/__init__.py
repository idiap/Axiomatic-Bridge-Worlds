# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Registration surface for the shipped ABW world families.

Importing this package has one important side effect: each family module
registers its generator function with the shared family registry. That makes
dataset generation and single-world generation work from stable paper-core
family names such as `predicate_invention`, `analogy`, or `multi_step`.

Conceptually, this package is the benchmark's family catalog. It does not build
worlds itself; it ensures the available world styles are imported and known to
the runtime.
"""

from . import (  # noqa: F401
    analogy,
    invariant,
    lemma_invention,
    multi_step,
    normal_form,
    predicate_invention,
    quotient,
)
