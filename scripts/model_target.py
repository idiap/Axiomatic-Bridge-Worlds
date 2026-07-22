# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Model-agnostic adapter for ABW direct and cross-track evaluations.

The benchmark harness sends one public ABW request on stdin. This adapter reads
the artifact view selected by the prompt condition, asks the configured model
for a bridge, and emits the benchmark-compatible JSON response on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib import parse
from urllib import error, request


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from abw_core.dsl import parse_document
from abw_core.nl.controlled_candidate import (
    CONTROLLED_NL_OUTPUT_CONTRACT,
    INVALID_CONVERSION_CANDIDATE,
    CandidateVocabulary,
    convert_controlled_nl,
)


WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_ENV_FILES = (WORKSPACE_ROOT / ".env", REPO_ROOT / ".env")
DEFAULT_MODEL: str | None = None
DEFAULT_BASE_URL: str | None = None
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_TEMPERATURE = 0.0
DEFAULT_RETRIES = 2
ZERO_SHOT_CONDITION = "zero_shot_formal_direct"
FEW_SHOT_CONDITION = "few_shot_formal_direct"
FAMILY_FEW_SHOT_CONDITION = "family_few_shot_formal_direct"
NATURAL_LANGUAGE_DIRECT_CONDITION = "zero_shot_natural_language_direct"
FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION = "few_shot_natural_language_direct"
FAMILY_FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION = "family_few_shot_natural_language_direct"
CROSS_TRACK_NL_TO_FORMAL_CONDITION = "zero_shot_cross_track_nl_to_formal"
FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION = "few_shot_cross_track_nl_to_formal"
FAMILY_FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION = "family_few_shot_cross_track_nl_to_formal"
SUPPORTED_PROMPT_CONDITIONS = (
    ZERO_SHOT_CONDITION,
    FEW_SHOT_CONDITION,
    FAMILY_FEW_SHOT_CONDITION,
    NATURAL_LANGUAGE_DIRECT_CONDITION,
    FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
    FAMILY_FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
    CROSS_TRACK_NL_TO_FORMAL_CONDITION,
    FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION,
    FAMILY_FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION,
)
NATURAL_LANGUAGE_DIRECT_CONDITIONS = {
    NATURAL_LANGUAGE_DIRECT_CONDITION,
    FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
    FAMILY_FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
}
FORMAL_EXEMPLAR_CONDITIONS = {FEW_SHOT_CONDITION, FAMILY_FEW_SHOT_CONDITION}
NLD_EXEMPLAR_CONDITIONS = {
    FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
    FAMILY_FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
}
CT_EXEMPLAR_CONDITIONS = {
    FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION,
    FAMILY_FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION,
}
FORBIDDEN_EXEMPLAR_KEYS = ("private", "hidden", "gold", "secret", "answer_key")
FAMILY_OUTPUT_GUIDANCE = {
    "analogy": (
        "This family requires a morphism candidate. Your answer must start with "
        "`morphism Guess : Left -> Right {` and then list symbol mappings like `L0 -> R0`, one per line. "
        "Inside the braces every line must use `->`; never use `:` or `:=` inside the morphism body. "
        "Include sort, constant, function, and predicate mappings when they appear in the theories. "
        "Do not use define, lemma, theorem, forall, Unicode math, or prose for analogy items."
    ),
    "predicate_invention": (
        "This family expects one `define Name(args) := atom & atom` clause plus useful `lemma` clauses. "
        "If the reusable bridge supports multiple consequences, write one lemma per single-atom conclusion."
    ),
    "lemma_invention": "This family expects one or more `lemma name: forall ...` clauses and no new predicate definition.",
    "invariant": (
        "This family expects one `define` clause naming the invariant plus one `lemma` preservation rule."
    ),
    "quotient": (
        "This family expects quotient-style `define` clauses plus transfer `lemma` clauses. "
        "Only state transfer lemmas that are directly supported by the public rules."
    ),
    "normal_form": (
        "This family expects a normal-form-style `define` clause plus a `lemma` about normalized terms. "
        "Use a neutral invented predicate name rather than a descriptive task word."
    ),
    "multi_step": (
        "This family expects a short ladder of `define` and `lemma` statements. "
        "Use separate lemmas for separate conclusions."
    ),
}
ABW_STATEMENT_PREFIXES = ("define ", "lemma ", "theorem ", "morphism ", "schema ")
ABW_DSL_SYNTAX_GUIDE = """## ABW DSL syntax contract
Use this exact surface syntax in the final answer:
- Definition: define Name(x:S0, y:S1) := Atom(x) & Relation(x,y)
- Lemma: lemma name: forall x:S0 y:S1. Premise(x,y) -> Conclusion(x,y)
- Theorem: theorem name: forall x:S0. Premise(x) -> Conclusion(x)
- Equality atom: term1 = term2
- Morphism:
  morphism Guess : Left -> Right {
    source_symbol -> target_symbol
  }

Quantifier rules:
- Put all quantified variables after one forall and before one dot.
- Correct: forall x:S0 y:S1. R(x,y) -> R(f0(x), f1(y))
- Incorrect: forall x:S0, forall y:S1, R(x,y) -> ...
- Incorrect: forall x:S0 -> Goal(x)

Final-answer rules:
- Every lemma or theorem must contain a colon before the formula.
- Every quantified lemma or theorem must contain a dot after the typed variables.
- A lemma/theorem conclusion after `->` must be exactly one atom. If you need several conclusions, write several lemmas.
- Do not output placeholders, comments, bullets, Markdown fences, JSON, or prose.
- Use only symbols listed in the public ABW output vocabulary."""

