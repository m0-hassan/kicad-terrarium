"""Interactive library browser with search."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import typer

from kicad_terrarium.commands.common import console, fail, load_user_config, resolve_root, runtime
from kicad_terrarium.commands.transfer import _execute_pluck, _execute_sprout, _find_projects
from kicad_terrarium.core.browse import Browser, Item, Screen, search_items
from kicad_terrarium.core.library import (
    LibrarySource,
    SymbolSource,
    discover_libraries,
    source_blocks,
)


@dataclass(frozen=True)
class _PluckAction:
    source: SymbolSource


@dataclass(frozen=True)
class _SproutAction:
    source: SymbolSource


def _curated_source_items(library: LibrarySource) -> list[Item]:
    return [
        Item(
            name,
            action=_PluckAction(SymbolSource(name, library)),
        )
        for name in sorted(source_blocks(library))
    ]


def _curated_items(lib_file: Path) -> list[Item]:
    """Compatibility helper for one packed vault file."""
    libraries = discover_libraries(lib_file)
    return _curated_source_items(libraries[0]) if libraries else []


def _project_source_items(
    library: LibrarySource,
    dest_name: str,
    curated_name: str | None,
) -> list[Item]:
    items: list[Item] = []
    for name in sorted(source_blocks(library)):
        choices = [
            Item(
                f"Pluck into {dest_name}",
                action=_PluckAction(SymbolSource(name, library)),
            )
        ]
        if curated_name is not None:
            choices.append(
                Item(
                    f"Sprout into {curated_name}",
                    action=_SproutAction(SymbolSource(name, library)),
                )
            )
        items.append(Item(f"{name}  [{library.nickname}]", children=choices))
    return items


def _project_items(lib_file: Path, dest_name: str, curated_name: str | None) -> list[Item]:
    """Compatibility helper for a packed project library."""
    libraries = discover_libraries(lib_file)
    return _project_source_items(libraries[0], dest_name, curated_name) if libraries else []


@dataclass
class _VaultNode:
    children: dict[str, _VaultNode] = field(default_factory=dict)
    library: LibrarySource | None = None


def _nest_vault_libraries(libraries: list[LibrarySource]) -> list[Item]:
    """Turn directory groups into navigable folder → library → symbol screens."""
    root = _VaultNode()
    for library in libraries:
        cursor = root
        for segment in library.group:
            cursor = cursor.children.setdefault(segment, _VaultNode())
        leaf = cursor.children.setdefault(library.nickname, _VaultNode())
        if leaf.library is not None:
            raise ValueError(f"duplicate vault library path: {library.label}")
        leaf.library = library

    def materialize(node: _VaultNode) -> list[Item]:
        rows: list[Item] = []
        for label, child in sorted(node.children.items()):
            nested = materialize(child)
            if child.library is not None and child.children:
                nested.insert(
                    0,
                    Item("Symbols", children=_curated_source_items(child.library)),
                )
                rows.append(Item(label, children=nested))
            elif child.library is not None:
                rows.append(Item(label, children=_curated_source_items(child.library)))
            else:
                rows.append(Item(label, children=nested))
        return rows

    return materialize(root)


def _build_browse_tree(
    config_curated: Path | None,
    project_roots: list[Path],
    dest_name: str,
    exclude: Path | None = None,
) -> Screen:
    curated_name = config_curated.stem if config_curated else None
    top: list[Item] = []
    if config_curated and config_curated.exists():
        libraries = discover_libraries(config_curated)
        if config_curated.is_file() and len(libraries) == 1:
            vault_items = _curated_source_items(libraries[0])
        else:
            vault_items = _nest_vault_libraries(libraries)
        if vault_items:
            top.append(Item("Vault", children=vault_items))

    projects: list[Item] = []
    for project in _find_projects(project_roots):
        if exclude is not None and project.parent.resolve() == exclude.resolve():
            continue
        symbols: list[Item] = []
        for library in discover_libraries(project.parent / "library"):
            symbols.extend(_project_source_items(library, dest_name, curated_name))
        if symbols:
            projects.append(Item(project.parent.name, children=symbols))
    if projects:
        top.append(Item("Projects", children=projects))
    return Screen(f"kicad-terrarium  /  into {dest_name}", top)


def _prompt_search(stdscr: Any, height: int, width: int) -> str:
    import curses

    prompt = "/ "
    stdscr.timeout(-1)
    curses.echo()
    try:
        stdscr.move(height - 1, 0)
        stdscr.clrtoeol()
        stdscr.addnstr(height - 1, 0, prompt, width - 1)
        raw = cast(
            bytes,
            stdscr.getstr(height - 1, len(prompt), max(1, width - len(prompt) - 1)),
        )
        return raw.decode(errors="replace").strip()
    finally:
        curses.noecho()
        stdscr.timeout(-1)


def _run_browser(root: Screen) -> object | None:
    """Drive navigation/search and return the selected action."""
    import curses

    picked: list[object] = []

    def loop(stdscr: Any) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        stdscr.timeout(-1)
        browser = Browser(root)
        while True:
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            if height < 8 or width < 38:
                stdscr.addnstr(0, 0, "Terminal too small (minimum 38x8). q to quit.", width - 1)
                key = stdscr.getch()
                if key in (ord("q"), 27):
                    return
                continue
            screen = browser.screen
            menu_width = width
            rows = max(1, height - 5)
            start = max(0, min(screen.cursor - rows // 2, max(0, len(screen.items) - rows)))
            stdscr.addnstr(0, 0, screen.title, menu_width - 1, curses.A_BOLD)
            if not screen.items:
                stdscr.addnstr(
                    2,
                    2,
                    "No matches. Search again with / or go back with left.",
                    menu_width - 3,
                    curses.A_DIM,
                )
            for row, item in enumerate(screen.items[start : start + rows]):
                selected = start + row == screen.cursor
                marker = "> " if selected else "  "
                arrow = " /" if item.children is not None else ""
                stdscr.addnstr(
                    row + 2,
                    0,
                    f"{marker}{item.label}{arrow}",
                    menu_width - 1,
                    curses.A_REVERSE if selected else curses.A_NORMAL,
                )
            stdscr.addnstr(
                height - 1,
                0,
                "up/down move  enter select  / search  left back  q quit",
                width - 1,
            )
            key = stdscr.getch()
            if key in (ord("q"), 27):
                return
            if key in (curses.KEY_UP, ord("k")):
                browser.move(-1)
            elif key in (curses.KEY_DOWN, ord("j")):
                browser.move(1)
            elif key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 8):
                browser.back()
            elif key == ord("/"):
                query = _prompt_search(stdscr, height, width)
                if query:
                    browser.stack.append(
                        Screen(f"search  /  {query}", search_items(root.items, query))
                    )
            elif key in (curses.KEY_ENTER, 10, 13):
                action = browser.enter()
                if action is not None:
                    picked.append(action)
                    return

    curses.wrapper(loop)
    return picked[0] if picked else None


def browse(
    into: Path | None = typer.Option(
        None,
        "--into",
        help="Destination project; defaults to the project here.",
    ),
) -> None:
    """Search and browse vault/project symbols, then pluck or sprout one."""
    if runtime.json_output:
        fail(
            "browse is interactive and cannot be combined with --json; use list/pluck/sprout",
            code=2,
        )
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        fail("browse needs an interactive input/output terminal; use list/pluck/sprout", code=2)
    root = resolve_root(into)
    config = load_user_config()
    try:
        tree = _build_browse_tree(
            config.vault,
            config.project_roots,
            root.parent.name,
            exclude=root.parent,
        )
    except (OSError, UnicodeError, ValueError) as error:
        fail(f"cannot build browser catalog: {error}", code=2)
    if not tree.items:
        fail("nothing to browse; configure a vault or project_roots with 'kt init'")
    try:
        action = _run_browser(tree)
    except ModuleNotFoundError:
        fail("this Python installation has no curses support; use list/pluck/sprout", code=2)
    if isinstance(action, _PluckAction):
        _execute_pluck(action.source, root)
    elif isinstance(action, _SproutAction):
        if config.vault is None:
            fail("no vault configured; run 'kt init'", code=2)
        _execute_sprout(action.source, config.vault)
    else:
        console().print("[dim]nothing changed[/dim]")


def register(app: typer.Typer) -> None:
    app.command()(browse)
