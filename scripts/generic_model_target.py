# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Generic OpenAI-compatible target adapter for ABW benchmark runs.

The benchmark runner invokes target commands with one public ABW request on
stdin. This adapter turns that request into a compact prompt, calls an
OpenAI-compatible chat-completions endpoint, and emits the benchmark-compatible
JSON response on stdout.

Configuration is intentionally neutral and disclosure-friendly:

- `ABW_MODEL_API_KEY`
- `ABW_MODEL_BASE_URL`
- `ABW_MODEL_ID`
- `ABW_MODEL_MAX_TOKENS`
- `ABW_MODEL_TIMEOUT_SECONDS`
- `ABW_MODEL_TEMPERATURE`
- `ABW_MODEL_API_KEY_HEADER`
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib import error, parse, request


DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_TEMPERATURE = 0.0
DEFAULT_API_KEY_HEADER = "Authorization"


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def _chat_completions_endpoint(base_url: str) -> str:
    stripped = base_url.strip()
    parsed = parse.urlparse(stripped)
    if parsed.path.rstrip("/").endswith("/chat/completions"):
        return stripped
    return stripped.rstrip("/") + "/chat/completions"


def _public_artifact_text(payload: Mapping[str, Any]) -> str:
    artifacts = payload.get("public_artifacts", {})
    if not isinstance(artifacts, Mapping):
        raise ValueError("Benchmark request is missing `public_artifacts`.")
    formal = artifacts.get("formal", {})
    nl = artifacts.get("nl", {})
    if not isinstance(formal, Mapping) or not isinstance(nl, Mapping):
        raise ValueError("Benchmark request public artifacts must include `formal` and `nl` objects.")

    sections = [
        ("signature.json", formal.get("signature")),
        ("axioms.abw", formal.get("axioms")),
        ("visible_facts.abw", formal.get("visible_facts")),
        ("visible_theorems.abw", formal.get("visible_theorems")),
        ("targets_visible.abw", formal.get("targets_visible")),
        ("problem.md", nl.get("problem")),
        ("examples.md", nl.get("examples")),
        ("theorem_cards.md", nl.get("theorem_cards")),
    ]
    rendered: list[str] = []
    for label, path in sections:
        if not isinstance(path, str) or not path:
            raise ValueError(f"Benchmark request is missing public artifact path `{label}`.")
        rendered.extend([f"## {label}", _read_text(path), ""])
    return "\n".join(rendered).strip()


def build_prompt(payload: Mapping[str, Any]) -> str:
    """Build a model prompt from public ABW artifacts only."""

    family = str(payload.get("family", "unknown"))
    world_id = str(payload.get("world_id", "unknown"))
    return f"""You are evaluating an Axiomatic Bridge Worlds task.

World id: {world_id}
Family: {family}

Read the public formal and natural-language artifacts below. Propose one useful
ABW bridge candidate for this world.

Return only ABW DSL candidate text. Do not include Markdown fences, JSON,
commentary, explanations, or hidden/private artifact guesses.

Valid candidate statement forms include `define`, `lemma`, `theorem`, and
`morphism`. Use only public symbols from the signature and public artifacts.

{_public_artifact_text(payload)}
""".strip()


def build_chat_request(prompt: str, *, model: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    """Build one OpenAI-compatible chat-completions request body."""

    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You generate ABW DSL bridge candidates for benchmark evaluation.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def _auth_headers(api_key: str, api_key_header: str) -> dict[str, str]:
    if api_key_header.lower() == "authorization":
        return {"Authorization": f"Bearer {api_key}"}
    return {api_key_header: api_key}


def call_chat_completions(
    *,
    base_url: str,
    api_key: str,
    api_key_header: str,
    request_body: Mapping[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Call an OpenAI-compatible chat-completions endpoint."""

    http_request = request.Request(
        _chat_completions_endpoint(base_url),
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json", **_auth_headers(api_key, api_key_header)},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model API returned HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Model API request failed: {exc.reason}") from exc


def extract_candidate_text(response_payload: Mapping[str, Any]) -> str:
    """Extract ABW candidate text from a chat-completions response."""

    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Model response did not include a non-empty `choices` list.")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("Model response choice must be an object.")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Model response choice did not include a message object.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model response did not include non-empty message content.")
    return _normalize_candidate_text(content)


def _normalize_candidate_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(decoded, dict) and isinstance(decoded.get("candidate"), str):
        return decoded["candidate"].strip()
    if isinstance(decoded, str):
        return decoded.strip()
    return stripped


def _env_or_arg(value: str | None, name: str, default: str | None = None) -> str | None:
    if value is not None:
        return value
    return os.environ.get(name, default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one ABW request against a generic model API.")
    parser.add_argument("--api-key")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--api-key-header")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    api_key = _env_or_arg(args.api_key, "ABW_MODEL_API_KEY")
    model = _env_or_arg(args.model, "ABW_MODEL_ID")
    if not api_key:
        print("Missing ABW_MODEL_API_KEY or --api-key.", file=sys.stderr)
        return 2
    if not model:
        print("Missing ABW_MODEL_ID or --model.", file=sys.stderr)
        return 2

    base_url = _env_or_arg(args.base_url, "ABW_MODEL_BASE_URL")
    if not base_url:
        print("Missing ABW_MODEL_BASE_URL or --base-url.", file=sys.stderr)
        return 2
    max_tokens = args.max_tokens or int(os.environ.get("ABW_MODEL_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    timeout_seconds = args.timeout_seconds or float(
        os.environ.get("ABW_MODEL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    )
    temperature = args.temperature
    if temperature is None:
        temperature = float(os.environ.get("ABW_MODEL_TEMPERATURE", DEFAULT_TEMPERATURE))
    api_key_header = _env_or_arg(args.api_key_header, "ABW_MODEL_API_KEY_HEADER", DEFAULT_API_KEY_HEADER)
    assert base_url is not None
    assert api_key_header is not None

    payload = json.load(sys.stdin)
    try:
        prompt = build_prompt(payload)
        request_body = build_chat_request(
            prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        response_payload = call_chat_completions(
            base_url=base_url,
            api_key=api_key,
            api_key_header=api_key_header,
            request_body=request_body,
            timeout_seconds=timeout_seconds,
        )
        candidate = extract_candidate_text(response_payload)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    json.dump(
        {
            "candidate": candidate,
            "metadata": {
                "adapter": "generic_openai_compatible",
                "model": model,
                "base_url": base_url,
                "max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
                "temperature": temperature,
            },
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