NL_DIRECT_VALIDITY_GUIDE = """## Natural-Language Direct validity controls
- Use one shared prompt for all models; do not rely on model-specific instructions.
- Use neutral invented bridge names with a `Cand` prefix, such as CandBridge, CandInv, CandQuot, CandNF, or CandStep.
- Do not name invented predicates after semantic task words from the prose. This avoids accidentally reproducing private bridge labels.
- Prefer a smaller sound candidate over a larger speculative candidate.
- Only assert a lemma if its conclusion follows from the public rules, examples, and theorem cards.
- If a candidate has a useful definition but you are unsure about a transfer/preservation rule, output the safest directly supported lemma rather than a broad one."""

NLD_FAMILY_OUTPUT_GUIDANCE = {
    "analogy": "Return exactly one Mapping block pairing every visible source-theory symbol with its target-theory counterpart.",
    "predicate_invention": "Return one Definition block and one or more useful Lemma blocks.",
    "lemma_invention": "Return one or more Lemma blocks and no Definition block.",
    "invariant": "Return one Definition block naming the invariant and one Lemma block describing its preservation.",
    "quotient": "Return the smallest useful set of Definition and Lemma blocks for equivalence and representative behavior.",
    "normal_form": "Return one Definition block for the normal condition and one supported Lemma block.",
    "multi_step": "Return the short ladder of Definition and Lemma blocks needed for the reusable construction.",
}


class MissingFinalAnswerError(ValueError):
    """The provider completed generation without emitting final-answer text."""


def _parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse one simple dotenv assignment without exposing secret values."""

    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip().strip("'\"")
    return key, value


def load_env_files(paths: tuple[Path, ...] = DEFAULT_ENV_FILES) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from env files in priority order."""

    loaded: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            if key not in loaded and value:
                loaded[key] = value
    return loaded


def resolve_setting(
    name: str,
    *,
    env_file_values: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
    default: str | None = None,
) -> str | None:
    """Resolve one setting from the process environment, then repo env files."""

    env_file_values = env_file_values if env_file_values is not None else load_env_files()
    environ = environ if environ is not None else os.environ
    value = environ.get(name)
    if value:
        return value
    value = env_file_values.get(name)
    if value:
        return value
    return default


def _read_text_artifact(path: str) -> str:
    artifact = Path(path)
    return artifact.read_text(encoding="utf-8")


def _read_json_artifact(path: str) -> Any:
    artifact = Path(path)
    return json.loads(artifact.read_text(encoding="utf-8"))


def _render_public_signature_glossary(signature_path: str) -> str:
    """Render only public vocabulary needed to write scoreable ABW DSL."""

    signature = _read_json_artifact(signature_path)
    lines = [
        "## public ABW output vocabulary",
        "Use only these public formal symbols when writing your final ABW DSL candidate.",
    ]
    for label in ("sorts", "constants", "functions", "predicates"):
        rows = signature.get(label, [])
        if not rows:
            continue
        lines.append(f"{label}:")
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            name = row.get("name")
            if not isinstance(name, str):
                continue
            if label == "constants":
                lines.append(f"- {name}: {row.get('sort', '?')}")
            elif label == "functions":
                inputs = ", ".join(str(item) for item in row.get("input_sorts", []))
                lines.append(f"- {name}({inputs}) -> {row.get('output_sort', '?')}")
            elif label == "predicates":
                inputs = ", ".join(str(item) for item in row.get("input_sorts", []))
                lines.append(f"- {name}({inputs})")
            else:
                lines.append(f"- {name}")
    return "\n".join(lines)


