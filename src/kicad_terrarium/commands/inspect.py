"""Read-only scan, audit, and deep verification commands."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import typer
from rich.markup import escape

from kicad_terrarium.commands.common import console, fail, resolve_root
from kicad_terrarium.core.audit import (
    cache_symbol_pins,
    is_stock_model_path,
    missing_pads,
    model_paths,
    pad_names,
)
from kicad_terrarium.core.discover import library_counts, placed_symbols
from kicad_terrarium.core.io import read_utf8
from kicad_terrarium.core.models import Diagnostic, PlacedSymbol, SymbolId
from kicad_terrarium.core.project import project_lib_ids, project_schematics
from kicad_terrarium.core.resolve import expand_uri, resolve_footprint_libs
from kicad_terrarium.core.sexpr import SExprError
from kicad_terrarium.core.verify import verify_project
from kicad_terrarium.presentation import DONE, ERROR, WARNING, status_line


def scan(
    path: Path | None = typer.Argument(
        None,
        help="Root .kicad_sch or project directory; defaults to the project here.",
    ),
    precise: bool = typer.Option(
        False,
        "--precise",
        help="List exact symbol names instead of only per-library counts.",
    ),
) -> None:
    """Show the symbol libraries used across every reachable sheet."""
    root = resolve_root(path)
    try:
        sheets = project_schematics(root, allow_external=False)
        all_ids = project_lib_ids(root, allow_external=False)
        for lib_id in all_ids:
            SymbolId.parse(lib_id)
    except (OSError, ValueError, SExprError) as error:
        fail(f"cannot scan project: {error}", code=2)
    counts = library_counts(all_ids)
    names: dict[str, set[str]] = defaultdict(set)
    for lib_id in all_ids:
        library, separator, symbol = lib_id.partition(":")
        if separator:
            names[library].add(symbol)

    console().print(
        f"[bold]{escape(root.name)}[/bold]  "
        f"{len(sheets)} sheet{'s' if len(sheets) != 1 else ''}, "
        f"{sum(counts.values())} symbol placements"
    )
    for library, count in counts.most_common():
        console().print(f"  [bold]{escape(library)}[/bold]  {count}")
        if precise:
            for symbol in sorted(names[library]):
                console().print(f"    {escape(symbol)}")


def _is_backup(path: Path) -> bool:
    return any(
        part.endswith("-backups") or part.startswith("_autosave") or part.startswith(".")
        for part in path.parts
    )


def _audit_project(root: Path) -> tuple[list[Diagnostic], int]:
    findings: list[Diagnostic] = []
    sheets = project_schematics(root, allow_external=False)
    project_dir = root.parent
    cache: dict[str, set[str]] = {}
    instances: list[tuple[Path, PlacedSymbol]] = []
    for sheet in sheets:
        text = read_utf8(sheet)
        instances.extend((sheet, item) for item in placed_symbols(text))
        for symbol_id, cached_pins in cache_symbol_pins(text).items():
            if symbol_id in cache and cache[symbol_id] != cached_pins:
                findings.append(
                    Diagnostic(
                        "error",
                        f"cached definition for {symbol_id} differs between sheets",
                        sheet,
                        "cache-conflict",
                    )
                )
            cache[symbol_id] = cached_pins

    # Keep one physical component when a multi-unit symbol has several records.
    physical: dict[tuple[Path, str], PlacedSymbol] = {}
    for sheet, item in instances:
        if item.on_board and not item.dnp and item.symbol_id.library != "power":
            physical[(sheet, item.reference)] = item

    footprint_libs = resolve_footprint_libs(project_dir)
    checked_models: set[Path] = set()
    module_texts: dict[Path, str] = {}
    for (sheet, _reference), item in physical.items():
        reference = item.reference
        symbol_id = str(item.symbol_id)
        footprint = item.footprint
        if not footprint:
            findings.append(
                Diagnostic(
                    "error",
                    f"{reference} ({symbol_id}) has no footprint [{sheet.name}]",
                    sheet,
                    "unassigned-footprint",
                )
            )
            continue
        library, separator, name = footprint.partition(":")
        if (
            not separator
            or not library
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
        ):
            findings.append(
                Diagnostic(
                    "error",
                    f"{reference}: malformed footprint ID {footprint!r}",
                    sheet,
                    "bad-footprint-id",
                )
            )
            continue
        directory = footprint_libs.get(library)
        if directory is None or not directory.is_dir():
            findings.append(
                Diagnostic(
                    "error",
                    f"{reference}: footprint library {library!r} is unavailable",
                    sheet,
                    "unknown-footprint-library",
                )
            )
            continue
        module = (directory / f"{name}.kicad_mod").resolve()
        if not module.is_relative_to(directory.resolve()):
            findings.append(
                Diagnostic(
                    "error",
                    f"{reference}: footprint path escapes its library: {footprint}",
                    module,
                    "bad-footprint-id",
                )
            )
            continue
        if not module.is_file():
            findings.append(
                Diagnostic(
                    "error",
                    f"{reference}: {footprint} has no .kicad_mod file",
                    module,
                    "missing-footprint",
                )
            )
            continue
        module_text = module_texts.get(module)
        if module_text is None:
            module_text = read_utf8(module)
            module_texts[module] = module_text
        instance_pins = cache.get(symbol_id)
        if instance_pins is None:
            findings.append(
                Diagnostic(
                    "warning",
                    f"{reference}: no cached pin definition found for {symbol_id}",
                    sheet,
                    "missing-cache-symbol",
                )
            )
        else:
            unmatched = missing_pads(instance_pins, pad_names(module_text))
            if unmatched:
                findings.append(
                    Diagnostic(
                        "error",
                        f"{reference}: pins {sorted(unmatched)} have no pad on {footprint}",
                        module,
                        "pin-pad-mismatch",
                    )
                )
        checked_models.add(module)

    for module in sorted(checked_models):
        for model in model_paths(module_texts[module]):
            if is_stock_model_path(model):
                continue
            if model.startswith("${KIPRJMOD}"):
                resolved = expand_uri(model, project_dir).resolve()
                if not resolved.is_relative_to(project_dir):
                    findings.append(
                        Diagnostic(
                            "error",
                            f"3D model escapes the project: {model}",
                            module,
                            "external-model",
                        )
                    )
                elif not resolved.exists():
                    findings.append(
                        Diagnostic(
                            "error",
                            f"3D model does not exist: {model}",
                            module,
                            "missing-model",
                        )
                    )
            else:
                findings.append(
                    Diagnostic(
                        "warning",
                        f"3D model path will not travel: {model}",
                        module,
                        "external-model",
                    )
                )

    reached = {sheet.resolve() for sheet in sheets}
    for candidate in sorted(project_dir.rglob("*.kicad_sch")):
        relative = candidate.relative_to(project_dir)
        if candidate.resolve() not in reached and not _is_backup(relative):
            findings.append(
                Diagnostic(
                    "warning",
                    f"sheet is not reachable from {root.name}: {relative}",
                    candidate,
                    "orphaned-sheet",
                )
            )
    return findings, len(physical)


def audit(
    root: Path | None = typer.Argument(
        None,
        help="Root .kicad_sch or project directory; defaults to the project here.",
    ),
    precise: bool = typer.Option(False, "--precise", help="Show every finding."),
) -> None:
    """Check layout-critical assignments, files, pins/pads, sheets, and models."""
    project = resolve_root(root)
    try:
        findings, physical_count = _audit_project(project)
    except (OSError, ValueError, SExprError) as error:
        fail(f"cannot audit project: {error}", code=2)

    grouped: dict[str, list[Diagnostic]] = defaultdict(list)
    for finding in findings:
        grouped[finding.code or "finding"].append(finding)
    for code, rows in grouped.items():
        level = ERROR if any(row.level == "error" for row in rows) else WARNING
        console().print(status_line(level, f"{code.replace('-', ' ')} ({len(rows)})"))
        shown = rows if precise else rows[:8]
        for row in shown:
            console().print(f"  {escape(row.message)}")
        if len(rows) > len(shown):
            console().print(f"  [dim]{len(rows) - len(shown)} more; use --precise[/dim]")
    if findings:
        console().print(status_line(ERROR, f"{len(findings)} finding(s)"))
        raise typer.Exit(code=1)
    console().print(status_line(DONE, f"audit clean; {physical_count} physical symbols checked"))


def verify(
    root: Path | None = typer.Argument(
        None,
        help="Root .kicad_sch or project directory; defaults to the project here.",
    ),
) -> None:
    """Prove every used symbol source exists inside the project."""
    project = resolve_root(root)
    report = verify_project(project)
    for diagnostic in report.diagnostics:
        status = ERROR if diagnostic.level == "error" else WARNING
        console().print(status_line(status, diagnostic.message))
    if report.ok:
        console().print(
            status_line(
                DONE,
                f"source-complete; {report.libraries} libraries, {report.symbols} symbols",
            )
        )
    if not report.ok:
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    app.command()(scan)
    app.command()(audit)
    app.command()(verify)
