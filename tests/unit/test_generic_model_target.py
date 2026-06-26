# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Tests for the disclosure-friendly generic model target adapter."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generic_model_target.py"
SPEC = importlib.util.spec_from_file_location("generic_model_target", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
generic_model_target = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generic_model_target)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _artifact(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_generic_model_target_calls_openai_compatible_api(monkeypatch, tmp_path: Path) -> None:
    payload = {
        "world_id": "abw_test_0000",
        "family": "predicate_invention",
        "public_artifacts": {
            "formal": {
                "signature": _artifact(tmp_path / "formal" / "signature.json", '{"sorts": []}'),
                "axioms": _artifact(tmp_path / "formal" / "axioms.abw", "axiom step: A(x) -> B(x)"),
                "visible_facts": _artifact(tmp_path / "formal" / "visible_facts.abw", "fact a: A(c)"),
                "visible_theorems": _artifact(tmp_path / "formal" / "visible_theorems.abw", ""),
                "targets_visible": _artifact(tmp_path / "formal" / "targets_visible.abw", "goal g: B(c)"),
            },
            "nl": {
                "problem": _artifact(tmp_path / "nl" / "problem.md", "Find the bridge."),
                "examples": _artifact(tmp_path / "nl" / "examples.md", "No solved examples."),
                "theorem_cards": _artifact(tmp_path / "nl" / "theorem_cards.md", "Visible theorem cards."),
            },
        },
    }
    seen: dict[str, Any] = {}

    def fake_urlopen(http_request, timeout: float):  # noqa: ANN001
        seen["url"] = http_request.full_url
        seen["headers"] = dict(http_request.headers)
        seen["body"] = json.loads(http_request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "```abw\n"
                            "define Cand(x:S0) := A(x)\n"
                            "lemma cand_step: forall x:S0. Cand(x) -> B(x)\n"
                            "```"
                        }
                    }
                ]
            }
        )

    monkeypatch.setenv("ABW_MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("ABW_MODEL_BASE_URL", "https://models.example/v1")
    monkeypatch.setenv("ABW_MODEL_ID", "example-model")
    monkeypatch.setenv("ABW_MODEL_MAX_TOKENS", "77")
    monkeypatch.setenv("ABW_MODEL_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr(generic_model_target.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    assert generic_model_target.main([]) == 0

    response = json.loads(stdout.getvalue())
    assert response["candidate"].startswith("define Cand")
    assert response["metadata"]["adapter"] == "generic_openai_compatible"
    assert response["metadata"]["model"] == "example-model"
    assert "secret-key" not in stdout.getvalue()
    assert seen["url"] == "https://models.example/v1/chat/completions"
    assert seen["timeout"] == 12.0
    assert seen["body"]["model"] == "example-model"
    assert seen["body"]["max_tokens"] == 77
    assert "Find the bridge." in seen["body"]["messages"][1]["content"]
    assert "hidden_bridge" not in seen["body"]["messages"][1]["content"]
