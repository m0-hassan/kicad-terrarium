import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import typer
from pyfiglet import figlet_format
from rich.console import Console
from rich.text import Text

from kicad_terrarium import __version__
from kicad_terrarium.core.audit import (
    cache_symbol_pins,
    foreign_model_paths,
    missing_pads,
    pad_names,
)
from kicad_terrarium.core.browse import Browser, Item, Screen
from kicad_terrarium.core.config import CONFIG_PATH, Config, dump_config, load_config
from kicad_terrarium.core.discover import (
    library_counts,
    reassign_footprints,
    symbol_instances,
    used_symbols,
)
from kicad_terrarium.core.extract import (
    library_version,
    merge_symbols,
    pluck_symbols,
    prune_library,
    symbol_blocks,
    vendor_library,
)
from kicad_terrarium.core.project import project_lib_ids, project_schematics
from kicad_terrarium.core.repoint import repoint_text
from kicad_terrarium.core.resolve import resolve_footprint_libs, resolve_libraries
from kicad_terrarium.core.sizing import INDUCTOR_SYMBOLS, footprint_for, rules_from_config
from kicad_terrarium.core.tables import merge_sym_lib_table, remove_from_sym_lib_table
from kicad_terrarium.core.verify import external_libraries, registered_libraries

# The typer "app" is the container all of our commands attach to.
# Our pyproject entry point calls this object to launch the CLI.

app = typer.Typer(
    name="kicad-terrarium",
    help="Make KiCad projects reproducibly self-contained.",
)

console = Console()

# "sunset" gradient for figlet

PALETTE = ["#ff5f6d", "#ff8a5b", "#ffc371"]


def line_colors(num_lines: int, palette: list[str]) -> list[str]:
    """Return one color per line so 'palette' sweeps evenly top -> bottom

    Example: line_colors(6, ["a", "b", "c"]) -> ["a", "a", "b", "b", "c", "c"]
    """
    colors = []
    for i in range(num_lines):
        index = i * len(palette) // num_lines
        colors.append(palette[index])
    return colors