def _find_forbidden_exemplar_keys(value: Any, *, path: str = "$") -> list[str]:
    """Return forbidden key paths in a few-shot exemplar payload."""

    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            key_path = f"{path}.{key_text}"
            lowered = key_text.lower()
            if any(token in lowered for token in FORBIDDEN_EXEMPLAR_KEYS):
                findings.append(key_path)
            findings.extend(_find_forbidden_exemplar_keys(child, path=key_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_exemplar_keys(child, path=f"{path}[{index}]"))
    return findings


def load_exemplar_bank(path: str | Path) -> dict[str, Any]:
    """Load and validate a public-only few-shot exemplar bank.

    The bank is intentionally conservative: examples must be rendered public
    prompt fragments plus candidate text. Private/gold/hidden keys are rejected
    before a prompt can be built.
    """

    bank_path = Path(path)
    payload = json.loads(bank_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Few-shot exemplar bank must be a JSON object.")
    forbidden = _find_forbidden_exemplar_keys(payload)
    if forbidden:
        raise ValueError("Few-shot exemplar bank contains forbidden private fields: " + ", ".join(forbidden))
    exemplars = payload.get("exemplars")
    if not isinstance(exemplars, list) or not exemplars:
        raise ValueError("Few-shot exemplar bank must include a non-empty `exemplars` list.")
    for index, exemplar in enumerate(exemplars):
        if not isinstance(exemplar, dict):
            raise ValueError(f"Few-shot exemplar at index {index} must be a JSON object.")
        for key in ("id", "family", "candidate"):
            if not isinstance(exemplar.get(key), str) or not str(exemplar[key]).strip():
                raise ValueError(f"Few-shot exemplar at index {index} is missing non-empty `{key}`.")
        has_formal_view = isinstance(exemplar.get("public_formal_view"), str) and str(exemplar["public_formal_view"]).strip()
        has_nl_view = isinstance(exemplar.get("public_nl_view"), str) and str(exemplar["public_nl_view"]).strip()
        if not has_formal_view and not has_nl_view:
            raise ValueError(
                f"Few-shot exemplar at index {index} must include `public_formal_view` or `public_nl_view`."
            )
    return payload


def render_few_shot_exemplars(
    exemplar_bank: Mapping[str, Any],
    *,
    view_key: str = "public_formal_view",
    output_representation: str = "abw_dsl",
    family: str | None = None,
    expected_count: int | None = None,
) -> str:
    """Render public-only few-shot exemplars for insertion into a prompt."""

    exemplars = exemplar_bank.get("exemplars")
    if not isinstance(exemplars, list) or not exemplars:
        raise ValueError("Few-shot prompt condition requires at least one exemplar.")
    selected = [
        exemplar
        for exemplar in exemplars
        if isinstance(exemplar, Mapping) and (family is None or exemplar.get("family") == family)
    ]
    if not selected:
        raise ValueError(f"Exemplar bank has no public exemplar for family `{family}`.")
    if expected_count is not None and len(selected) != expected_count:
        raise ValueError(
            f"Prompt requires exactly {expected_count} exemplar(s) for family `{family}`; found {len(selected)}."
        )
    if output_representation == "controlled_natural_language":
        output_description = "They show the required controlled natural-language bridge shape."
        candidate_label = "controlled natural-language bridge:"
    else:
        output_description = "They show the required ABW DSL output shape."
        candidate_label = "candidate:"
    lines = [
        "## solved public exemplars",
        "The following examples are from a disjoint public-only exemplar bank.",
        output_description + " Do not copy labels unless they also appear in the target world.",
        "",
    ]
    for index, exemplar in enumerate(selected, start=1):
        assert isinstance(exemplar, Mapping)
        public_view = exemplar.get(view_key)
        if not isinstance(public_view, str) or not public_view.strip():
            raise ValueError(f"Few-shot exemplar {exemplar.get('id', index)} is missing `{view_key}`.")
        lines.extend(
            [
                f"### exemplar {index}: {exemplar['id']} ({exemplar['family']})",
                "public view:",
                public_view.strip(),
                candidate_label,
                str(exemplar["candidate"]).strip(),
                "",
            ]
        )
    return "\n".join(lines).strip()


def _theory_symbol_lines(theory: Any) -> list[str]:
    """Describe one public theory's symbol inventory for prompt guidance."""

    lines = [f"Theory {theory.name} public symbols:"]
    if theory.document.sorts:
        lines.append("  sorts: " + ", ".join(sort.name for sort in theory.document.sorts))
    if theory.document.constants:
        lines.append(
            "  constants: "
            + ", ".join(f"{constant.name}:{constant.sort}" for constant in theory.document.constants)
        )
    if theory.document.functions:
        lines.append(
            "  functions: "
            + ", ".join(
                f"{function.name}:{','.join(function.input_sorts)}->{function.output_sort}"
                for function in theory.document.functions
            )
        )
    if theory.document.predicates:
        lines.append(
            "  predicates: "
            + ", ".join(
                f"{predicate.name}:{','.join(predicate.input_sorts)}" for predicate in theory.document.predicates
            )
        )
    return lines


def build_public_symbol_hint(payload: Mapping[str, Any]) -> str:
    """Build optional public-only symbol guidance for syntax-constrained families."""

    if payload.get("family") != "analogy":
        return ""
    axioms_text = _read_text_artifact(str(payload["public_artifacts"]["formal"]["axioms"]))
    try:
        document = parse_document(axioms_text)
    except Exception:  # noqa: BLE001
        return ""
    if len(document.theories) < 2:
        return ""
    source, target = document.theories[0], document.theories[1]
    lines = [
        "## public symbol mapping guidance",
        *_theory_symbol_lines(source),
        *_theory_symbol_lines(target),
        (
            f"Write exactly one morphism from {source.name} to {target.name}. "
            "Map each source sort, constant, function, and predicate to a target symbol of the same kind and compatible type."
        ),
        "Use this syntax only:",
        f"morphism Guess : {source.name} -> {target.name} {{",
        "  source_symbol -> target_symbol",
        "}",
    ]
    return "\n".join(lines)


def build_formal_direct_prompt(
    payload: Mapping[str, Any],
    *,
    prompt_condition: str = ZERO_SHOT_CONDITION,
    exemplar_bank: Mapping[str, Any] | None = None,
) -> str:
    """Build a benchmark prompt for one supported direct condition."""

    if prompt_condition not in SUPPORTED_PROMPT_CONDITIONS:
        raise ValueError(f"Unsupported prompt condition: {prompt_condition}.")
    if prompt_condition in FORMAL_EXEMPLAR_CONDITIONS and exemplar_bank is None:
        raise ValueError("Exemplar-conditioned Formal Direct requires an exemplar bank.")
    if prompt_condition in {
        CROSS_TRACK_NL_TO_FORMAL_CONDITION,
        FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION,
        FAMILY_FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION,
    }:
        return build_cross_track_nl_to_formal_prompt(
            payload,
            prompt_condition=prompt_condition,
            exemplar_bank=exemplar_bank,
        )
    if prompt_condition in {
        NATURAL_LANGUAGE_DIRECT_CONDITION,
        FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
        FAMILY_FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION,
    }:
        return build_natural_language_direct_prompt(
            payload,
            prompt_condition=prompt_condition,
            exemplar_bank=exemplar_bank,
        )

    formal = payload["public_artifacts"]["formal"]
    symbol_hint = build_public_symbol_hint(payload)
    sections = [
        "# ABW Formal Direct Task",
        f"Prompt condition: {prompt_condition}",
        f"World ID: {payload['world_id']}",
        f"Family: {payload['family']}",
        "",
        "You are given only the formal public view of an Axiomatic Bridge World.",
        "Invent a candidate bridge that is well-typed, non-trivial, and useful for hidden downstream goals.",
        FAMILY_OUTPUT_GUIDANCE.get(str(payload["family"]), "Return the bridge in valid ABW DSL."),
        "Return only ABW candidate bridge text. Do not use Markdown fences, prose, or JSON.",
        "Use ASCII ABW syntax only: forall, ->, &, :=. Never use ∀, →, or explanatory paragraphs.",
        "The first non-whitespace character of your answer must start an ABW statement such as define, lemma, theorem, morphism, or schema.",
        "",
    ]
    if prompt_condition in FORMAL_EXEMPLAR_CONDITIONS:
        assert exemplar_bank is not None
        family_specific = prompt_condition == FAMILY_FEW_SHOT_CONDITION
        exemplar_family = str(payload["family"]) if family_specific else None
        sections.extend(
            [
                render_few_shot_exemplars(
                    exemplar_bank,
                    view_key="public_formal_view",
                    family=exemplar_family,
                    expected_count=2 if family_specific else None,
                ),
                "",
            ]
        )
    if symbol_hint:
        sections.extend([symbol_hint, ""])
    for label in ("signature", "axioms", "visible_facts", "visible_theorems", "targets_visible"):
        sections.extend(
            [
                f"## {label}",
                _read_text_artifact(str(formal[label])).strip(),
                "",
            ]
        )
    return "\n".join(sections).strip() + "\n"


def build_cross_track_nl_to_formal_prompt(
    payload: Mapping[str, Any],
    *,
    prompt_condition: str = CROSS_TRACK_NL_TO_FORMAL_CONDITION,
    exemplar_bank: Mapping[str, Any] | None = None,
) -> str:
    """Build the executable Cross-Track prompt for NL input and formal output."""

    formal = payload["public_artifacts"]["formal"]
    nl = payload["public_artifacts"]["nl"]
    symbol_hint = build_public_symbol_hint(payload)
    sections = [
        "# ABW Cross-Track NL-to-Formal Task",
        f"Prompt condition: {prompt_condition}",
        f"World ID: {payload['world_id']}",
        f"Family: {payload['family']}",
        "",
        "Infer a bridge from the public natural-language view, then express it as formal ABW DSL.",
        "Return only ABW candidate bridge text. Do not use Markdown fences, prose, or JSON.",
        "Use ASCII ABW syntax only: forall, ->, &, :=. Never use Unicode math or explanatory paragraphs.",
        FAMILY_OUTPUT_GUIDANCE.get(str(payload["family"]), "Return the bridge in valid ABW DSL."),
        "",
        _render_public_signature_glossary(str(formal["signature"])),
        "",
        ABW_DSL_SYNTAX_GUIDE,
        "",
        NL_DIRECT_VALIDITY_GUIDE,
        "",
    ]
    if prompt_condition in CT_EXEMPLAR_CONDITIONS:
        if exemplar_bank is None:
            raise ValueError("Exemplar-conditioned Cross-Track NL-to-formal requires an exemplar bank.")
        if exemplar_bank.get("output_representation") != "abw_dsl":
            raise ValueError("Cross-Track NL-to-formal requires ABW DSL exemplar outputs.")
        exemplar_family = (
            str(payload["family"])
            if prompt_condition == FAMILY_FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION
            else None
        )
        sections.extend(
            [
                render_few_shot_exemplars(
                    exemplar_bank,
                    view_key="public_nl_view",
                    family=exemplar_family,
                    expected_count=(
                        2
                        if prompt_condition == FAMILY_FEW_SHOT_CROSS_TRACK_NL_TO_FORMAL_CONDITION
                        else None
                    ),
                ),
                "",
            ]
        )
    if symbol_hint:
        sections.extend([symbol_hint, ""])
    for label in ("problem", "examples", "theorem_cards"):
        sections.extend(
            [
                f"## public_nl_{label}",
                _read_text_artifact(str(nl[label])).strip(),
                "",
            ]
        )
    return "\n".join(sections).strip() + "\n"


def build_natural_language_direct_prompt(
    payload: Mapping[str, Any],
    *,
    prompt_condition: str = NATURAL_LANGUAGE_DIRECT_CONDITION,
    exemplar_bank: Mapping[str, Any] | None = None,
) -> str:
    """Build true Natural-Language Direct: public NL input and controlled-NL output."""

    nl = payload["public_artifacts"]["nl"]
    sections = [
        "# ABW Natural-Language Direct Task",
        f"Prompt condition: {prompt_condition}",
        f"World ID: {payload['world_id']}",
        f"Family: {payload['family']}",
        "",
        "You are given only the public natural-language view of an Axiomatic Bridge World.",
        "Invent a reusable bridge concept that is useful for hidden downstream goals.",
        NLD_FAMILY_OUTPUT_GUIDANCE.get(
            str(payload["family"]),
            "Return supported Definition and Lemma blocks in the controlled natural language.",
        ),
        "Your response is converted deterministically after generation. The converter performs no repair or inference.",
        "",
        CONTROLLED_NL_OUTPUT_CONTRACT,
        "",
    ]
    if prompt_condition in NLD_EXEMPLAR_CONDITIONS:
        if exemplar_bank is None:
            raise ValueError("Exemplar-conditioned Natural-Language Direct requires an exemplar bank.")
        if exemplar_bank.get("output_representation") != "controlled_natural_language":
            raise ValueError("Natural-Language Direct requires controlled-NL exemplar outputs.")
        exemplar_family = (
            str(payload["family"])
            if prompt_condition == FAMILY_FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION
            else None
        )
        sections.extend(
            [
                render_few_shot_exemplars(
                    exemplar_bank,
                    view_key="public_nl_view",
                    output_representation="controlled_natural_language",
                    family=exemplar_family,
                    expected_count=(
                        2
                        if prompt_condition == FAMILY_FEW_SHOT_NATURAL_LANGUAGE_DIRECT_CONDITION
                        else None
                    ),
                ),
                "",
            ]
        )
    for label in ("problem", "examples", "theorem_cards"):
        sections.extend(
            [
                f"## public_nl_{label}",
                _read_text_artifact(str(nl[label])).strip(),
                "",
            ]
        )
    return "\n".join(sections).strip() + "\n"


def normalize_base_url(base_url: str) -> str:
    """Normalize a provider URL into an OpenAI-compatible API base URL."""

    parsed = parse.urlparse(base_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return base_url.rstrip("/")
    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/v1"
    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return parse.urlunparse(normalized).rstrip("/")


def _chat_endpoint(base_url: str) -> str:
    parsed = parse.urlparse(base_url.strip())
    if parsed.scheme and parsed.netloc:
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions") or path.endswith("/score") or path.endswith("/api/chat"):
            return base_url.strip()
    return normalize_base_url(base_url).rstrip("/") + "/chat/completions"


def _is_azure_ml_score_endpoint(base_url: str) -> bool:
    return parse.urlparse(base_url.strip()).path.rstrip("/").endswith("/score")


def _is_ollama_endpoint(base_url: str) -> bool:
    parsed = parse.urlparse(base_url.strip())
    host = parsed.hostname or ""
    path = parsed.path.rstrip("/")
    return host in {"localhost", "127.0.0.1", "::1"} and (parsed.port in {None, 11434}) or path.endswith("/api/chat")


def _ollama_chat_endpoint(base_url: str) -> str:
    parsed = parse.urlparse(base_url.strip())
    if parsed.scheme and parsed.netloc:
        path = parsed.path.rstrip("/")
        if path.endswith("/api/chat"):
            return base_url.strip()
        return parse.urlunparse(parsed._replace(path="/api/chat", params="", query="", fragment=""))
    return DEFAULT_OLLAMA_BASE_URL.rstrip("/") + "/api/chat"


def model_output_instruction(prompt_condition: str) -> str:
    """Return the model-facing output instruction for one condition contract."""

    if prompt_condition in NATURAL_LANGUAGE_DIRECT_CONDITIONS:
        return "Return only the controlled natural-language bridge blocks requested by the prompt."
    return "Return only ABW DSL candidate bridge text."


def build_chat_request(
    prompt: str,
    *,
    model: str,
    max_tokens: int | None,
    temperature: float | None,
    output_instruction: str = "Return only ABW DSL candidate bridge text.",
) -> dict[str, Any]:
    """Build an OpenAI-compatible non-streaming chat-completions request."""

    is_deepseek_r1 = str(model).lower().startswith("deepseek-r1")
    user_content = (
        prompt + f"\n\n{output_instruction} Do not explain."
        if is_deepseek_r1
        else prompt
    )
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You generate bridge candidates for benchmark evaluation. " + output_instruction,
            },
            {"role": "user", "content": user_content},
        ],
        "stream": False,
    }
    if is_deepseek_r1:
        body["messages"].append({"role": "assistant", "content": "<think>\n\n</think>\n"})
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    return body


