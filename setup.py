# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Compatibility setuptools entrypoint.

The packaging metadata lives in `pyproject.toml`. This file remains only so
older workflows that invoke `setup.py` directly still delegate into the same
setuptools configuration instead of forking a second metadata source.
"""

from setuptools import setup


setup()
