"""Deep verification of Terrarium's source-level self-containment promise."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kicad_terrarium.core.discover import placed_symbols, used_symbols
from kicad_terrarium.core.extract import InheritanceError, extends_closure, symbol_blocks
from kicad_terrarium.core.footprints import (
    board_footprint_ids,
    is_embedded_model_path,
    is_stock_model_path,
    model_paths,
)
from kicad_terrarium.core.io import read_utf8
from kicad_terrarium.core.models import Diagnostic, FootprintId, LibraryEntry, SymbolId
from kicad_terrarium.core.project import project_lib_ids, project_schematics
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
    footprint_libraries: int = 0
    footprints: int = 0
    model_files: int = 0

    @property
    def ok(self) -> bool:
        return not any(item.level == "error" for item in self.diagnostics)


def _library_blocks(path: Path) -> tuple[dict[str, str], list[Diagnostic]]:
    files = sorted(path.rglob("*.kicad_sym")) if path.is_dir() else [path]
    merged: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    for source in files:
        try:
            current = symbol_blocks(read_utf8(source))
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


def _table_entries(
    project_dir: Path,
    table_name: str,
    report: VerificationReport,
) -> tuple[Path, dict[str, list[LibraryEntry]]] | None:
    table_path = project_dir / table_name
    if not table_path.is_file():
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"project has no {table_name}",
                table_path,
                "missing-project-table",
            )
        )
        return None
    if not table_path.resolve().is_relative_to(project_dir):
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"project {table_name} resolves outside the project",
                table_path,
                "external-project-table",
            )
        )
        return None
    try:
        entries = parse_library_entries(read_utf8(table_path), scope="project")
    except (OSError, UnicodeError, ValueError) as error:
        report.diagnostics.append(
            Diagnostic("error", f"invalid {table_name}: {error}", table_path, "invalid-table")
        )
        return None
    by_name: dict[str, list[LibraryEntry]] = {}
    for entry in entries:
        if entry.enabled:
            by_name.setdefault(entry.nickname, []).append(entry)
    return table_path, by_name


def _portable_source(
    library: str,
    entries: dict[str, list[LibraryEntry]],
    table_path: Path,
    project_dir: Path,
    report: VerificationReport,
    *,
    footprint: bool,
) -> Path | None:
    matches = entries.get(library, [])
    noun = "footprint source" if footprint else "source"
    if not matches:
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"{library}: used but not registered in the project",
                table_path,
                "external-library",
            )
        )
        return None
    if len(matches) > 1:
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"{library}: registered more than once",
                table_path,
                "duplicate-registration",
            )
        )
        return None
    entry = matches[0]
    if entry.library_type.casefold() != "kicad":
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"{library}: project {noun} has unsupported type {entry.library_type!r}",
                table_path,
                "unsupported-library-type",
            )
        )
        return None
    if not portable_project_uri(entry.uri):
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"{library}: project {noun} has a non-portable URI: {entry.uri}",
                table_path,
                "nonportable-uri",
            )
        )
        return None
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
        return None
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
        return None
    if not resolved.exists():
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"{library}: registered source does not exist: {path}",
                path,
                "missing-library",
            )
        )
        return None
    if footprint and not resolved.is_dir():
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"{library}: footprint source is not a directory: {path}",
                path,
                "unsupported-library-format",
            )
        )
        return None
    if not footprint and resolved.is_file() and resolved.suffix != ".kicad_sym":
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"{library}: expected a .kicad_sym file or unpacked-library folder, "
                f"found {resolved.name}",
                resolved,
                "unsupported-library-format",
            )
        )
        return None
    return resolved


def _verify_symbols(
    all_ids: list[str],
    project_dir: Path,
    report: VerificationReport,
) -> None:
    symbol_ids: list[SymbolId] = []
    for value in all_ids:
        try:
            symbol_id = SymbolId.parse(value)
            validate_library_nickname(symbol_id.library)
        except ValueError as error:
            report.diagnostics.append(
                Diagnostic("error", str(error), project_dir, "invalid-symbol-id")
            )
        else:
            symbol_ids.append(symbol_id)
    used_libraries = sorted({symbol_id.library for symbol_id in symbol_ids})
    report.libraries = len(used_libraries)
    report.symbols = len(set(symbol_ids))
    if not used_libraries:
        return
    table = _table_entries(project_dir, "sym-lib-table", report)
    if table is None:
        return
    table_path, entries = table
    for library in used_libraries:
        resolved = _portable_source(
            library,
            entries,
            table_path,
            project_dir,
            report,
            footprint=False,
        )
        if resolved is None:
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


def _verify_model(
    model: str,
    owner: Path,
    project_dir: Path,
    report: VerificationReport,
    project_models: set[Path],
) -> None:
    if is_stock_model_path(model) or is_embedded_model_path(model):
        return
    if not model.startswith("${KIPRJMOD}"):
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"3D model has a non-portable path: {model}",
                owner,
                "nonportable-model",
            )
        )
        return
    resolved = expand_uri(model, project_dir).resolve()
    if not resolved.is_relative_to(project_dir):
        report.diagnostics.append(
            Diagnostic(
                "error",
                f"3D model escapes the project: {model}",
                owner,
                "external-model",
            )
        )
    elif not resolved.is_file():
        report.diagnostics.append(
            Diagnostic("error", f"3D model does not exist: {model}", owner, "missing-model")
        )
    else:
        project_models.add(resolved)


def _verify_footprints(
    root: Path,
    sheets: list[Path],
    project_dir: Path,
    report: VerificationReport,
) -> None:
    values = [
        item.footprint
        for sheet in sheets
        for item in placed_symbols(read_utf8(sheet))
        if item.footprint
    ]
    board = root.with_suffix(".kicad_pcb")
    board_text = read_utf8(board) if board.is_file() else None
    if board_text is not None:
        values.extend(board_footprint_ids(board_text))
    footprint_ids: list[FootprintId] = []
    for value in values:
        try:
            footprint_id = FootprintId.parse(value)
            validate_library_nickname(footprint_id.library)
        except ValueError as error:
            report.diagnostics.append(Diagnostic("error", str(error), root, "invalid-footprint-id"))
        else:
            footprint_ids.append(footprint_id)
    used_libraries = sorted({item.library for item in footprint_ids})
    report.footprint_libraries = len(used_libraries)
    report.footprints = len(set(footprint_ids))
    project_models: set[Path] = set()
    if not used_libraries:
        if board_text is not None:
            for model in model_paths(board_text):
                _verify_model(model, board, project_dir, report, project_models)
        report.model_files = len(project_models)
        return
    table = _table_entries(project_dir, "fp-lib-table", report)
    if table is None:
        return
    table_path, entries = table
    for library in used_libraries:
        resolved = _portable_source(
            library,
            entries,
            table_path,
            project_dir,
            report,
            footprint=True,
        )
        if resolved is None:
            continue
        wanted = sorted({item.name for item in footprint_ids if item.library == library})
        for name in wanted:
            module = (resolved / f"{name}.kicad_mod").resolve()
            if not module.is_relative_to(resolved):
                report.diagnostics.append(
                    Diagnostic(
                        "error",
                        f"{library}:{name} escapes its footprint library",
                        module,
                        "invalid-footprint-id",
                    )
                )
                continue
            if not module.is_file():
                report.diagnostics.append(
                    Diagnostic(
                        "error",
                        f"{library}: missing footprint definition {name}.kicad_mod",
                        module,
                        "missing-footprint",
                    )
                )
                continue
            try:
                models = model_paths(read_utf8(module))
            except (OSError, UnicodeError, ValueError) as error:
                report.diagnostics.append(
                    Diagnostic(
                        "error",
                        f"cannot read footprint: {error}",
                        module,
                        "invalid-footprint",
                    )
                )
                continue
            for model in models:
                _verify_model(model, module, project_dir, report, project_models)
    if board_text is not None:
        for model in model_paths(board_text):
            _verify_model(model, board, project_dir, report, project_models)
    report.model_files = len(project_models)


def verify_project(root: Path) -> VerificationReport:
    """Verify symbol, footprint, and custom-model source containment."""
    report = VerificationReport()
    project_dir = root.resolve().parent
    try:
        sheets = project_schematics(root, allow_external=False)
        all_ids = project_lib_ids(root, allow_external=False)
        _verify_symbols(all_ids, project_dir, report)
        _verify_footprints(root, sheets, project_dir, report)
    except (OSError, UnicodeError, ValueError) as error:
        report.diagnostics.append(
            Diagnostic("error", f"cannot read project: {error}", root, "invalid-project")
        )
    return report