def build_ollama_chat_request(
    prompt: str,
    *,
    model: str,
    max_tokens: int | None,
    temperature: float | None,
    context_tokens: int | None = None,
    output_instruction: str = "Return only ABW DSL candidate bridge text.",
) -> dict[str, Any]:
    """Build a native Ollama non-streaming chat request."""

    options: dict[str, Any] = {}
    if context_tokens is not None:
        options["num_ctx"] = context_tokens
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    if temperature is not None:
        options["temperature"] = temperature
    is_deepseek_r1 = str(model).lower().startswith("deepseek-r1")
    user_content = (
        prompt + f"\n\n{output_instruction} Do not explain."
        if is_deepseek_r1
        else "/no_think\n" + prompt
    )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": "You generate bridge candidates for benchmark evaluation. " + output_instruction,
        },
        {"role": "user", "content": user_content},
    ]
    if is_deepseek_r1:
        messages[0]["content"] += " Do not include reasoning."
        messages.append({"role": "assistant", "content": "<think>\n\n</think>\n"})

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
    }
    if options:
        body["options"] = options
    return body


def build_azure_ml_score_request(
    prompt: str,
    *,
    max_tokens: int | None,
    temperature: float | None,
    output_instruction: str = "Return only ABW DSL candidate bridge text.",
) -> dict[str, Any]:
    """Build an Azure ML managed-endpoint text-generation request."""

    chat_prompt = (
        "<|begin_of_text|>"
        "<|start_header_id|>system<|end_header_id|>\n\n"
        f"You generate bridge candidates for benchmark evaluation. {output_instruction}"
        "<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n"
        f"{prompt}"
        "<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
    )
    parameters: dict[str, Any] = {
        "return_full_text": False,
        "stop": ["<|eot_id|>", "<|end_of_text|>"],
    }
    if max_tokens is not None:
        parameters["max_new_tokens"] = max_tokens
    if temperature is not None:
        parameters["temperature"] = temperature
    return {"input_data": {"input_string": [chat_prompt], "parameters": parameters}}


