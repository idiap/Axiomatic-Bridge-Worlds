# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

PYTHON ?= python3
UV ?= uv

BENCHMARK_REPORT ?= artifacts/abw_benchmark_report.json
BENCHMARK_REPORT_TEX ?= artifacts/abw_benchmark_report.tex
BENCHMARK_REPORT_PDF ?= artifacts/abw_benchmark_report.pdf
BENCHMARK_REPORT_ARGS ?= --report $(BENCHMARK_REPORT)
ROBUSTNESS_PLAN ?= artifacts/abw_robustness/robustness_plan.json
ROBUSTNESS_TARGET_COMMAND ?= --target-command $(UV) --target-command run --target-command python --target-command scripts/example_target_system.py
EXPERIMENT_TARGET_COMMAND ?= --target-command $(UV) --target-command run --target-command python --target-command scripts/example_target_system.py
BUILD_TOOL ?= $(UV) run --with build python -m build
TWINE_CHECK ?= $(UV) run --with twine python -m twine check

.PHONY: setup setup-base setup-test setup-validation test test-validation dist dist-check example dataset paper-core paired-difficulty robustness-plan run-experiment benchmark-report benchmark-report-fragment benchmark-report-pdf

setup:
	$(UV) sync --all-extras

setup-base:
	$(UV) sync

setup-test:
	$(UV) sync --extra test

setup-validation:
	$(UV) sync --extra validation

test:
	$(UV) run --all-extras pytest

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
	$(UV) run python -m abw_core generate-dataset --config configs/mvp.yaml --output datasets/mvp

paper-core:
	$(UV) run python scripts/generate_dataset.py --config configs/paper_core.yaml --output datasets/paper_core

paired-difficulty:
	$(UV) run python scripts/build_paired_difficulty_dataset.py --all-families --examples-per-family 1 --output datasets/paired_difficulty_shapes --overwrite

robustness-plan:
	$(UV) run python scripts/robustness_plan.py --base-dataset-root datasets/paper_core $(ROBUSTNESS_TARGET_COMMAND) --output $(ROBUSTNESS_PLAN)

run-experiment:
	$(UV) run python scripts/run_experiment.py --skip-generation --dataset-root datasets/paper_core $(EXPERIMENT_TARGET_COMMAND)

benchmark-report:
	$(UV) run python scripts/render_benchmark_report.py $(BENCHMARK_REPORT_ARGS) --output $(BENCHMARK_REPORT_TEX)

benchmark-report-fragment:
	$(UV) run python scripts/render_benchmark_report.py $(BENCHMARK_REPORT_ARGS) --output $(BENCHMARK_REPORT_TEX) --fragment

benchmark-report-pdf:
	$(UV) run python scripts/render_benchmark_report.py $(BENCHMARK_REPORT_ARGS) --output $(BENCHMARK_REPORT_TEX) --pdf-output $(BENCHMARK_REPORT_PDF)
