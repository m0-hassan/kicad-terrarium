"""Discover project references without depending on KiCad's indentation.

KiCad files are S-expressions, but Terrarium deliberately does not round-trip
them through an object model. This module reads only the forms it needs and
edits exact source spans, preserving every unknown field around them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from kicad_terrarium.core.models import PlacedSymbol, SymbolId
from kicad_terrarium.core.sexpr import (
    Form,
    SExprError,
    apply_replacements,
    atoms,
    child_forms,
    forms,
    quote,
    quoted_tokens,
)


def _first_string(text: str, form: Form) -> str | None:
    tokens = quoted_tokens(text, form)
    return tokens[0].value if tokens else None


def find_lib_ids(text: str) -> list[str]:
    """Return every structurally valid ``lib_id`` in source order."""
    result: list[str] = []
    all_forms = forms(text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "kicad_sch"]
    if len(roots) != 1:
        raise SExprError(f"expected one kicad_sch root, found {len(roots)}")
    for form in all_forms:
        if form.head == "lib_id" and (value := _first_string(text, form)) is not None:
            result.append(value)
    return result


def sheet_files(text: str) -> list[str]:
    """Return filenames from KiCad ``Sheetfile`` properties."""
    all_forms = forms(text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "kicad_sch"]
    if len(roots) != 1:
        raise SExprError(f"expected one kicad_sch root, found {len(roots)}")
    candidates = [
        property_form
        for sheet in child_forms(all_forms, roots[0], "sheet")
        for property_form in child_forms(all_forms, sheet, "property")
    ]
    result: list[str] = []
    for form in candidates:
        if form.head != "property":
            continue
        values = quoted_tokens(text, form)
        if len(values) >= 2 and values[0].value == "Sheetfile":
            result.append(values[1].value)
    return result


def library_counts(lib_ids: list[str]) -> Counter[str]:
    """Count placed-symbol references by library nickname."""
    return Counter(lib_id.split(":", 1)[0] for lib_id in lib_ids if ":" in lib_id)


def _bool_field(text: str, children: list[Form], head: str, default: bool) -> bool:
    field = next((child for child in children if child.head == head), None)
    if field is None:
        return default
    values = atoms(text, field)
    return not values or values[0].lower() not in {"no", "false", "0"}


def placed_symbols(text: str) -> list[PlacedSymbol]:
    """Read placed symbols, excluding definitions in ``lib_symbols``."""
    all_forms = forms(text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "kicad_sch"]
    if len(roots) != 1:
        return []

    result: list[PlacedSymbol] = []
    for symbol in child_forms(all_forms, roots[0], "symbol"):
        children = child_forms(all_forms, symbol)
        lib_form = next((child for child in children if child.head == "lib_id"), None)
        lib_id = _first_string(text, lib_form) if lib_form else None
        if lib_id is None:
            continue
        try:
            symbol_id = SymbolId.parse(lib_id)
        except ValueError as error:
            raise ValueError(f"placed symbol has {error}") from error
        properties: dict[str, str] = {}
        for prop in children:
            if prop.head != "property":
                continue
            values = quoted_tokens(text, prop)
            if len(values) >= 2:
                properties[values[0].value] = values[1].value
        result.append(
            PlacedSymbol(
                reference=properties.get("Reference", "?"),
                symbol_id=symbol_id,
                value=properties.get("Value", ""),
                footprint=properties.get("Footprint", ""),
                on_board=_bool_field(text, children, "on_board", True),
                dnp=_bool_field(text, children, "dnp", False),
            )
        )
    return result


Decider = Callable[[str, str, str, str], str | None]


def reassign_footprints(text: str, decide: Decider) -> tuple[str, list[tuple[str, str]]]:
    """Rewrite only placed-symbol Footprint value spans selected by ``decide``."""
    all_forms = forms(text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "kicad_sch"]
    if len(roots) != 1:
        return text, []

    replacements: list[tuple[int, int, str]] = []
    applied: list[tuple[str, str]] = []
    for symbol in child_forms(all_forms, roots[0], "symbol"):
        children = child_forms(all_forms, symbol)
        lib_form = next((child for child in children if child.head == "lib_id"), None)
        lib_id = _first_string(text, lib_form) if lib_form else None
        if lib_id is None:
            continue
        properties: dict[str, tuple[str, Form]] = {}
        for prop in children:
            if prop.head != "property":
                continue
            values = quoted_tokens(text, prop)
            if len(values) >= 2:
                properties[values[0].value] = (values[1].value, prop)
        footprint = properties.get("Footprint")
        if footprint is None:
            continue
        reference = properties.get("Reference", ("?", footprint[1]))[0]
        value = properties.get("Value", ("", footprint[1]))[0]
        new = decide(reference, lib_id, value, footprint[0])
        if new is None or new == footprint[0]:
            continue
        token = quoted_tokens(text, footprint[1])[1]
        replacements.append((token.start, token.end, quote(new)))
        applied.append((reference, new))
    return apply_replacements(text, replacements), applied


def used_symbols(lib_ids: list[str], library: str) -> set[str]:
    """Symbol names referenced from one exact library nickname."""
    names: set[str] = set()
    for lib_id in lib_ids:
        lib, separator, symbol = lib_id.partition(":")
        if separator and lib == library:
            names.add(symbol)
    return names