def render_banner() -> Text:
    """Turn the word 'terrarium' into gradient-colored figlet art."""
    art = figlet_format("terrarium", font="slant")
    lines = art.rstrip("\n").split("\n")
    colors = line_colors(len(lines), PALETTE)
    text = Text()
    for line, color in zip(lines, colors, strict=True):
        text.append(line + "\n", style=color)
    return text


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Runs before any subcommand. With no subcommand, show the banner."""
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty():  # only drawing to a real terminal
            console.print(render_banner())
        console.print(f"kicad-terrarium v{__version__} - it's alive!")


@app.command()
def scan(
    path: Path | None = typer.Argument(
        None, help="A .kicad_sch to inspect. Defaults to the project in this directory."
    ),
    precise: bool = typer.Option(
        False, "--precise", help="List the exact symbol names used, not just per-library counts."
    ),
) -> None:
    """
    Report libraries used across a schematic and all its sub-sheets.

    With --precise, list the exact symbol names too — handy for spelling a
    name correctly before `pluck`.
    """
    path = _resolve_root(path)
    sheets = project_schematics(path)
    all_ids = project_lib_ids(path)
    counts = library_counts(all_ids)
    total = sum(counts.values())

    console.print(
        f"[bold]{path.name}[/bold] (+{len(sheets) - 1} sub-sheets) - "
        f"{len(counts)} libraries across {total} symbols:"
    )

    if not precise:
        for lib, n in counts.most_common():
            console.print(f"  • {lib}: {n}")
        return

    names_by_lib: dict[str, set[str]] = {}
    for lib_id in all_ids:
        lib, _, symbol = lib_id.partition(":")
        names_by_lib.setdefault(lib, set()).add(symbol)
    for lib, n in counts.most_common():
        console.print(f"  [bold]{lib}[/bold] ({n})")
        for symbol in sorted(names_by_lib[lib]):
            console.print(f"    {symbol}")


@app.command()
def seal(
    root: Path | None = typer.Argument(
        None, help="Root .kicad_sch. Defaults to the project in the current directory."
    ),
    source: Path | None = typer.Option(
        None, "--source", help="Override: seal one library from this .kicad_sym."
    ),
    library: str | None = typer.Option(None, "--library", help="Override: that library's name."),
    output: Path | None = typer.Option(None, "--output", help="Override: where to write it."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would happen, write nothing."
    ),
) -> None:
    """Seal every library the project uses into ./library and register it.

    ("Sealing" is *vendoring* in software terms: copy your dependencies in so
    the project no longer relies on the outside world.) Reads the project and
    global sym-lib-tables to find each library's source, copies the used
    symbols (plus inherited parents) byte-for-byte, and registers the copies
    under their original names so they shadow the originals — no schematic
    reference is rewritten. Libraries with no table entry are reported as
    orphaned, and can be sealed one at a time with --source/--library/--output.
    """
    root = _resolve_root(root)
    all_ids = project_lib_ids(root)

    if source or library or output:
        if not (source and library and output):
            console.print("[red]--source, --library and --output must be given together.[/red]")
            raise typer.Exit(code=2)
        _seal_one(source, used_symbols(all_ids, library), library, output, dry_run)
        return

    project_dir = root.parent
    lib_map = resolve_libraries(project_dir)
    sealed: list[str] = []
    orphaned: list[str] = []

    for lib_name, n_refs in sorted(library_counts(all_ids).items()):
        src_path = lib_map.get(lib_name)
        if src_path is None:
            orphaned.append(lib_name)
            continue
        if project_dir in src_path.parents:
            console.print(f"{lib_name}: already project-local ({n_refs} refs) - skipped")
            continue
        out_path = project_dir / "library" / f"{lib_name}.kicad_sym"
        _seal_one(src_path, used_symbols(all_ids, lib_name), lib_name, out_path, dry_run)
        sealed.append(lib_name)

    if sealed and not dry_run:
        table_path = project_dir / "sym-lib-table"
        existing = table_path.read_text() if table_path.exists() else None
        if existing is not None:
            table_path.with_suffix(".bak").write_text(existing)
        table_path.write_text(merge_sym_lib_table(existing, sealed))
        console.print(f"[green]✓ registered {len(sealed)} libraries in sym-lib-table[/green]")

    if orphaned:
        console.print(f"[yellow]⚠ orphaned (no table entry, not sealed):[/yellow] {orphaned}")
        console.print("  seal these manually with --source/--library/--output.")
    if not dry_run:
        console.print("run [bold]verify[/bold] to confirm the project is self-contained.")


def _seal_one(source: Path, wanted: set[str], library: str, output: Path, dry_run: bool) -> None:
    """Seal one library file; shared by auto and manual modes."""
    lib_text, kept, missing = vendor_library(source.read_text(), wanted)

    parents = len(kept) - len(wanted - missing)  # kept beyond the found wanted = parents pulled in
    note = f" (+{parents} inherited parents)" if parents else ""
    console.print(f"[bold]{library}[/bold]: {len(wanted)} used -> {len(kept)} symbols{note}")
    if missing:
        console.print(f"  [red]⚠ missing from source:[/red] {sorted(missing)}")
    if dry_run:
        console.print(f"  [yellow](dry-run) would write {output}[/yellow]")
        return

    if output.exists():
        output.with_suffix(output.suffix + ".bak").write_bytes(output.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(lib_text)
    console.print(f"  [green]✓ wrote {output}[/green]")


@app.command()
def graft(
    root: Path | None = typer.Argument(
        None, help="Root .kicad_sch (this rewrites files). Defaults to the project here."
    ),
    old_library: str = typer.Option(..., "--old", help="Library name to replace."),
    new_library: str = typer.Option(..., "--new", help="Library name to use instead."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; change nothing."),
) -> None:
    """Graft references from one library name onto another across all sheets.

    Advanced/niche: rewrites the library-name part of every reference (both
    placed instances and the lib_symbols cache), like grafting a plant onto
    new roots. It does NOT create or move the target library — that's on you.
    The normal `seal` workflow keeps original names, so you rarely need this;
    it's here for deliberately renaming or merging libraries.
    """
    root = _resolve_root(root)
    total = 0
    for sheet in project_schematics(root):
        new_text, n = repoint_text(sheet.read_text(), old_library, new_library)
        total += n

        if n and not dry_run:
            backup = sheet.with_suffix(sheet.suffix + ".bak")  # power.kicad_sch.bak
            backup.write_bytes(sheet.read_bytes())  # safety net first
            sheet.write_text(new_text)  # then overwrite

        note = (
            "" if not n else (" -> rewritten (.bak saved)" if not dry_run else " (would rewrite)")
        )
        console.print(f"{sheet.name}: {n}{note}")

    verb = "Would rewrite" if dry_run else "Rewrote"
    tag = " [yellow](dry-run)[/yellow]" if dry_run else ""
    console.print(f"[bold]{verb} {total} references[/bold] '{old_library}' -> '{new_library}'{tag}")


def _find_project_root(directory: Path) -> Path | None:
    """The root .kicad_sch of the KiCad project in `directory`, if exactly one."""
    pros = sorted(directory.glob("*.kicad_pro"))
    if len(pros) != 1:
        return None
    root = pros[0].with_suffix(".kicad_sch")
    return root if root.is_file() else None


def _resolve_root(root: Path | None) -> Path:
    """A given root .kicad_sch, or the project in the current directory.

    Lets `seal`, `verify`, `scan`, `fit`, `audit` be run bare from inside a
    project (like git), instead of always retyping the schematic path.
    """
    if root is not None:
        if not root.is_file():
            console.print(f"[red]{root} not found.[/red]")
            raise typer.Exit(code=2)
        return root
    found = _find_project_root(Path.cwd())
    if found is None:
        console.print("[red]no .kicad_sch given and no single project in this directory.[/red]")
        raise typer.Exit(code=2)
    return found


def _local_libraries(project_dir: Path) -> list[Path]:
    """The .kicad_sym files under a project's library/ folder."""
    lib_dir = project_dir / "library"
    return sorted(lib_dir.glob("*.kicad_sym")) if lib_dir.is_dir() else []


