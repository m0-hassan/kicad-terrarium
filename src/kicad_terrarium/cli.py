import sys

import typer
from pyfiglet import figlet_format
from rich.console import Console
from rich.text import Text
from pathlib import Path
from kiutils.symbol import SymbolLib

from kicad_terrarium import __version__
from kicad_terrarium.core.discover import find_lib_ids, library_counts, used_symbols
from kicad_terrarium.core.project import project_schematics
from kicad_terrarium.core.vendor import select_symbols


# The typer "app" is the container all of our commands attach to.
# Out pyproject entry point calls this object to launch the CLI.

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
    for line, color in zip(lines, colors):
        text.append(line + "\n", style=color)
    return text

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Runs before any subcommand. With no subcommand, show the banner."""
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty(): # only drawing to a real terminal
            console.print(render_banner())
        console.print(f"kicad-terrarium v{__version__} - it's alive!")

@app.command()
def hello(name: str = "world") -> None:
    """A throwaway command to prove subcommands + arguments work."""
    console.print(f"Hello, {name}!")

@app.command()
def scan(
    path: Path = typer.Argument(...,
         exists=True,
         readable=True,
         help="A .kicad_sch or .kicad_pcb file to inspect."),
        ) -> None:
    """
    Report libraries used across a schematic and all its sub-sheets.
    """
    sheets = project_schematics(path)
    all_ids: list[str]= []
    for sheet in sheets:
        all_ids += find_lib_ids(sheet.read_text())
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
    root: Path = typer.Argument(...,
                                exists=True,
                                readable=True,
                                help="Root .kicad_sch of the project."),
    source: Path = typer.Option(...,
                                "--source",
                                exists=True,
                                readable=True,
                                help="Source .kicad_sch to pull symbols from."),
    library: str = typer.Option(...,
                                "--library",
                                help="Library name as it appears in lib_ids."),
    output: Path = typer.Option(...,
                                "--output",
                                help="Where to write the vendored .kicad_sym."),
    dry_run: bool = typer.Option(False,
                                 "--dry-run",
                                 help="Report what would happen, write nothing."),
            ) -> None:
    """Write a minimal local library containing only the symbols the project uses."""

    # 1. discover what the project uses

    all_ids: list[str] = []
    for sheet in project_schematics(root):
        all_ids += find_lib_ids(sheet.read_text())
    wanted = used_symbols(all_ids, library)

    # 2. load source, filter to what's used

    src = SymbolLib.from_file(str(source))
    kept, missing = select_symbols(src, wanted)

    # 3. report BEFORE touching disk
    console.print(f"Project uses [bold]{len(wanted)}[/bold] symbols from '{library}' .")
    console.print(f"Source has {len(src.symbols)}; keeping {len(kept)}.")

    if missing:
        console.print(f"[red]⚠ missing from source:[/red] {sorted(missing)}")

    if dry_run:
        console.print("[yellow]dry-run - nothing written.[/yellow]")
        return


    # 4. safe write: back up an existing output before overwriting
    if output.exists():
        backup = output.with_suffix(output.suffix + ".bak")
        backup.write_bytes(output.read_bytes())
        console.print(f"backed up existing -> {backup.name}")


    output.parent.mkdir(parents=True, exist_ok=True)
    src.symbols = kept
    src.to_file(str(output))
    console.print(f"[green]✓ wrote {len(kept)} symbols -> {output}[/green]")
