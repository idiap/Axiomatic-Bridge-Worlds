# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Deterministic NL rendering for ABW worlds."""

from __future__ import annotations

from dataclasses import dataclass

from abw_core import ir
from abw_core.dsl.printer import format_atom, format_clause, format_definition, format_morphism
from abw_core.nl.align import entry
from abw_core.nl.leakage import detect_hidden_name_leaks
from abw_core.nl.naming import NamingScheme, build_naming


@dataclass(frozen=True)
class RenderedTrack:
    """Bundled public and private NL renderings for one packaged world."""

    problem_md: str
    examples_md: str
    theorem_cards_md: str
    hidden_bridge_private_md: str
    gold_informal_solution_private_md: str
    alignment: list[dict[str, str]]


def _render_term(term: ir.Term, naming: NamingScheme) -> str:
    if isinstance(term, ir.VarTerm):
        return term.variable.name
    if isinstance(term, ir.ConstTerm):
        return naming.constants.get(term.name, term.name)
    if isinstance(term, ir.FuncTerm):
        if len(term.args) == 1:
            return f"the {naming.functions.get(term.name, term.name)} of {_render_term(term.args[0], naming)}"
        rendered = ", ".join(_render_term(argument, naming) for argument in term.args)
        return f"{naming.functions.get(term.name, term.name)}({rendered})"
    raise TypeError(f"Unsupported term type: {type(term)!r}")


def _render_atom(atom: ir.Atom, naming: NamingScheme) -> str:
    if atom.predicate == "=" and len(atom.terms) == 2:
        return f"{_render_term(atom.terms[0], naming)} equals {_render_term(atom.terms[1], naming)}"

    label = naming.predicates.get(atom.predicate, atom.predicate)
    if len(atom.terms) == 1:
        return f"{label} holds of {_render_term(atom.terms[0], naming)}"
    if len(atom.terms) == 2:
        return f"{label} holds between {_render_term(atom.terms[0], naming)} and {_render_term(atom.terms[1], naming)}"
    if not atom.terms:
        return f"{label} holds"
    return f"{label} holds of {', '.join(_render_term(term, naming) for term in atom.terms)}"


def _render_clause(clause: ir.HornClause, naming: NamingScheme) -> str:
    premise_text = " and ".join(_render_atom(atom, naming) for atom in clause.premises)
    conclusion_text = _render_atom(clause.conclusion, naming)
    if clause.premises:
        return f"If {premise_text}, then {conclusion_text}."
    return f"{conclusion_text}."


def _render_goal(goal: ir.Goal, naming: NamingScheme) -> str:
    body = " and ".join(_render_atom(atom, naming) for atom in goal.atoms)
    return f"{goal.name}: {body}."


def _task_lines(world: ir.World) -> list[str]:
    if world.hidden_bridge.mappings:
        return [
            "Infer a structure-preserving mapping between the public theories.",
            "Then use that mapping to transport visible source-theory theorems into the target theory.",
        ]
    if world.hidden_bridge.lemmas and not world.hidden_bridge.definitions:
        return [
            "Invent a reusable shortcut lemma that collapses a repeated proof pattern in the public theory.",
            "Then use it to make deeper hidden targets cheaper to justify under the benchmark's proof budget.",
        ]
    return [
        "Invent a reusable bridge concept that captures a repeated structural pattern in the public facts and theorems.",
        "Then propose a lemma that makes deeper hidden targets cheaper to justify under the benchmark's proof budget.",
    ]