def _find_projects(roots: list[Path]) -> list[Path]:
    """.kicad_pro files under the roots, skipping backup and autosave copies."""
    projects = []
    for root_dir in roots:
        if not root_dir.is_dir():
            continue
        for pro in sorted(root_dir.glob("**/*.kicad_pro")):
            if any(
                parent.name.endswith("-backups") or parent.name.startswith("_autosave")
                for parent in pro.parents
            ):
                continue
            projects.append(pro)
    return projects


def _source_files(source: Path) -> list[Path]:
    """The .kicad_sym files a source target offers: itself, or a project's libs."""
    if source.is_file() and source.suffix == ".kicad_sym":
        return [source]
    project_dir = source if source.is_dir() else source.parent
    return _local_libraries(project_dir)


def _find_symbol_source(source: Path, symbol: str) -> Path | None:
    """The .kicad_sym under `source` that defines `symbol`, or None."""
    return next((f for f in _source_files(source) if symbol in symbol_blocks(f.read_text())), None)


@app.command("list")
def list_(
    target: Path | None = typer.Argument(
        None, help="A .kicad_sym file or a project. Omit to list configured projects."
    ),
) -> None:
    """List projects, or the symbols available in a library or project."""
    if target is None:
        roots = load_config().project_roots
        if not roots:
            console.print(f"No project roots configured. Add some to {CONFIG_PATH}:")
            console.print('  {"project_roots": ["~/path/to/projects"]}')
            raise typer.Exit(code=1)
        for pro in _find_projects(roots):
            console.print(f"  {pro.stem}  [dim]{pro.parent}[/dim]")
        return

    if target.is_file() and target.suffix == ".kicad_sym":
        for name in sorted(symbol_blocks(target.read_text())):
            console.print(f"  {name}")
        return

    libs = _local_libraries(target if target.is_dir() else target.parent)
    if not libs:
        console.print(f"[yellow]no local libraries found for {target}[/yellow]")
        return
    for lib in libs:
        names = sorted(symbol_blocks(lib.read_text()))
        console.print(f"[bold]{lib.stem}[/bold] ({len(names)})")
        for name in names:
            console.print(f"  {name}")