def call_chat_completion(
    *,
    base_url: str,
    api_key: str | None,
    request_body: Mapping[str, Any],
    timeout_seconds: float,
    retries: int = 0,
    deployment: str | None = None,
    native_ollama: bool = False,
) -> Any:
    """Call an OpenAI-compatible chat-completions endpoint."""

    data = json.dumps(request_body).encode("utf-8")
    attempts = max(1, retries + 1)
    last_url_error: error.URLError | None = None
    endpoint = _ollama_chat_endpoint(base_url) if native_ollama else _chat_endpoint(base_url)
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if deployment:
        headers["azureml-model-deployment"] = deployment
    for _ in range(attempts):
        current_url = endpoint
        try:
            for _redirect in range(4):
                http_request = request.Request(
                    current_url,
                    data=data,
                    headers=headers,
                    method="POST",
                )
                try:
                    with request.urlopen(http_request, timeout=timeout_seconds) as response:
                        return json.loads(response.read().decode("utf-8"))
                except error.HTTPError as exc:
                    if exc.code in {301, 302, 303, 307, 308}:
                        location = exc.headers.get("Location")
                        if location:
                            current_url = parse.urljoin(current_url, location)
                            continue
                    body = exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Internal model API returned HTTP {exc.code}: {body}") from exc
            raise RuntimeError("Internal model API exceeded redirect limit.")
        except error.URLError as exc:
            last_url_error = exc
    assert last_url_error is not None
    raise RuntimeError(f"Internal model API request failed: {last_url_error.reason}") from last_url_error


