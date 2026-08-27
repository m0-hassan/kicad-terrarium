"""Exact discovery and rewriting of KiCad footprint/model references."""

from __future__ import annotations

import re
from collections.abc import Callable

from kicad_terrarium.core.sexpr import (
    Form,
    SExprError,
    apply_replacements,
    child_forms,
    descendant_forms,
    forms,
    quote,
    quoted_tokens,
)

ModelDecider = Callable[[str], str | None]
BoardModelDecider = Callable[[str, str], str | None]
_STOCK_MODEL = re.compile(r"^\$\{(?:KICAD\d+_3DMODEL_DIR|KISYS3DMOD)\}(?:[/\\]|$)")


def _root_and_forms(text: str, head: str) -> tuple[Form, list[Form]]:
    all_forms = forms(text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == head]
    if len(roots) != 1:
        raise SExprError(f"expected one {head} root, found {len(roots)}")
    return roots[0], all_forms


def board_footprint_ids(text: str) -> list[str]:
    """Library-linked footprint IDs embedded in a board, in source order."""
    root, all_forms = _root_and_forms(text, "kicad_pcb")
    result: list[str] = []
    for footprint in child_forms(all_forms, root, "footprint"):
        tokens = quoted_tokens(text, footprint)
        if tokens and ":" in tokens[0].value:
            result.append(tokens[0].value)
    return result


def repoint_schematic_footprints(
    text: str,
    mapping: dict[str, str],
) -> tuple[str, dict[str, int]]:
    """Rewrite only placed-symbol Footprint properties for mapped libraries."""
    root, all_forms = _root_and_forms(text, "kicad_sch")
    counts = {old: 0 for old, new in mapping.items() if old != new}
    if not counts:
        return text, counts
    replacements: list[tuple[int, int, str]] = []
    for symbol in child_forms(all_forms, root, "symbol"):
        for prop in child_forms(all_forms, symbol, "property"):
            tokens = quoted_tokens(text, prop)
            if len(tokens) < 2 or tokens[0].value != "Footprint":
                continue
            library, separator, name = tokens[1].value.partition(":")
            if separator and library in counts:
                replacements.append(
                    (tokens[1].start, tokens[1].end, quote(f"{mapping[library]}:{name}"))
                )
                counts[library] += 1
    return apply_replacements(text, replacements), counts


def model_paths(text: str) -> list[str]:
    """Every structurally valid 3D model URI in a footprint or board."""
    result: list[str] = []
    for form in forms(text):
        if form.head != "model":
            continue
        tokens = quoted_tokens(text, form)
        if tokens:
            result.append(tokens[0].value)
    return result


def is_stock_model_path(path: str) -> bool:
    """Whether a model URI uses a recognized KiCad installation variable."""
    return _STOCK_MODEL.match(path) is not None


def is_embedded_model_path(path: str) -> bool:
    """Whether a model is stored inside its KiCad document."""
    return path.startswith("kicad-embed://")


def rewrite_model_paths(text: str, decide: ModelDecider) -> tuple[str, int]:
    """Rewrite exact model URI tokens selected by ``decide``."""
    replacements: list[tuple[int, int, str]] = []
    for form in forms(text):
        if form.head != "model":
            continue
        tokens = quoted_tokens(text, form)
        if not tokens:
            continue
        new = decide(tokens[0].value)
        if new is not None and new != tokens[0].value:
            replacements.append((tokens[0].start, tokens[0].end, quote(new)))
    return apply_replacements(text, replacements), len(replacements)


def rewrite_board_assets(
    text: str,
    library_mapping: dict[str, str],
    decide_model: BoardModelDecider,
) -> tuple[str, dict[str, int], int]:
    """Rewrite board footprint links and their model paths without reserialization."""
    root, all_forms = _root_and_forms(text, "kicad_pcb")
    counts = {old: 0 for old, new in library_mapping.items() if old != new}
    replacements: list[tuple[int, int, str]] = []
    model_count = 0
    for footprint in child_forms(all_forms, root, "footprint"):
        tokens = quoted_tokens(text, footprint)
        original_library = ""
        if tokens:
            library, separator, name = tokens[0].value.partition(":")
            if separator:
                original_library = library
            if separator and library in counts:
                replacements.append(
                    (
                        tokens[0].start,
                        tokens[0].end,
                        quote(f"{library_mapping[library]}:{name}"),
                    )
                )
                counts[library] += 1
        for model in descendant_forms(all_forms, footprint, "model"):
            model_tokens = quoted_tokens(text, model)
            if not model_tokens:
                continue
            new = decide_model(original_library, model_tokens[0].value)
            if new is not None and new != model_tokens[0].value:
                replacements.append((model_tokens[0].start, model_tokens[0].end, quote(new)))
                model_count += 1
    return apply_replacements(text, replacements), counts, model_count
