"""Library transfer, finalization, pruning, and reference rewrite commands."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import typer
from rich.markup import escape

from kicad_terrarium.commands.common import (
    apply_plan,
    console,
    emit_json,
    fail,
    load_user_config,
    resolve_root,
    runtime,
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
from kicad_terrarium.core.verify import verify_project
from kicad_terrarium.core.workflows import (
    SealResult,
    WorkflowError,
    plan_graft,
    plan_pluck,
    plan_prune,
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
        if runtime.json_output:
            emit_json({"ok": True, "projects": [str(project) for project in projects]})
            return
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
    if runtime.json_output:
        emit_json(
            {
                "ok": True,
                "source": str(target),
                "libraries": [
                    {
                        "library": library.nickname,
                        "group": library.group,
                        "symbols": names,
                    }
                    for library, names in catalog
                ],
            }
        )
        return
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
    as_library: str | None = typer.Option(
        None,
        "--as",
        help="Exact destination nickname; defaults to Terrarium__<source>.",
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
    _execute_pluck(source, root, as_library=as_library, dry_run=dry_run)


def _execute_pluck(
    source: SymbolSource,
    root: Path,
    *,
    as_library: str | None = None,
    dry_run: bool = False,
) -> None:
    """Apply one already-resolved symbol transfer without rediscovering its source."""
    try:
        result = plan_pluck(source, root, as_library=as_library)
    except (OSError, UnicodeError, ValueError, SExprError, MutationError) as error:
        fail(str(error), code=2)
    changed = apply_plan(result.plan, dry_run=dry_run)
    if runtime.json_output:
        emit_json(
            {
                "ok": True,
                "dry_run": dry_run,
                "symbol": source.symbol,
                "library": result.library,
                "destination": result.destination,
                "added": result.added,
                "parents": result.parents,
                "changed": changed,
            }
        )
        return
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
    if runtime.json_output:
        emit_json(
            {
                "ok": True,
                "dry_run": dry_run,
                "symbol": source.symbol,
                "library": result.library,
                "destination": result.destination,
                "added": result.added,
                "parents": result.parents,
                "changed": changed,
            }
        )
        return
    status = PLAN if dry_run and result.plan.changes else (DONE if changed else UNCHANGED)
    console().print(
        status_line(status, f"sprouted {source.symbol} into {short_path(result.destination)}")
    )


def _snapshot_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {
        ".DS_Store",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
    return {
        name
        for name in names
        if name in ignored
        or name.endswith("-backups")
        or name.startswith("_autosave")
        or (name.startswith("~") and name.endswith(".lck"))
        or re.search(r"\.bak(?:\.\d+)?$", name) is not None
    }


def _snapshot_paths(root: Path, destination: Path) -> tuple[Path, Path]:
    source_dir = root.parent.resolve()
    target = destination.resolve()
    if destination.is_symlink() or target.exists():
        raise WorkflowError(f"snapshot destination already exists: {target}")
    if target.is_relative_to(source_dir):
        raise WorkflowError("snapshot destination must be outside the source project")
    return source_dir, target


def _create_snapshot(root: Path, destination: Path) -> tuple[Path, SealResult]:
    source_dir, target = _snapshot_paths(root, destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        # Preserve links instead of following them into unrelated directories;
        # verification will reject any linked symbol source that escapes.
        shutil.copytree(
            source_dir,
            temporary,
            dirs_exist_ok=True,
            symlinks=True,
            ignore=_snapshot_ignore,
        )
        copied_root = temporary / root.name
        result = plan_seal(copied_root)
        result.plan.apply()
        for backup in temporary.rglob("*"):
            if backup.is_file() and re.search(r"\.bak(?:\.\d+)?$", backup.name):
                backup.unlink()
        report = verify_project(copied_root)
        if not report.ok:
            messages = "; ".join(item.message for item in report.diagnostics)
            raise WorkflowError(f"snapshot verification failed: {messages}")
        os.replace(temporary, target)
        return target / root.name, result
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def seal(
    root: Path | None = typer.Argument(
        None,
        help="Root .kicad_sch or project directory; defaults to the project here.",
    ),
    snapshot: Path | None = typer.Option(
        None,
        "--snapshot",
        help=("Create and seal a namespaced handoff copy without changing the working project."),
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
) -> None:
    """Finalize the project so every used symbol source travels with it."""
    project = resolve_root(root)
    if snapshot is not None:
        destination = snapshot.expanduser()
        if dry_run:
            try:
                _snapshot_paths(project, destination)
                preview = plan_seal(project)
            except (
                OSError,
                ValueError,
                SExprError,
                SymbolConflictError,
                MutationError,
            ) as error:
                fail(str(error), code=2)
            if runtime.json_output:
                emit_json(
                    {
                        "ok": True,
                        "dry_run": True,
                        "snapshot": str(destination),
                        "source": str(project.parent),
                        "libraries": preview.libraries,
                    }
                )
            else:
                console().print(status_line(PLAN, f"create verified snapshot at {destination}"))
            return
        try:
            copied_root, result = _create_snapshot(project, destination)
        except (OSError, ValueError, SExprError, MutationError) as error:
            fail(str(error), code=2)
        if runtime.json_output:
            emit_json({"ok": True, "snapshot": str(destination), "root": str(copied_root)})
        else:
            console().print(status_line(DONE, f"sealed snapshot at {short_path(destination)}"))
        return

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
    if runtime.json_output:
        emit_json(
            {
                "ok": True,
                "dry_run": dry_run,
                "libraries": result.libraries,
                "rewritten": result.rewritten,
                "backups_created": 0 if dry_run else backup_count,
                "changed": changed,
            }
        )
        return
    for library in result.libraries:
        status = PLAN if dry_run and library.changed else (DONE if library.changed else UNCHANGED)
        migrated = [source for source in library.sources if source != library.nickname]
        label = f"{', '.join(migrated)} -> {library.nickname}" if migrated else library.nickname
        console().print(
            status_line(
                status,
                f"{label}: {library.used} used, {library.kept} definitions",
            )
        )
    if not result.libraries:
        console().print(status_line(UNCHANGED, "project uses no external symbol definitions"))
    elif not dry_run:
        console().print(
            status_line(DONE if changed else UNCHANGED, "project symbol sources are sealed")
        )
        if backup_count:
            console().print(status_line(DONE, f"{backup_count} adjacent recovery backups created"))


def prune(
    root: Path | None = typer.Argument(None, help="Project; defaults to the project here."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
    precise: bool = typer.Option(False, "--precise", help="List removed symbol names."),
) -> None:
    """Remove unused definitions from registered project-local packed libraries."""
    project = resolve_root(root)
    try:
        result = plan_prune(project)
    except (OSError, UnicodeError, ValueError, SExprError, MutationError) as error:
        fail(str(error), code=2)
    changed = apply_plan(result.plan, dry_run=dry_run)
    if runtime.json_output:
        emit_json(
            {
                "ok": True,
                "dry_run": dry_run,
                "removed": result.removed,
                "dropped": result.dropped,
                "changed": changed,
            }
        )
        return
    for library, names in result.removed.items():
        detail = f": {escape(', '.join(names))}" if precise else ""
        console().print(f"  {escape(library)}: {len(names)} removed{detail}")
    total = sum(len(names) for names in result.removed.values())
    status = PLAN if dry_run and total else (DONE if changed else UNCHANGED)
    console().print(status_line(status, f"{total} unused symbol definitions"))


def graft(
    root: Path | None = typer.Argument(None, help="Project; defaults to the project here."),
    old_library: str = typer.Option(..., "--old", help="Exact nickname to replace."),
    new_library: str = typer.Option(..., "--new", help="Exact replacement nickname."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
) -> None:
    """Deliberately rename library references in placed and cached symbols."""
    project = resolve_root(root)
    try:
        result = plan_graft(project, old_library, new_library)
    except (OSError, UnicodeError, ValueError, SExprError, MutationError) as error:
        fail(str(error), code=2)
    changed = apply_plan(result.plan, dry_run=dry_run)
    total = sum(count for _path, count in result.changed)
    if runtime.json_output:
        emit_json(
            {
                "ok": True,
                "dry_run": dry_run,
                "old": old_library,
                "new": new_library,
                "references": total,
                "files": result.changed,
                "changed": changed,
            }
        )
        return
    status = PLAN if dry_run and total else (DONE if changed else UNCHANGED)
    console().print(status_line(status, f"{total} references: {old_library} -> {new_library}"))


def _pluck(
    symbol: str,
    src_file: Path,
    root: Path,
    curated: Path | None = None,
    as_lib: str | None = None,
    dry_run: bool = False,
) -> None:
    """Compatibility helper used by the interactive browser and API tests."""
    del curated
    source = _choose_source(src_file, symbol, None)
    _execute_pluck(source, root, as_library=as_lib, dry_run=dry_run)


def _sprout(symbol: str, src_file: Path, curated: Path, dry_run: bool = False) -> None:
    """Compatibility helper used by the interactive browser and API tests."""
    source = _choose_source(src_file, symbol, None)
    _execute_sprout(source, curated, dry_run=dry_run)


def register(app: typer.Typer) -> None:
    app.command("list")(list_)
    app.command()(pluck)
    app.command()(sprout)
    app.command()(seal)
    app.command()(prune)
    app.command()(graft)
