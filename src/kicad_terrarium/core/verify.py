"""Deep verification of Terrarium's source-level self-containment promise."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kicad_terrarium.core.discover import used_symbols
from kicad_terrarium.core.extract import InheritanceError, extends_closure, symbol_blocks
from kicad_terrarium.core.models import Diagnostic, LibraryEntry, SymbolId
from kicad_terrarium.core.project import project_lib_ids
from kicad_terrarium.core.resolve import expand_uri
from kicad_terrarium.core.tables import (
    parse_library_entries,
    portable_project_uri,
    validate_library_nickname,
)


@dataclass
class VerificationReport:
    """The complete, stable set of facts found by a verification pass."""

    diagnostics: list[Diagnostic] = field(default_factory=list)
    libraries: int = 0
    symbols: int = 0

    @property
    def ok(self) -> bool:
        return not any(item.level == "error" for item in self.diagnostics)


def _library_blocks(path: Path) -> tuple[dict[str, str], list[Diagnostic]]:
    files = sorted(path.rglob("*.kicad_sym")) if path.is_dir() else [path]
    merged: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    for source in files:
        try:
            current = symbol_blocks(source.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            diagnostics.append(
                Diagnostic(
                    "error",
                    f"cannot read symbol library: {error}",
                    source,
                    "invalid-library",
                )
            )
            continue
        for name, block in current.items():
            if name in merged and merged[name] != block:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        f"symbol {name!r} has conflicting definitions in directory library",
                        source,
                        "duplicate-symbol",
                    )
                )
            else:
                merged[name] = block
    return merged, diagnostics


def verify_project(root: Path) -> VerificationReport:
    """Verify registrations, containment, paths, definitions, and inheritance."""
    report = VerificationReport()
    project_dir = root.resolve().parent
    try:
        all_ids = project_lib_ids(root, allow_external=False)
    except (OSError, ValueError) as error:
        report.diagnostics.append(
            Diagnostic("error", f"cannot read project schematics: {error}", root, "invalid-project")
        )
        return report

    symbol_ids: list[SymbolId] = []
    for value in all_ids:
        try:
            symbol_id = SymbolId.parse(value)
            validate_library_nickname(symbol_id.library)
        except ValueError as error:
            report.diagnostics.append(Diagnostic("error", str(error), root, "invalid-symbol-id"))
        else:
            symbol_ids.append(symbol_id)
    used_libraries = sorted({symbol_id.library for symbol_id in symbol_ids})
    report.libraries = len(used_libraries)
    report.symbols = len(set(symbol_ids))
    if not used_libraries:
        return report
    table_path = project_dir / "sym-lib-table"
    if not table_path.is_file():
        report.diagnostics.append(
            Diagnostic("error", "project has no sym-lib-table", table_path, "missing-project-table")
        )
        return report
    if not table_path.resolve().is_relative_to(project_dir):
        report.diagnostics.append(
            Diagnostic(
                "error",
                "project sym-lib-table resolves outside the project",
                table_path,
                "external-project-table",
            )
        )
        return report
    try:
        entries = parse_library_entries(table_path.read_bytes().decode("utf-8"), scope="project")
    except (OSError, UnicodeError, ValueError) as error:
        report.diagnostics.append(
            Diagnostic("error", f"invalid sym-lib-table: {error}", table_path, "invalid-table")
        )
        return report

    by_name: dict[str, list[LibraryEntry]] = {}
    for entry in entries:
        if entry.enabled:
            by_name.setdefault(entry.nickname, []).append(entry)

    for library in used_libraries:
        matches = by_name.get(library, [])
        if not matches:
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: used but not registered in the project",
                    table_path,
                    "external-library",
                )
            )
            continue
        if len(matches) > 1:
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: registered more than once",
                    table_path,
                    "duplicate-registration",
                )
            )
            continue
        entry = matches[0]
        if entry.library_type.casefold() != "kicad":
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: project source has unsupported type {entry.library_type!r}",
                    table_path,
                    "unsupported-library-type",
                )
            )
            continue
        if not portable_project_uri(entry.uri):
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: project source has a non-portable URI: {entry.uri}",
                    table_path,
                    "nonportable-uri",
                )
            )
            continue
        path = expand_uri(entry.uri, project_dir, base_dir=table_path.parent)
        if "${" in str(path):
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: project path contains an unresolved variable: {entry.uri}",
                    table_path,
                    "unresolved-variable",
                )
            )
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(project_dir):
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: registration points outside the project: {path}",
                    path,
                    "external-path",
                )
            )
            continue
        if not resolved.is_file() and not resolved.is_dir():
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: registered source does not exist: {path}",
                    path,
                    "missing-library",
                )
            )
            continue
        if resolved.is_file() and resolved.suffix != ".kicad_sym":
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: expected a .kicad_sym file or unpacked-library folder, "
                    f"found {resolved.name}",
                    resolved,
                    "unsupported-library-format",
                )
            )
            continue
        blocks, diagnostics = _library_blocks(resolved)
        report.diagnostics.extend(diagnostics)
        wanted = used_symbols(all_ids, library)
        try:
            _ordered, missing = extends_closure(wanted, blocks)
        except InheritanceError as error:
            report.diagnostics.append(
                Diagnostic("error", f"{library}: {error}", resolved, "inheritance-cycle")
            )
            continue
        if missing:
            report.diagnostics.append(
                Diagnostic(
                    "error",
                    f"{library}: missing symbol definitions or parents: "
                    f"{', '.join(sorted(missing))}",
                    resolved,
                    "missing-symbol",
                )
            )
    return report
