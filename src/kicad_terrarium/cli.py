"""Typer application assembly; implementation lives in cohesive command groups."""

from __future__ import annotations

import sys
from enum import Enum
from typing import cast

import typer

from kicad_terrarium import __version__
from kicad_terrarium.commands import browser, inspect, setup, transfer
from kicad_terrarium.commands.browser import (
    _build_browse_tree,
    _PluckAction,
    _run_browser,
    _SproutAction,
)
from kicad_terrarium.commands.common import configure, console
from kicad_terrarium.commands.transfer import _pluck, _sprout
from kicad_terrarium.core.config import ConfigError, load_config
from kicad_terrarium.presentation import Theme, line_colors, render_banner

__all__ = [
    "_PluckAction",
    "_SproutAction",
    "_build_browse_tree",
    "_pluck",
    "_run_browser",
    "_sprout",
    "app",
    "line_colors",
    "render_banner",
]


class ColorChoice(str, Enum):
    auto = "auto"
    always = "always"
    never = "never"


class ThemeChoice(str, Enum):
    auto = "auto"
    dark = "dark"
    light = "light"


app = typer.Typer(
    name="kicad-terrarium",
    help=(
        "A fast, local-first KiCad library workflow: find custom symbols in a few "
        "keystrokes, then seal and audit a self-contained professional handoff."
    ),
    no_args_is_help=False,
    pretty_exceptions_show_locals=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Print the installed version and exit.",
        is_eager=True,
    ),
    color: ColorChoice = typer.Option(
        ColorChoice.auto,
        "--color",
        help="Color policy: auto, always, or never (NO_COLOR is respected).",
    ),
    theme: ThemeChoice | None = typer.Option(
        None,
        "--theme",
        help="Background-aware botanical palette: auto, dark, or light.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit stable machine-readable output.",
    ),
) -> None:
    """Configure output once, before dispatching a command."""
    if version:
        typer.echo(f"kicad-terrarium {__version__}")
        raise typer.Exit()
    configured_theme = "auto"
    if theme is not None:
        configured_theme = theme.value
    else:
        try:
            configured_theme = load_config().theme
        except ConfigError:
            pass
    configure(
        color=color.value,
        json_output=json_output,
    )
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty() and not json_output:
            console().print(render_banner(cast(Theme, configured_theme)))
        if json_output:
            typer.echo(f'{{"name":"kicad-terrarium","version":"{__version__}"}}')
        else:
            console().print(
                f"kicad-terrarium {__version__}  "
                "[dim]custom symbols in; self-contained projects out[/dim]"
            )


inspect.register(app)
transfer.register(app)
setup.register(app)
browser.register(app)