@app.command()
def pluck(
    symbol: str = typer.Argument(..., help="Symbol name to copy into the project."),
    from_: Path | None = typer.Option(
        None, "--from", help="Source .kicad_sym or project. Default: your vault."
    ),
    into: Path | None = typer.Option(
        None, "--into", help="Destination project root .kicad_sch. Default: the project here."
    ),
    as_lib: str | None = typer.Option(
        None, "--as", help="Destination library name. Default: the source library's name."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; write nothing."),
) -> None:
    """Copy a named symbol (and any inherited parents) into a project's library.

    Vendor works backward from what a project already uses; pluck works
    forward from intent, pulling a symbol in *before* you place it — so you
    never have to mine an old project or open KiCad just to reuse a part.
    """
    config = load_config()
    source = from_ or config.curated_library
    if source is None:
        console.print("[red]no --from given and no vault configured — run 'kt init'.[/red]")
        raise typer.Exit(code=2)

    src_file = _find_symbol_source(source, symbol)
    if src_file is None:
        console.print(f"[red]symbol '{symbol}' not found in {source}[/red]")
        raise typer.Exit(code=1)

    root = into or _find_project_root(Path.cwd())
    if root is None:
        console.print("[red]no --into given and no single project in the current directory.[/red]")
        raise typer.Exit(code=2)

    _pluck(symbol, src_file, root, config.curated_library, as_lib, dry_run)


def _short(path: Path) -> str:
    """Path with the home directory abbreviated to ~, so lines don't wrap."""
    text, home = str(path), str(Path.home())
    return "~" + text[len(home) :] if text.startswith(home) else text


def _source_label(src_file: Path, curated: Path | None) -> str:
    """A human tag for where a symbol came from: the vault, or a project."""
    if curated is not None and src_file.resolve() == curated.resolve():
        return f"vault · {src_file.name}"
    if src_file.parent.name == "library":  # a project's local library folder
        return f"project {src_file.parent.parent.name} · {src_file.name}"
    return _short(src_file)


def _result_line(added: list[str]) -> str:
    if added:
        return f"  [green]✓ wrote {len(added)} symbol{'s' if len(added) != 1 else ''}[/green]"
    return "  [dim]· already present — nothing changed[/dim]"


def _pluck(
    symbol: str,
    src_file: Path,
    root: Path,
    curated: Path | None = None,
    as_lib: str | None = None,
    dry_run: bool = False,
) -> None:
    """Copy `symbol` (and inherited parents) from src_file down into root's project."""
    source_text = src_file.read_text()
    additions, missing = pluck_symbols(source_text, {symbol})
    if missing:
        console.print(f"[red]⚠ missing from source: {sorted(missing)}[/red]")
        raise typer.Exit(code=1)

    lib_name = as_lib or src_file.stem
    parents = sorted(set(additions) - {symbol})
    note = f" (+ {', '.join(parents)})" if parents else ""
    console.print(f"[bold]plucked[/bold] '{symbol}'{note}")
    console.print(f"  from  {_source_label(src_file, curated)}")
    console.print(f"  into  {root.parent.name}/library/{lib_name}.kicad_sym")
    if dry_run:
        console.print("  [yellow](dry-run) nothing written[/yellow]")
        return

    dest_file = root.parent / "library" / f"{lib_name}.kicad_sym"
    dest_text = dest_file.read_text() if dest_file.exists() else None
    if dest_text is not None:
        dest_file.with_suffix(".kicad_sym.bak").write_bytes(dest_file.read_bytes())
    new_text, added = merge_symbols(dest_text, additions, library_version(source_text))
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    dest_file.write_text(new_text)

    table = root.parent / "sym-lib-table"
    existing = table.read_text() if table.exists() else None
    if existing is not None:
        table.with_suffix(".bak").write_text(existing)
    table.write_text(merge_sym_lib_table(existing, [lib_name]))
    console.print(_result_line(added))


@app.command()
def sprout(
    symbol: str = typer.Argument(..., help="Symbol to add to your vault."),
    from_: Path | None = typer.Option(
        None, "--from", help="Source project or .kicad_sym. Default: the project here."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; write nothing."),
) -> None:
    """Sprout a symbol up into your vault, to reuse across projects.

    The mirror of `pluck`: pluck pulls a symbol down into a project; sprout
    pushes one up into your growing collection. Grow it from real reuse — the
    moment you think "I'll want this again."
    """
    curated = load_config().curated_library
    if curated is None:
        console.print("[red]no vault configured — run 'kt init' first.[/red]")
        raise typer.Exit(code=2)

    source = from_ or _find_project_root(Path.cwd())
    if source is None:
        console.print("[red]no --from given and no single project in this directory.[/red]")
        raise typer.Exit(code=2)
    src_file = _find_symbol_source(source, symbol)
    if src_file is None:
        console.print(f"[red]symbol '{symbol}' not found in {source}[/red]")
        raise typer.Exit(code=1)

    _sprout(symbol, src_file, curated, dry_run)


def _sprout(symbol: str, src_file: Path, curated: Path, dry_run: bool = False) -> None:
    """Copy `symbol` (and inherited parents) from src_file into the vault."""
    source_text = src_file.read_text()
    additions, missing = pluck_symbols(source_text, {symbol})
    if missing:
        console.print(f"[red]⚠ missing from source: {sorted(missing)}[/red]")
        raise typer.Exit(code=1)

    parents = sorted(set(additions) - {symbol})
    note = f" (+ {', '.join(parents)})" if parents else ""
    console.print(f"[bold]sprouted[/bold] '{symbol}'{note}")
    console.print(f"  from  {_source_label(src_file, curated)}")
    console.print(f"  into  vault · {curated.name}  ({_short(curated.parent)}/)")
    if dry_run:
        console.print("  [yellow](dry-run) nothing written[/yellow]")
        return

    dest_text = curated.read_text() if curated.exists() else None
    if dest_text is not None:
        curated.with_suffix(".kicad_sym.bak").write_bytes(curated.read_bytes())
    new_text, added = merge_symbols(dest_text, additions, library_version(source_text))
    curated.parent.mkdir(parents=True, exist_ok=True)
    curated.write_text(new_text)
    console.print(_result_line(added))


@dataclass(frozen=True)
class _PluckAction:
    """A menu leaf's payload: copy `symbol` from `source` down into the project."""

    symbol: str
    source: Path


@dataclass(frozen=True)
class _SproutAction:
    """A menu leaf's payload: copy `symbol` from `source` up into the vault."""

    symbol: str
    source: Path


def _curated_items(lib_file: Path) -> list[Item]:
    """Curated-library symbols: pluck-only (sprouting into the curated lib is a no-op)."""
    return [
        Item(name, action=_PluckAction(name, lib_file))
        for name in sorted(symbol_blocks(lib_file.read_text()))
    ]


def _project_items(lib_file: Path, dest_name: str, curated_name: str | None) -> list[Item]:
    """Project symbols: each opens a pluck-here / sprout-up choice."""
    items = []
    for name in sorted(symbol_blocks(lib_file.read_text())):
        choices = [Item(f"Pluck into {dest_name}", action=_PluckAction(name, lib_file))]
        if curated_name is not None:
            choices.append(
                Item(f"Sprout into {curated_name}", action=_SproutAction(name, lib_file))
            )
        items.append(Item(f"{name}  [{lib_file.stem}]", children=choices))
    return items


def _build_browse_tree(
    config_curated: Path | None,
    project_roots: list[Path],
    dest_name: str,
    exclude: Path | None = None,
) -> Screen:
    """The source-browsing menu: vault and projects → their symbols.

    Curated symbols pluck straight into the destination project. Project
    symbols open a choice: pluck them here, or sprout them up into the curated
    library. `exclude` (the destination project) is left out of the sources —
    plucking a project into itself is a no-op.
    """
    curated_name = config_curated.stem if config_curated else None
    top: list[Item] = []
    if config_curated and config_curated.is_file():
        top.append(Item("Vault", children=_curated_items(config_curated)))
    projects: list[Item] = []
    for pro in _find_projects(project_roots):
        if exclude is not None and pro.parent.resolve() == exclude.resolve():
            continue
        symbols: list[Item] = []
        for lib in _local_libraries(pro.parent):
            symbols += _project_items(lib, dest_name, curated_name)
        if symbols:
            projects.append(Item(pro.parent.name, children=symbols))  # folder disambiguates
    if projects:
        top.append(Item("Projects", children=projects))
    return Screen(f"kicad-terrarium — into {dest_name}", top)


# a little potted sprout swaying in a breeze, bottom-right of the menu:
# center, lean-right, center, lean-left
_PLANT_FRAMES = [
    [" ,(), ", "  \\|/ ", "   |  ", "  \\_/ "],
    [" ,(), ", "   \\|/", "   |  ", "  \\_/ "],
    [" ,(), ", "  \\|/ ", "   |  ", "  \\_/ "],
    [" ,(), ", "  \\|/ ", "  \\|  ", "  \\_/ "],
]


def _draw_plant(stdscr, height: int, width: int, frame: int) -> None:
    """Draw the swaying sprout in the bottom-right corner, if it fits."""
    import curses

    art = _PLANT_FRAMES[frame % len(_PLANT_FRAMES)]
    art_w = max(len(line) for line in art)
    if height < len(art) + 6 or width < art_w + 2:  # too small — skip gracefully
        return
    top, left = height - len(art) - 1, width - art_w - 1
    for i, line in enumerate(art):
        try:
            stdscr.addnstr(top + i, left, line, art_w, curses.A_DIM)
        except Exception:  # writing the last cell can raise; harmless
            pass


def _run_browser(root: Screen) -> object | None:
    """Drive the curses menu; return the chosen leaf action, or None."""
    import curses

    picked: list[object] = []

    def loop(stdscr) -> None:
        curses.curs_set(0)
        stdscr.timeout(450)  # ms: wake to sway the plant even without a keypress
        browser = Browser(root)
        frame = 0
        while True:
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            screen = browser.screen
            rows = max(1, height - 4)
            start = max(0, min(screen.cursor - rows // 2, len(screen.items) - rows))
            stdscr.addnstr(0, 0, screen.title, width - 1, curses.A_BOLD)
            for row, item in enumerate(screen.items[start : start + rows]):
                selected = start + row == screen.cursor
                marker = "› " if selected else "  "
                arrow = " ›" if item.children is not None else ""
                stdscr.addnstr(
                    row + 2,
                    0,
                    f"{marker}{item.label}{arrow}",
                    width - 1,
                    curses.A_REVERSE if selected else curses.A_NORMAL,
                )
            stdscr.addnstr(height - 1, 0, "↑↓ move · ⏎ select · ← back · q quit", width - 1)
            _draw_plant(stdscr, height, width, frame)
            key = stdscr.getch()
            if key == -1:  # timeout: no input, just let the plant sway
                frame += 1
                continue
            if key in (ord("q"), 27):  # q or Esc
                return
            if key in (curses.KEY_UP, ord("k")):
                browser.move(-1)
            elif key in (curses.KEY_DOWN, ord("j")):
                browser.move(1)
            elif key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 8):
                browser.back()
            elif key in (curses.KEY_ENTER, 10, 13):
                action = browser.enter()
                if action is not None:
                    picked.append(action)
                    return

    curses.wrapper(loop)
    return picked[0] if picked else None


@app.command()
def browse(
    into: Path | None = typer.Option(
        None, "--into", help="Project to pluck into. Default: the project in this directory."
    ),
) -> None:
    """Interactive menu: browse your libraries and projects, pluck a symbol.

    A thin shell over `list` and `pluck` — everything it does is also a
    flag-driven command, so scripts never need the menu.
    """
    if not sys.stdout.isatty():
        console.print(
            "[red]browse needs an interactive terminal — use 'list', 'pluck', 'sprout'.[/red]"
        )
        raise typer.Exit(code=2)
    root = _resolve_root(into)

    config = load_config()
    # exclude the destination project from the sources — plucking a project
    # into itself is always a no-op and only causes confusion.
    tree = _build_browse_tree(
        config.curated_library, config.project_roots, root.parent.name, exclude=root.parent
    )
    if not tree.items:
        console.print(f"nothing to browse — set curated_library / project_roots in {CONFIG_PATH}.")
        raise typer.Exit(code=1)

    action = _run_browser(tree)
    if isinstance(action, _PluckAction):
        _pluck(action.symbol, action.source, root, config.curated_library)
    elif isinstance(action, _SproutAction):
        if config.curated_library is None:
            console.print("[red]no vault configured — run 'kt init'.[/red]")
            raise typer.Exit(code=2)
        _sprout(action.symbol, action.source, config.curated_library)
    else:
        console.print("[dim]nothing done.[/dim]")


_EMPTY_LIBRARY = '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "kicad-terrarium")\n)\n'


@app.command()
def init() -> None:
    """Set up kicad-terrarium: your vault and where your projects live.

    Writes ~/.config/kicad-terrarium/config.json. Both fields are optional —
    press Enter to skip either.
    """
    if not sys.stdin.isatty():
        console.print(f"[red]init is interactive; edit {CONFIG_PATH} directly instead.[/red]")
        raise typer.Exit(code=2)

    console.print("[bold]kicad-terrarium setup[/bold] — press Enter to skip a field.\n")
    existing = load_config()

    # Suggest a professional, descriptive default: the vault's name
    # propagates into every project that uses it (shadow keeps original names),
    # so a personal handle would leak into shared repos. Neutral name instead.
    suggested = Path.home() / "Documents/KiCad/libraries/custom_symbols.kicad_sym"
    lib_default = str(existing.curated_library or suggested)
    lib_in = typer.prompt(
        "Your vault — a .kicad_sym of reusable parts you carry across projects",
        default=lib_default,
    ).strip()
    curated = Path(lib_in).expanduser() if lib_in else None
    if (
        curated
        and not curated.exists()
        and typer.confirm(f"{curated} doesn't exist — create an empty library there?", default=True)
    ):
        curated.parent.mkdir(parents=True, exist_ok=True)
        curated.write_text(_EMPTY_LIBRARY)
        console.print(f"[green]created {curated}[/green]")

    roots_default = ", ".join(str(p) for p in existing.project_roots)
    roots_in = typer.prompt(
        "Folder(s) holding your KiCad projects, comma-separated",
        default=roots_default,
        show_default=bool(roots_default),
    )
    roots = [Path(r.strip()).expanduser() for r in roots_in.split(",") if r.strip()]

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(dump_config(Config(curated, roots, existing.sizing)))
    console.print(f"\n[green]✓ wrote {CONFIG_PATH}[/green]")
    console.print("Try [bold]kt list[/bold] to see your projects, or [bold]kt browse[/bold].")


@app.command()
def fit(
    root: Path | None = typer.Argument(
        None, help="Root .kicad_sch. Defaults to the project in this directory."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; write nothing."),
    precise: bool = typer.Option(
        False, "--precise", help="List every part, not just per-package counts."
    ),
) -> None:
    """Fit footprints to unassigned resistors and capacitors by value.

    Uses a value table (0603 up to 1 µF, 0805 above; all resistors 0603 by
    default — override under "sizing" in the config). Only fills empty
    footprints; never overwrites. Inductors are left alone on purpose:
    their package depends on saturation current, which is your call.
    """
    root = _resolve_root(root)
    rules = rules_from_config(load_config().sizing)

    def decide(ref: str, lib_id: str, value: str, current: str) -> str | None:
        return None if current else footprint_for(lib_id, value, rules)

    applied: list[tuple[str, str]] = []
    inductors: set[str] = set()
    for sheet in project_schematics(root):
        text = sheet.read_text()
        new_text, changed = reassign_footprints(text, decide)
        changed = sorted(set(changed))  # multi-unit symbols count once
        applied += changed
        if changed and not dry_run:
            sheet.with_suffix(sheet.suffix + ".bak").write_bytes(sheet.read_bytes())
            sheet.write_text(new_text)
        inductors |= {
            ref
            for ref, lib_id, fp in symbol_instances(text)
            if not fp and lib_id.split(":", 1)[-1] in INDUCTOR_SYMBOLS
        }

    if precise:
        for ref, fp in sorted(applied):
            console.print(f"  {ref} → {fp.split(':', 1)[-1]}")
    else:  # compressed: one line per package, so 100 passives don't flood
        for fp, n in sorted(Counter(fp for _, fp in applied).items()):
            console.print(f"  {n:>3} × {fp.split(':', 1)[-1]}")

    verb = "would assign" if dry_run else "assigned"
    tag = " [yellow](dry-run)[/yellow]" if dry_run else ""
    hint = "" if precise or not applied else "  [dim](--precise for the full list)[/dim]"
    n = len(applied)
    console.print(f"[bold]{verb} {n} footprint{'s' if n != 1 else ''}[/bold]{tag}{hint}")
    if inductors:
        console.print(
            f"[dim]left for you: {sorted(inductors)} — inductor package depends on "
            f"saturation current, not value.[/dim]"
        )
    if not dry_run and applied:
        console.print("run [bold]audit[/bold] to check pin/pad consistency.")


@app.command()
def prune(
    root: Path | None = typer.Argument(
        None, help="Root .kicad_sch. Defaults to the project in this directory."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; write nothing."),
    precise: bool = typer.Option(
        False, "--precise", help="List the removed symbol names, not just counts."
    ),
) -> None:
    """Trim project-local libraries to exactly the symbols the schematic uses.

    Removes symbols left behind by plucking-and-not-placing (inherited parents
    are kept), and drops any library that ends up entirely unused — so a
    project stays minimal no matter how much you explored.
    """
    root = _resolve_root(root)
    project_dir = root.parent
    all_ids = project_lib_ids(root)

    removed_total = 0
    dropped: list[str] = []
    for lib_file in _local_libraries(project_dir):
        used = used_symbols(all_ids, lib_file.stem)
        new_text, kept, removed = prune_library(lib_file.read_text(), used)
        if not removed:
            continue
        removed_total += len(removed)
        detail = f": {removed}" if precise else ""
        if kept:
            console.print(f"  {lib_file.stem}: kept {len(kept)}, removed {len(removed)}{detail}")
        else:
            dropped.append(lib_file.stem)
            console.print(f"  {lib_file.stem}: [yellow]dropped[/yellow] (nothing used){detail}")
        if not dry_run:
            lib_file.with_suffix(".kicad_sym.bak").write_bytes(lib_file.read_bytes())
            lib_file.write_text(new_text) if kept else lib_file.unlink()

    if dropped and not dry_run:
        table = project_dir / "sym-lib-table"
        if table.exists():
            existing = table.read_text()
            table.with_suffix(".bak").write_text(existing)
            table.write_text(remove_from_sym_lib_table(existing, dropped))

    if removed_total == 0:
        console.print("[green]✓ already minimal — nothing to prune.[/green]")
        return
    verb = "would remove" if dry_run else "removed"
    tag = " [yellow](dry-run)[/yellow]" if dry_run else ""
    note = f", dropped {len(dropped)} empty" if dropped else ""
    plural = "s" if removed_total != 1 else ""
    console.print(f"[bold]{verb} {removed_total} unused symbol{plural}{note}[/bold]{tag}")


@app.command()
def audit(
    root: Path | None = typer.Argument(
        None, help="Root .kicad_sch to lint. Defaults to the project in this directory."
    ),
    precise: bool = typer.Option(
        False, "--precise", help="List every finding, not just the first few per category."
    ),
) -> None:
    """Read-only lint: report the mechanical gaps that bite during layout.

    Checks footprint assignment, footprint existence, symbol-pin vs
    footprint-pad consistency, orphaned sheet files, and 3D model paths
    that will not travel. Exits 1 if anything is found; safe to run while
    KiCad is open.
    """
    root = _resolve_root(root)
    sheets = project_schematics(root)
    project_dir = root.parent

    instances: list[tuple[str, str, str, str]] = []  # (sheet, ref, lib_id, footprint)
    cache: dict[str, set[str]] = {}
    for sheet in sheets:
        text = sheet.read_text()
        instances += [(sheet.name, *inst) for inst in symbol_instances(text)]
        cache.update(cache_symbol_pins(text))
    physical = [inst for inst in instances if not inst[2].startswith("power:")]

    findings = 0

    def section(title: str, rows: list[str]) -> None:
        nonlocal findings
        unique = sorted(set(rows))  # multi-unit symbols yield one row per placed unit
        if not unique:
            return
        findings += len(unique)
        console.print(f"[red]✗ {title}[/red] ({len(unique)})")
        shown = unique if precise else unique[:8]
        for row in shown:
            console.print(f"  • {row}")
        if len(unique) > len(shown):
            console.print(f"  [dim]… {len(unique) - len(shown)} more (--precise for all)[/dim]")

    section(
        "unassigned footprints",
        [f"{ref} ({lib_id}) [{sheet}]" for sheet, ref, lib_id, fp in physical if not fp],
    )

    fp_libs = resolve_footprint_libs(project_dir)
    unknown_libs, missing_mods, mismatches = [], [], []
    for _sheet, ref, lib_id, fp in physical:
        if not fp:
            continue
        lib, _, name = fp.partition(":")
        pretty = fp_libs.get(lib)
        if pretty is None:
            unknown_libs.append(f"{ref}: footprint library '{lib}' not in any fp-lib-table")
            continue
        mod = pretty / f"{name}.kicad_mod"
        if not mod.is_file():
            missing_mods.append(f"{ref}: {fp} has no .kicad_mod file")
            continue
        pins = cache.get(lib_id)
        if pins:
            missing = missing_pads(pins, pad_names(mod.read_text()))
            if missing:
                mismatches.append(f"{ref}: pins {sorted(missing)} have no pad on {fp}")
    section("unknown footprint libraries", unknown_libs)
    section("footprints without files", missing_mods)
    section("symbol pins without pads", mismatches)

    reached = {s.resolve() for s in sheets}
    section(
        "orphaned sheet files (nothing references them)",
        sorted(p.name for p in project_dir.glob("*.kicad_sch") if p.resolve() not in reached),
    )

    foreign = []
    for lib, pretty in fp_libs.items():
        if project_dir not in pretty.parents:
            continue  # only project-local libraries must be self-contained
        for mod in sorted(pretty.glob("*.kicad_mod")):
            for path in foreign_model_paths(mod.read_text()):
                foreign.append(f"{lib}:{mod.stem}: model path won't travel: {path}")
    section("3D model paths outside the project", foreign)

    if findings:
        console.print(f"[bold red]{findings} finding{'s' if findings != 1 else ''}.[/bold red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ audit clean[/green] - {len(physical)} physical symbols checked.")


@app.command()
def verify(
    root: Path | None = typer.Argument(
        None, help="Root .kicad_sch to check. Defaults to the project in this directory."
    ),
) -> None:
    """Confirm every library the project uses is registered locally."""
    root = _resolve_root(root)
    used = set(library_counts(project_lib_ids(root)))  # library names referenced

    table = root.parent / "sym-lib-table"  # the project's registration
    registered = registered_libraries(table.read_text()) if table.exists() else set()

    external = external_libraries(used, registered)

    if external:
        console.print(f"[red]✗ NOT self-contained![/red] - {len(external)} external:")
        for lib in sorted(external):
            console.print(f"  • {lib}")
        raise typer.Exit(code=1)  # <- non-zero exit = failure
    console.print(
        f"[green]✓ self-contained[/green] - {'all' if len(used) == 1 else ''} {len(used)} "
        f"librar{'y' if len(used) == 1 else 'ies'} registered locally."
    )
