"""Exact-span library nickname changes for schematic references."""

from __future__ import annotations

from kicad_terrarium.core.sexpr import apply_replacements, forms, quote, quoted_tokens


def repoint_libraries(text: str, mapping: dict[str, str]) -> tuple[str, dict[str, int]]:
    """Atomically rewrite several exact library nicknames.

    Description strings and unrelated metadata that happen to mention the old
    nickname are deliberately untouched.
    """
    replacements: list[tuple[int, int, str]] = []
    counts = {old: 0 for old, new in mapping.items() if old != new}
    for form in forms(text):
        if form.head not in {"lib_id", "symbol"}:
            continue
        tokens = quoted_tokens(text, form)
        if not tokens:
            continue
        old, separator, symbol = tokens[0].value.partition(":")
        if not separator or old not in counts:
            continue
        replacements.append((tokens[0].start, tokens[0].end, quote(f"{mapping[old]}:{symbol}")))
        counts[old] += 1
    return apply_replacements(text, replacements), counts
