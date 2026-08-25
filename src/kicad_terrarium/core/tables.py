"""Emit and merge sym-lib-table registrations.

Registering a vendored library under its ORIGINAL name makes it shadow the
global one (KiCad checks the project table first), so no lib_id in any
schematic needs rewriting. Merging preserves entries the project already has.
"""

import re

from kicad_terrarium.core.verify import registered_libraries

EMPTY_TABLE = "(sym_lib_table\n\t(version 7)\n)\n"
_ENTRY_NAME = re.compile(r'\(lib\s*\(name "([^"]+)"\)')


def table_entry(name: str) -> str:
    """One project-local registration line for a vendored library."""
    return (
        f'\t(lib (name "{name}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/library/{name}.kicad_sym")'
        f'(options "")(descr "Vendored by kicad-terrarium"))\n'
    )


def merge_sym_lib_table(existing: str | None, names: list[str]) -> str:
    """`existing` table text (or None) with entries for `names` added.

    Names already registered are left untouched; their existing entries win.
    """
    text = existing if existing is not None else EMPTY_TABLE
    additions = "".join(table_entry(n) for n in names if n not in registered_libraries(text))
    if not additions:
        return text
    closing = text.rstrip().rfind(")")
    return text.rstrip()[:closing] + additions + ")\n"


def remove_from_sym_lib_table(text: str, names: list[str]) -> str:
    """Drop the `(lib (name "X") ...)` entries for `names` (one entry per line)."""
    drop = set(names)
    kept = [
        line
        for line in text.splitlines(keepends=True)
        if not ((m := _ENTRY_NAME.search(line)) and m.group(1) in drop)
    ]
    return "".join(kept)
