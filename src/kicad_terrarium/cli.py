import sys

import typer
from pyfiglet import figlet_format
from rich.console import Console
from rich.text import Text

from kicad_terrarium import __version__

# The typer "app" is the container all of our commands attach to.
# Out pyproject entry point calls this object to launch the CLI.

app = typer.Typer(
    name="kicad-terrarium",
    help="Make KiCad porjects reproducibly self-contained.",
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
        index = int(i // (num_lines / len(palette)))
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