def render_world(world: ir.World) -> RenderedTrack:
    """Render one world into the Markdown artifacts shipped with a package."""

    naming = build_naming(world.signature)
    sort_labels = [naming.sorts[sort.name] for sort in world.signature.sorts]

    problem_lines = [
        "# Problem",
        "",
        f"There are {len(sort_labels)} synthetic object kinds in this world: {', '.join(sort_labels)}.",
        "The names are intentionally neutral so the task depends on structure, not stored background knowledge.",
        "",
        "## Rules",
    ]
    theorem_lines = ["# Theorem Cards", ""]
    examples_lines = ["# Examples", "", "## Visible Facts"]
    alignment: list[dict[str, str]] = []

    for clause in world.axioms:
        sentence = _render_clause(clause, naming)
        problem_lines.append(f"- {sentence}")
        alignment.append(entry(sentence, format_clause(clause), f"axioms.abw:{clause.name}"))

    theorem_lines.append("## Visible Theorems")
    for theorem in world.visible_theorems:
        sentence = _render_clause(theorem, naming)
        theorem_lines.append(f"- **{theorem.name}**: {sentence}")
        alignment.append(entry(sentence, format_clause(theorem), f"visible_theorems.abw:{theorem.name}"))

    for fact in world.visible_facts:
        sentence = _render_atom(fact.atom, naming) + "."
        examples_lines.append(f"- {sentence}")
        alignment.append(entry(sentence, format_atom(fact.atom), f"visible_facts.abw:{fact.name}"))

    examples_lines.append("")
    examples_lines.append("## Visible Targets")
    for goal in world.targets_visible:
        sentence = _render_goal(goal, naming)
        examples_lines.append(f"- {sentence}")
        alignment.append(entry(sentence, " & ".join(format_atom(atom) for atom in goal.atoms), f"targets_visible.abw:{goal.name}"))

    problem_lines.extend(
        [
            "",
            "## Task",
            *_task_lines(world),
        ]
    )

    hidden_bridge_lines = ["# Hidden Bridge", ""]
    for definition in world.hidden_bridge.definitions:
        hidden_bridge_lines.append(f"- {format_definition(definition)}")
    for lemma in world.hidden_bridge.lemmas:
        hidden_bridge_lines.append(f"- {format_clause(lemma, 'lemma')}")
    for mapping in world.hidden_bridge.mappings:
        hidden_bridge_lines.append(f"- {format_morphism(mapping)}")

    gold_solution_lines = ["# Gold Informal Solution", ""]
    if world.hidden_bridge.mappings:
        gold_solution_lines.append(
            "A strong solution identifies the symbol correspondence between the public theories and transports the source theorem family across it."
        )
    elif world.hidden_bridge.lemmas and not world.hidden_bridge.definitions:
        gold_solution_lines.append(
            "A strong solution packages the repeated low-level argument into one reusable lemma."
        )
    else:
        gold_solution_lines.append(
            "A strong solution names the synchronized low-level state with one reusable predicate and advances it with one lemma."
        )
    for definition in world.hidden_bridge.definitions:
        gold_solution_lines.append(f"- Formal definition: `{format_definition(definition)}`")
    for mapping in world.hidden_bridge.mappings:
        gold_solution_lines.append(f"- Formal mapping: `{mapping.name}` from `{mapping.source_theory}` to `{mapping.target_theory}`.")

    public_texts = {
        "problem.md": "\n".join(problem_lines) + "\n",
        "examples.md": "\n".join(examples_lines) + "\n",
        "theorem_cards.md": "\n".join(theorem_lines) + "\n",
    }
    hidden_names = {
        definition.name for definition in world.hidden_bridge.definitions
    } | {
        mapping.name for mapping in world.hidden_bridge.mappings
    }
    leaks = detect_hidden_name_leaks(public_texts, hidden_names)
    if leaks:
        raise ValueError(f"Hidden bridge names leaked into public NL artifacts: {leaks!r}")

    return RenderedTrack(
        problem_md=public_texts["problem.md"],
        examples_md=public_texts["examples.md"],
        theorem_cards_md=public_texts["theorem_cards.md"],
        hidden_bridge_private_md="\n".join(hidden_bridge_lines) + "\n",
        gold_informal_solution_private_md="\n".join(gold_solution_lines) + "\n",
        alignment=alignment,
    )
