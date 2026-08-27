"""Terminal identity, restrained status language, and color policy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from rich.console import Console
from rich.text import Text

ColorMode = Literal["auto", "always", "never"]
Theme = Literal["auto", "dark", "light"]

DARK_PALETTE = ["#b7d88a", "#69b578", "#2f8f62"]
LIGHT_PALETTE = ["#183d2b", "#2d6045", "#51734b"]
BANNER_LINES = (
    "   __                            _               ",
    "  / /____  ______________ ______(_)_  ______ ___ ",
    " / __/ _ \\/ ___/ ___/ __ `/ ___/ / / / / __ `__ \\",
    "/ /_/  __/ /  / /  / /_/ / /  / / /_/ / / / / / /",
    "\\__/\\___/_/  /_/   \\__,_/_/  /_/\\__,_/_/ /_/ /_/ ",
    "                                                 ",
)


def detect_theme(requested: Theme = "auto") -> Literal["dark", "light"]:
    if requested != "auto":
        return requested
    colorfgbg = os.environ.get("COLORFGBG", "")
    try:
        background = int(colorfgbg.split(";")[-1])
    except ValueError:
        background = -1
    return "light" if background in {7, 8, 9, 10, 11, 12, 13, 14, 15} else "dark"


def make_console(mode: ColorMode = "auto", *, stderr: bool = False) -> Console:
    force_terminal: bool | None = None
    if mode == "always":
        force_terminal = True
    elif mode == "never" or "NO_COLOR" in os.environ:
        force_terminal = False
    return Console(force_terminal=force_terminal, highlight=False, stderr=stderr)


def line_colors(num_lines: int, palette: list[str]) -> list[str]:
    if num_lines <= 0 or not palette:
        return []
    if num_lines == 1 or len(palette) == 1:
        return [palette[0]] * num_lines

    def channels(color: str) -> tuple[int, int, int]:
        if len(color) != 7 or not color.startswith("#"):
            raise ValueError(f"gradient stops must be #RRGGBB colors: {color!r}")
        try:
            return (
                int(color[1:3], 16),
                int(color[3:5], 16),
                int(color[5:7], 16),
            )
        except ValueError as error:
            raise ValueError(f"invalid gradient stop: {color!r}") from error

    stops = [channels(color) for color in palette]
    colors: list[str] = []
    for index in range(num_lines):
        position = index * (len(stops) - 1) / (num_lines - 1)
        left = min(int(position), len(stops) - 2)
        fraction = position - left
        interpolated = tuple(
            round(start + (end - start) * fraction)
            for start, end in zip(stops[left], stops[left + 1], strict=True)
        )
        colors.append("#" + "".join(f"{channel:02x}" for channel in interpolated))
    return colors


def render_banner(theme: Theme = "auto") -> Text:
    """Render Terrarium's botanical gradient with a light-background variant."""
    palette = LIGHT_PALETTE if detect_theme(theme) == "light" else DARK_PALETTE
    rendered = Text()
    for line, color in zip(
        BANNER_LINES,
        line_colors(len(BANNER_LINES), palette),
        strict=True,
    ):
        rendered.append(line + "\n", style=color)
    return rendered


@dataclass(frozen=True)
class Status:
    label: str
    style: str


DONE = Status("done", "green")
PLAN = Status("plan", "yellow")
WARNING = Status("warning", "yellow")
ERROR = Status("error", "red")
UNCHANGED = Status("unchanged", "dim")


def status_line(status: Status, message: str) -> Text:
    """Color only a compact semantic label; keep the useful text neutral."""
    output = Text()
    output.append(f"{status.label:<10}", style=status.style)
    output.append(message)
    return output
