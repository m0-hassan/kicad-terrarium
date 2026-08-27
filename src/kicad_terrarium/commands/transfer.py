"""Library discovery, symbol transfer, and project finalization commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from kicad_terrarium.commands.common import (
    apply_plan,
    console,
    fail,
    load_user_config,
    resolve_root,
    short_path,
)
from kicad_terrarium.core.extract import SymbolConflictError
from kicad_terrarium.core.io import MutationError
from kicad_terrarium.core.library import (
    LibrarySource,
    SymbolSource,
    discover_libraries,
    find_symbol_sources,
    source_blocks,
)
from kicad_terrarium.core.sexpr import SExprError
from kicad_terrarium.core.workflows import (
    plan_pluck,
    plan_seal,
    plan_sprout,
)
from kicad_terrarium.presentation import DONE, PLAN, UNCHANGED, status_line


def _find_projects(roots: list[Path]) -> list[Path]:
    projects: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for project in sorted(root.rglob("*.kicad_pro")):
            relative = project.relative_to(root)
            if any(
                part.endswith("-backups") or part.startswith("_autosave") or part.startswith(".")
                for part in relative.parts
            ):
                continue
            resolved = project.resolve()
            if resolved not in seen:
                seen.add(resolved)
                projects.append(project)
    return projects


def _choose_source(
    source: Path,
    symbol: str,
    source_library: str | None,
) -> SymbolSource:
    source = source.expanduser()
    try:
        matches = find_symbol_sources(source, symbol, library=source_library)
    except (OSError, UnicodeError, ValueError, SymbolConflictError) as error:
        fail(f"cannot inspect source {source}: {error}", code=2)
    if not matches:
        qualifier = f" in library {source_library!r}" if source_library else ""
        fail(f"symbol {symbol!r} was not found{qualifier} under {source}")
    if len(matches) > 1:
        choices = ", ".join(match.library.selector for match in matches)
        fail(
            f"symbol {symbol!r} is ambiguous ({choices}); select one with --from-library",
            code=2,
        )
    return matches[0]


def list_(
    target: Path | None = typer.Argument(
        None,
        help="Library/vault/project to inspect; omit to list configured projects.",
    ),
) -> None:
    """List configured projects or symbols in packed, unpacked, or nested libraries."""
    if target is None:
        config = load_user_config()
        try:
            projects = _find_projects(config.project_roots)
        except OSError as error:
            fail(f"cannot search configured project roots: {error}", code=2)
        if not projects:
            console().print(status_line(UNCHANGED, "no projects found in configured roots"))
            return
        for project in projects:
            console().print(
                f"  {escape(project.stem)}  [dim]{escape(short_path(project.parent))}[/dim]"
            )
        return

    try:
        libraries = discover_libraries(target.expanduser())
    except (OSError, UnicodeError, ValueError) as error:
        fail(f"cannot inspect {target}: {error}", code=2)
    if not libraries:
        fail(f"no symbol libraries found under {target}")
    catalog: list[tuple[LibrarySource, list[str]]] = []
    for library in libraries:
        try:
            names = sorted(source_blocks(library))
        except (OSError, UnicodeError, ValueError) as error:
            fail(f"cannot read {library.label}: {error}", code=2)
        catalog.append((library, names))
    for library, names in catalog:
        group = " / ".join((*library.group, library.nickname))
        console().print(f"[bold]{escape(group)}[/bold]  {len(names)}")
        for name in names:
            console().print(f"  {escape(name)}")


def pluck(
    symbol: str = typer.Argument(..., help="Symbol name to copy into the project."),
    from_: Path | None = typer.Option(
        None,
        "--from",
        help="Source file, unpacked library, vault folder, or project; defaults to your vault.",
    ),
    from_library: str | None = typer.Option(
        None,
        "--from-library",
        help="Resolve a duplicate by nickname or nested path (sensors/environmental).",
    ),
    into: Path | None = typer.Option(
        None,
        "--into",
        help="Destination project; defaults to the project here.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
) -> None:
    """Bring one reusable symbol into a project in a few keystrokes."""
    config = load_user_config()
    source_path = from_ or config.vault
    if source_path is None:
        fail("no source given and no vault configured; run 'kt init'", code=2)
    source = _choose_source(source_path, symbol, from_library)
    root = resolve_root(into)
    _execute_pluck(source, root, dry_run=dry_run)


def _execute_pluck(
    source: SymbolSource,
    root: Path,
    *,
    dry_run: bool = False,
) -> None:
    """Apply one already-resolved symbol transfer without rediscovering its source."""
    try:
        result = plan_pluck(source, root)
    except (OSError, UnicodeError, ValueError, SExprError, MutationError) as error:
        fail(str(error), code=2)
    changed = apply_plan(result.plan, dry_run=dry_run)
    status = PLAN if dry_run and result.plan.changes else (DONE if changed else UNCHANGED)
    parent_note = f" with {', '.join(result.parents)}" if result.parents else ""
    console().print(
        status_line(
            status,
            f"plucked {source.symbol}{parent_note} into {short_path(result.destination)}",
        )
    )


def sprout(
    symbol: str = typer.Argument(..., help="Symbol name to add to your vault."),
    from_: Path | None = typer.Option(
        None,
        "--from",
        help="Source library/project; defaults to the project here.",
    ),
    from_library: str | None = typer.Option(
        None,
        "--from-library",
        help="Resolve a duplicate by nickname or nested path (sensors/environmental).",
    ),
    library: str | None = typer.Option(
        None,
        "--library",
        help="Vault sub-library, optionally nested (for example sensors/environmental).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
) -> None:
    """Promote a project symbol into your reusable vault."""
    config = load_user_config()
    if config.vault is None:
        fail("no vault configured; run 'kt init'", code=2)
    source_path = from_ or resolve_root(None)
    source = _choose_source(source_path, symbol, from_library)
    _execute_sprout(source, config.vault, library=library, dry_run=dry_run)


def _execute_sprout(
    source: SymbolSource,
    vault: Path,
    *,
    library: str | None = None,
    dry_run: bool = False,
) -> None:
    """Apply one already-resolved symbol transfer without rediscovering its source."""
    try:
        result = plan_sprout(source, vault, library=library)
    except (OSError, UnicodeError, ValueError, SExprError, MutationError) as error:
        fail(str(error), code=2)
    changed = apply_plan(result.plan, dry_run=dry_run)
    status = PLAN if dry_run and result.plan.changes else (DONE if changed else UNCHANGED)
    console().print(
        status_line(status, f"sprouted {source.symbol} into {short_path(result.destination)}")
    )


def seal(
    root: Path | None = typer.Argument(
        None,
        help="Root .kicad_sch or project directory; defaults to the project here.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
) -> None:
    """Finalize used symbol, footprint, and custom-model sources inside the project."""
    project = resolve_root(root)
    try:
        result = plan_seal(project)
    except (
        OSError,
        UnicodeError,
        ValueError,
        SExprError,
        SymbolConflictError,
        MutationError,
    ) as error:
        fail(str(error), code=2)
    backup_count = sum(change.expected_digest is not None for change in result.plan.changes)
    changed = apply_plan(result.plan, dry_run=dry_run)
    for symbol_library in result.libraries:
        status = (
            PLAN
            if dry_run and symbol_library.changed
            else (DONE if symbol_library.changed else UNCHANGED)
        )
        migrated = [
            source for source in symbol_library.sources if source != symbol_library.nickname
        ]
        label = (
            f"{', '.join(migrated)} -> {symbol_library.nickname}"
            if migrated
            else symbol_library.nickname
        )
        console().print(
            status_line(
                status,
                f"{label}: {symbol_library.used} used, {symbol_library.kept} definitions",
            )
        )
    for footprint_library in result.footprint_libraries:
        status = (
            PLAN
            if dry_run and footprint_library.changed
            else (DONE if footprint_library.changed else UNCHANGED)
        )
        migrated = [
            source for source in footprint_library.sources if source != footprint_library.nickname
        ]
        label = (
            f"{', '.join(migrated)} -> {footprint_library.nickname}"
            if migrated
            else footprint_library.nickname
        )
        console().print(
            status_line(
                status,
                f"{label}: {footprint_library.used} used, {footprint_library.kept} footprints",
            )
        )
    if result.model_files:
        model_status = (
            PLAN
            if dry_run and result.changed_model_files
            else (DONE if result.changed_model_files else UNCHANGED)
        )
        console().print(
            status_line(
                model_status,
                f"{result.model_files} project-contained custom 3D model file(s)",
            )
        )
    if not result.libraries and not result.footprint_libraries and not result.model_files:
        console().print(status_line(UNCHANGED, "project uses no external library definitions"))
    elif not dry_run:
        console().print(status_line(DONE if changed else UNCHANGED, "project sources are sealed"))
        if backup_count:
            console().print(status_line(DONE, f"{backup_count} adjacent recovery backups created"))


def register(app: typer.Typer) -> None:
    app.command("list")(list_)
    app.command()(pluck)
    app.command()(sprout)
    app.command()(seal)
