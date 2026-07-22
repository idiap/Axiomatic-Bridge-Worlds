# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

PYTHON ?= python3
UV ?= uv

ROBUSTNESS_PLAN ?= artifacts/abw_robustness/robustness_plan.json
ROBUSTNESS_TARGET_COMMAND ?= --target-command $(UV) --target-command run --target-command python --target-command scripts/example_target_system.py
EXPERIMENT_TARGET_COMMAND ?= --target-command $(UV) --target-command run --target-command python --target-command scripts/example_target_system.py
BUILD_TOOL ?= $(UV) run --with build python -m build
TWINE_CHECK ?= $(UV) run --with twine python -m twine check

.PHONY: setup setup-base setup-test setup-validation test test-validation dist dist-check example dataset paper-core paired-difficulty robustness-plan run-experiment

setup:
	$(UV) sync

setup-base:
	$(UV) sync

setup-test:
	$(UV) sync --extra test

setup-validation:
	$(UV) sync --extra validation

test:
	$(UV) run --extra test pytest

test-validation:
	$(UV) run --extra test --extra validation pytest

dist:
	rm -rf dist build
	$(BUILD_TOOL)

dist-check: dist
	$(TWINE_CHECK) dist/*

example:
	$(UV) run python -m abw_core generate-world --family predicate_invention --seed 7 --output examples/tiny_world

dataset:
	$(UV) run python scripts/install_seeded_v2_dataset.py

paper-core:
	$(UV) run python -m abw_core generate-dataset --config configs/paper_core_seeded_v2.yaml --output dataset/abw-formal-nl-core

paired-difficulty:
	$(UV) run python scripts/build_paired_difficulty_dataset.py --overwrite

robustness-plan:
	$(UV) run python scripts/robustness_plan.py --base-dataset-root dataset/abw-formal-nl-core $(ROBUSTNESS_TARGET_COMMAND) --output $(ROBUSTNESS_PLAN)

run-experiment:
	$(UV) run python scripts/run_experiment.py --dataset-root dataset/abw-formal-nl-core $(EXPERIMENT_TARGET_COMMAND)
