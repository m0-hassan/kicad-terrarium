"""Parse and minimally edit KiCad library tables."""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

from kicad_terrarium.core.models import LibraryEntry, TableScope
from kicad_terrarium.core.sexpr import (
    Form,
    apply_replacements,
    child_forms,
    forms,
    quote,
    quoted_tokens,
)

EMPTY_TABLE = "(sym_lib_table\n\t(version 7)\n)\n"
MANAGED_DESCRIPTION = "Managed by kicad-terrarium"
_SAFE_NICKNAME = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')
_VARIABLE = re.compile(r"\$\{([^}]+)\}")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


def portable_project_uri(uri: str) -> bool:
    """Whether a table URI can survive moving the complete project folder."""
    variables = set(_VARIABLE.findall(uri))
    if variables - {"KIPRJMOD"} or uri.startswith("~"):
        return False
    if variables:
        return uri == "${KIPRJMOD}" or uri.startswith("${KIPRJMOD}/")
    return not Path(uri).is_absolute() and not PureWindowsPath(uri).is_absolute()


def validate_library_nickname(name: str) -> str:
    """Return a safe KiCad nickname or raise ``ValueError``.

    Nicknames become both ``library:symbol`` prefixes and local filenames, so
    path separators, colons, control characters, and dot-directory names are
    never valid Terrarium output targets.
    """
    if (
        name != name.strip()
        or name in {"", ".", ".."}
        or name.endswith(".")
        or name.split(".", 1)[0].upper() in _WINDOWS_RESERVED
        or not _SAFE_NICKNAME.fullmatch(name)
    ):
        raise ValueError(f"unsafe library nickname: {name!r}")
    return name


def _field_value(text: str, all_forms: list[Form], entry: Form, head: str) -> str | None:
    field = next((form for form in child_forms(all_forms, entry, head)), None)
    if field is None:
        return None
    values = quoted_tokens(text, field)
    return values[0].value if values else None


def _optional_field_value(
    text: str,
    all_forms: list[Form],
    entry: Form,
    head: str,
) -> str:
    matches = child_forms(all_forms, entry, head)
    if not matches:
        return ""
    values = quoted_tokens(text, matches[0]) if len(matches) == 1 else []
    if len(values) != 1:
        raise ValueError(f"library entry has an invalid optional {head} field")
    return values[0].value


def parse_library_entries(
    table_text: str,
    *,
    scope: TableScope = "project",
) -> list[LibraryEntry]:
    """Parse immediate ``lib`` entries, preserving their table order."""
    all_forms = forms(table_text)
    roots = [
        form
        for form in all_forms
        if form.depth == 0 and form.head in {"sym_lib_table", "fp_lib_table"}
    ]
    if len(roots) != 1:
        raise ValueError(f"expected one KiCad library table, found {len(roots)}")
    result: list[LibraryEntry] = []
    for entry in child_forms(all_forms, roots[0], "lib"):
        fields: dict[str, str] = {}
        for head in ("name", "type", "uri"):
            matches = child_forms(all_forms, entry, head)
            values = quoted_tokens(table_text, matches[0]) if len(matches) == 1 else []
            if len(values) != 1:
                raise ValueError(f"library entry needs exactly one quoted {head} field")
            fields[head] = values[0].value
        children = child_forms(all_forms, entry)
        disabled = any(form.head == "disabled" for form in children)
        hidden = any(form.head == "hidden" for form in children)
        _optional_field_value(table_text, all_forms, entry, "options")
        result.append(
            LibraryEntry(
                nickname=fields["name"],
                library_type=fields["type"],
                uri=fields["uri"],
                scope=scope,
                enabled=not disabled,
                hidden=hidden,
                description=_optional_field_value(table_text, all_forms, entry, "descr"),
            )
        )
    return result


def table_entry_uri(
    name: str,
    uri: str,
    *,
    hidden: bool = False,
    description: str = MANAGED_DESCRIPTION,
) -> str:
    """One explicitly located project symbol-library registration line."""
    validate_library_nickname(name)
    hidden_field = "(hidden)" if hidden else ""
    return (
        f'\t(lib (name {quote(name)})(type "KiCad")'
        f'(uri {quote(uri)})(options "")'
        f"(descr {quote(description)}){hidden_field})\n"
    )


def remove_from_sym_lib_table(text: str, names: list[str]) -> str:
    """Remove named entries by source span, including multiline entries."""
    drop = set(names)
    all_forms = forms(text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "sym_lib_table"]
    if len(roots) != 1:
        raise ValueError("invalid sym-lib-table")
    replacements: list[tuple[int, int, str]] = []
    for entry in child_forms(all_forms, roots[0], "lib"):
        nickname = _field_value(text, all_forms, entry, "name")
        if nickname in drop:
            start = entry.start
            while start > roots[0].start and text[start - 1] in " \t":
                start -= 1
            if entry.end < len(text) and text[entry.end : entry.end + 2] == "\r\n":
                end = entry.end + 2
            elif entry.end < len(text) and text[entry.end] == "\n":
                end = entry.end + 1
            else:
                end = entry.end
            replacements.append((start, end, ""))
    return apply_replacements(text, replacements)


def upsert_sym_lib_uris(
    existing: str | None,
    entries: dict[str, str],
    *,
    hidden_names: set[str] | frozenset[str] = frozenset(),
    descriptions: dict[str, str] | None = None,
) -> str:
    """Replace named direct registrations with explicit project-portable URIs."""
    nonportable = [name for name, uri in entries.items() if not portable_project_uri(uri)]
    if nonportable:
        raise ValueError(
            "project library URI is not portable for: " + ", ".join(sorted(nonportable))
        )
    text = existing if existing is not None else EMPTY_TABLE
    without_old = remove_from_sym_lib_table(text, list(entries))
    all_forms = forms(without_old)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "sym_lib_table"]
    if len(roots) != 1:
        raise ValueError("invalid sym-lib-table")
    root = roots[0]
    newline = "\r\n" if "\r\n" in without_old else "\n"
    descriptions = descriptions or {}
    insertion = "".join(
        table_entry_uri(
            name,
            uri,
            hidden=name in hidden_names,
            description=descriptions.get(name, MANAGED_DESCRIPTION),
        )
        for name, uri in entries.items()
    ).replace("\n", newline)
    if root.start + 1 < root.end and not without_old[: root.end - 1].endswith(("\n", "\r")):
        insertion = newline + insertion
    return without_old[: root.end - 1] + insertion + without_old[root.end - 1 :]