def extract_candidate_text(response_payload: Any, *, preserve_full_text: bool = False) -> str:
    """Extract candidate bridge text from an OpenAI-compatible response."""

    def clean_candidate(candidate: str) -> str:
        if preserve_full_text:
            return candidate.strip()
        lines = candidate.strip().splitlines()
        if any(line.strip().lower().replace(" ", "_") == "## candidate_bridge" for line in lines):
            for index, line in enumerate(lines):
                if line.strip().lower().replace(" ", "_") == "## candidate_bridge":
                    lines = lines[index + 1 :]
                    break
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(ABW_STATEMENT_PREFIXES):
                lines = lines[index:]
                break
        while lines and lines[-1].lstrip().startswith("## "):
            lines.pop()
        return "\n".join(line for line in lines if not line.lstrip().startswith("## ")).strip()

    if isinstance(response_payload, list):
        texts: list[str] = []
        for item in response_payload:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, Mapping):
                for key in ("generated_text", "text", "output", "0"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        texts.append(value)
                        break
        candidate = "\n".join(text.strip() for text in texts if text.strip()).strip()
        if candidate:
            return clean_candidate(candidate)
        raise ValueError("Model response list did not include generated text.")
    for key in ("generated_text", "text", "output"):
        value = response_payload.get(key)
        if isinstance(value, str) and value.strip():
            return clean_candidate(value)
    choices = response_payload.get("choices")
    message = response_payload.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return clean_candidate(content)
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return clean_candidate(reasoning_content)
        thinking = message.get("thinking")
        if isinstance(thinking, str) and thinking.strip():
            raise MissingFinalAnswerError(
                "Model exhausted generation in the thinking field without a final answer."
            )
    response = response_payload.get("response")
    if isinstance(response, str) and response.strip():
        return clean_candidate(response)
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Model response did not include any choices.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("Model response choice did not include a message object.")
    content = message.get("content")
    reasoning_content = message.get("reasoning_content")
    if isinstance(content, str) and content.strip():
        candidate = content.strip()
    elif isinstance(reasoning_content, str) and reasoning_content.strip():
        candidate = reasoning_content.strip()
    else:
        raise ValueError("Model response message did not include non-empty content.")
    if preserve_full_text:
        return candidate
    if candidate.startswith("`") and candidate.endswith("`"):
        candidate = candidate.strip("`").strip()
        if candidate.startswith("abw\n"):
            candidate = candidate[4:].strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError:
        return candidate
    if isinstance(decoded, dict) and isinstance(decoded.get("candidate"), str):
        return clean_candidate(decoded["candidate"])
    if isinstance(decoded, str):
        return clean_candidate(decoded)
    return clean_candidate(candidate)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one ABW request against a model API.")
    parser.add_argument("--api-key-env", default="ABW_MODEL_API_KEY")
    parser.add_argument("--base-url-env", default="ABW_MODEL_BASE_URL")
    parser.add_argument("--model-env", default="ABW_MODEL_ID")
    parser.add_argument("--max-tokens-env", default="ABW_MODEL_MAX_TOKENS")
    parser.add_argument("--temperature-env", default="ABW_MODEL_TEMPERATURE")
    parser.add_argument("--timeout-env", default="ABW_MODEL_TIMEOUT_SECONDS")
    parser.add_argument("--retries-env", default="ABW_MODEL_RETRIES")
    parser.add_argument("--context-tokens-env", default="ABW_MODEL_CONTEXT_TOKENS")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--context-tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--prompt-condition", choices=SUPPORTED_PROMPT_CONDITIONS, default=ZERO_SHOT_CONDITION)
    parser.add_argument("--exemplar-bank")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_values = load_env_files()
    raw_base_url = args.base_url or resolve_setting(args.base_url_env, env_file_values=env_values) or DEFAULT_BASE_URL
    if not raw_base_url:
        print(f"Missing {args.base_url_env} or --base-url.", file=sys.stderr)
        return 2
    base_url = normalize_base_url(raw_base_url)
    is_ollama = _is_ollama_endpoint(str(base_url))
    api_key = resolve_setting(args.api_key_env, env_file_values=env_values)
    model = args.model or resolve_setting(args.model_env, env_file_values=env_values, default=DEFAULT_MODEL)
    if not model:
        print(f"Missing {args.model_env} or --model.", file=sys.stderr)
        return 2
    raw_max_tokens = resolve_setting(args.max_tokens_env, env_file_values=env_values)
    raw_timeout = resolve_setting(args.timeout_env, env_file_values=env_values)
    raw_temperature = resolve_setting(args.temperature_env, env_file_values=env_values)
    raw_retries = resolve_setting(args.retries_env, env_file_values=env_values)
    raw_context_tokens = resolve_setting(args.context_tokens_env, env_file_values=env_values)
    max_tokens = args.max_tokens if args.max_tokens is not None else int(raw_max_tokens) if raw_max_tokens else None
    context_tokens = (
        args.context_tokens
        if args.context_tokens is not None
        else int(raw_context_tokens)
        if raw_context_tokens
        else None
    )
    temperature = (
        args.temperature
        if args.temperature is not None
        else float(raw_temperature)
        if raw_temperature
        else DEFAULT_TEMPERATURE
    )
    timeout_seconds = (
        args.timeout_seconds if args.timeout_seconds is not None else float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
    )
    retries = int(raw_retries) if raw_retries else DEFAULT_RETRIES

    payload = json.load(sys.stdin)
    exemplar_bank = load_exemplar_bank(args.exemplar_bank) if args.exemplar_bank else None
    prompt = build_formal_direct_prompt(
        payload,
        prompt_condition=args.prompt_condition,
        exemplar_bank=exemplar_bank,
    )
    output_instruction = model_output_instruction(args.prompt_condition)
    is_score_endpoint = _is_azure_ml_score_endpoint(str(base_url))
    request_body = (
        build_azure_ml_score_request(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            output_instruction=output_instruction,
        )
        if is_score_endpoint
        else build_ollama_chat_request(
            prompt,
            model=str(model),
            max_tokens=max_tokens,
            temperature=temperature,
            context_tokens=context_tokens,
            output_instruction=output_instruction,
        )
        if is_ollama
        else build_chat_request(
            prompt,
            model=str(model),
            max_tokens=max_tokens,
            temperature=temperature,
            output_instruction=output_instruction,
        )
    )
    response_issue = None
    try:
        response_payload = call_chat_completion(
            base_url=str(base_url),
            api_key=api_key,
            request_body=request_body,
            timeout_seconds=timeout_seconds,
            retries=retries,
            deployment=str(model) if is_score_endpoint else None,
            native_ollama=is_ollama,
        )
        raw_candidate = extract_candidate_text(
            response_payload,
            preserve_full_text=args.prompt_condition in NATURAL_LANGUAGE_DIRECT_CONDITIONS,
        )
    except MissingFinalAnswerError:
        raw_candidate = INVALID_CONVERSION_CANDIDATE
        response_issue = "missing_final_answer"
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    conversion_metadata = None
    if args.prompt_condition in NATURAL_LANGUAGE_DIRECT_CONDITIONS:
        formal = payload["public_artifacts"]["formal"]
        vocabulary = CandidateVocabulary.from_public_artifacts(formal["signature"], formal["axioms"])
        conversion = convert_controlled_nl(raw_candidate, vocabulary)
        candidate = conversion.candidate_dsl or INVALID_CONVERSION_CANDIDATE
        conversion_metadata = conversion.to_metadata()
    else:
        candidate = raw_candidate

    json.dump(
        {
            "candidate": candidate,
            "metadata": {
                "adapter": (
                    "azure_ml_score"
                    if is_score_endpoint
                    else "ollama_native"
                    if is_ollama
                    else "openai_compatible"
                ),
                "model": model,
                "base_url": base_url,
                "prompt_condition": args.prompt_condition,
                "exemplar_bank": args.exemplar_bank,
                "raw_model_output": raw_candidate,
                "response_issue": response_issue,
                "thinking_length": len(response_payload.get("message", {}).get("thinking", ""))
                if isinstance(response_payload, Mapping)
                and isinstance(response_payload.get("message"), Mapping)
                else 0,
                "conversion": conversion_metadata,
                "usage": response_payload.get("usage") if isinstance(response_payload, Mapping) else None,
                "finish_reason": (
                    response_payload.get("done_reason")
                    or (
                        response_payload.get("choices", [{}])[0].get("finish_reason")
                        if isinstance(response_payload.get("choices"), list)
                        and response_payload.get("choices")
                        else None
                    )
                )
                if isinstance(response_payload, Mapping)
                else None,
            },
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
