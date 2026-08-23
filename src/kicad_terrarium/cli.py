import sys
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
from kicad_terrarium.core.discover import library_counts, symbol_instances, used_symbols
from kicad_terrarium.core.extract import vendor_library
from kicad_terrarium.core.project import project_lib_ids, project_schematics
from kicad_terrarium.core.repoint import repoint_text
from kicad_terrarium.core.resolve import resolve_footprint_libs, resolve_libraries
from kicad_terrarium.core.tables import merge_sym_lib_table
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
    path: Path = typer.Argument(
        ..., exists=True, readable=True, help="A .kicad_sch or .kicad_pcb file to inspect."
    ),
) -> None:
    """
    Report libraries used across a schematic and all its sub-sheets.
    """
    sheets = project_schematics(path)
    all_ids = project_lib_ids(path)
    counts = library_counts(all_ids)
    total = sum(counts.values())

    console.print(
        f"[bold]{path.name}[/bold] (+{len(sheets) - 1} sub-sheets) - "
        f"{len(counts)} libraries across {total} symbols:"
    )

    for lib, n in counts.most_common():
        console.print(f"  • {lib}: {n}")


@app.command()
def vendor(
    root: Path = typer.Argument(
        ..., exists=True, readable=True, help="Root .kicad_sch of the project."
    ),
    source: Path | None = typer.Option(
        None, "--source", help="Override: vendor one library from this .kicad_sym."
    ),
    library: str | None = typer.Option(None, "--library", help="Override: that library's name."),
    output: Path | None = typer.Option(None, "--output", help="Override: where to write it."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would happen, write nothing."
    ),
) -> None:
    """Vendor every library the project uses into ./library and register it.

    Without flags, reads the project and global sym-lib-tables to find each
    library's source file, copies the used symbols (plus inherited parents)
    byte-for-byte, and registers the copies so they shadow the originals.
    Libraries with no table entry are reported as orphaned, and can be
    vendored one at a time with --source/--library/--output.
    """
    all_ids = project_lib_ids(root)

    if source or library or output:
        if not (source and library and output):
            console.print("[red]--source, --library and --output must be given together.[/red]")
            raise typer.Exit(code=2)
        _vendor_one(source, used_symbols(all_ids, library), library, output, dry_run)
        return

    project_dir = root.parent
    lib_map = resolve_libraries(project_dir)
    vendored: list[str] = []
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
        _vendor_one(src_path, used_symbols(all_ids, lib_name), lib_name, out_path, dry_run)
        vendored.append(lib_name)

    if vendored and not dry_run:
        table_path = project_dir / "sym-lib-table"
        existing = table_path.read_text() if table_path.exists() else None
        if existing is not None:
            table_path.with_suffix(".bak").write_text(existing)
        table_path.write_text(merge_sym_lib_table(existing, vendored))
        console.print(f"[green]✓ registered {len(vendored)} libraries in sym-lib-table[/green]")

    if orphaned:
        console.print(f"[yellow]⚠ orphaned (no table entry, not vendored):[/yellow] {orphaned}")
        console.print("  vendor these manually with --source/--library/--output.")
    if not dry_run:
        console.print("run [bold]verify[/bold] to confirm the project is self-contained.")


def _vendor_one(source: Path, wanted: set[str], library: str, output: Path, dry_run: bool) -> None:
    """Vendor one library file; shared by auto and manual modes."""
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
def repoint(
    root: Path = typer.Argument(
        ..., exists=True, readable=True, help="Root .kicad_sch of a COPY (this rewrites files)."
    ),
    old_library: str = typer.Option(..., "--old", help="Library name to replace."),
    new_library: str = typer.Option(..., "--new", help="Library name to use instead."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; change nothing."),
) -> None:
    """Rewrite every lib reference from --old to --new across a project's sheets."""
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


@app.command()
def audit(
    root: Path = typer.Argument(
        ..., exists=True, readable=True, help="Root .kicad_sch of the project to lint."
    ),
) -> None:
    """Read-only lint: report the mechanical gaps that bite during layout.

    Checks footprint assignment, footprint existence, symbol-pin vs
    footprint-pad consistency, orphaned sheet files, and 3D model paths
    that will not travel. Exits 1 if anything is found; safe to run while
    KiCad is open.
    """
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
        if unique:
            findings += len(unique)
            console.print(f"[red]✗ {title}[/red] ({len(unique)})")
            for row in unique:
                console.print(f"  • {row}")

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
    root: Path = typer.Argument(
        ..., exists=True, readable=True, help="Root .kicad_sch of the project to check."
    ),
) -> None:
    """Confirm every library the project uses is registered locally."""
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
