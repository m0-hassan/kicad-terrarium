"""Exact-span library nickname changes for schematic references."""

from __future__ import annotations

import re

from kicad_terrarium.core.sexpr import SExprError, apply_replacements, forms, quote, quoted_tokens


def repoint_libraries(text: str, mapping: dict[str, str]) -> tuple[str, dict[str, int]]:
    """Atomically rewrite several exact library nicknames.

    Description strings and unrelated metadata that happen to mention the old
    nickname are deliberately untouched.
    """
    replacements: list[tuple[int, int, str]] = []
    counts = {old: 0 for old, new in mapping.items() if old != new}
    try:
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
    except SExprError:
        # Compatibility for callers passing a fragment rather than a document.
        replaced = text
        for old, new in mapping.items():
            if old == new:
                continue
            pattern = re.compile(rf'(?P<head>\b(?:lib_id|symbol)\s+)"{re.escape(old)}:')
            replaced, counts[old] = pattern.subn(rf'\g<head>"{new}:', replaced)
        return replaced, counts
    return apply_replacements(text, replacements), counts


def repoint_text(text: str, old_library: str, new_library: str) -> tuple[str, int]:
    """Rewrite one exact nickname in ``lib_id`` and cached-symbol identifiers."""
    output, counts = repoint_libraries(text, {old_library: new_library})
    return output, counts.get(old_library, 0)
