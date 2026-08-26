"""Shared CLI boundaries: runtime output, project discovery, and failures."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import typer
from rich.console import Console

from kicad_terrarium.core.config import Config, ConfigError, load_config
from kicad_terrarium.core.io import MutationError, OperationPlan
from kicad_terrarium.presentation import ERROR, PLAN, ColorMode, make_console, status_line


@dataclass
class Runtime:
    color: ColorMode = "auto"
    json_output: bool = False
    console: Console | None = None
    error_console: Console | None = None


runtime = Runtime()


def configure(*, color: ColorMode, json_output: bool) -> None:
    runtime.color = color
    runtime.json_output = json_output
    runtime.console = make_console(color)
    runtime.error_console = make_console(color, stderr=True)


def console(*, stderr: bool = False) -> Console:
    if stderr:
        if runtime.error_console is None:
            runtime.error_console = make_console(runtime.color, stderr=True)
        return runtime.error_console
    if runtime.console is None:
        runtime.console = make_console(runtime.color)
    return runtime.console


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, default=_json_default, sort_keys=True))


def fail(message: str, *, code: int = 1) -> NoReturn:
    if runtime.json_output:
        emit_json({"ok": False, "error": message, "exit_code": code})
    else:
        console(stderr=True).print(status_line(ERROR, message))
    raise typer.Exit(code=code)


def load_user_config() -> Config:
    try:
        return load_config()
    except ConfigError as error:
        fail(str(error), code=2)


def find_project_root(directory: Path) -> Path | None:
    """The sole matching KiCad project root in a directory."""
    projects = sorted(directory.glob("*.kicad_pro"))
    candidates = [path.with_suffix(".kicad_sch") for path in projects]
    roots = [path for path in candidates if path.is_file()]
    return roots[0] if len(roots) == 1 else None


def resolve_root(value: Path | None) -> Path:
    if value is None:
        found = find_project_root(Path.cwd())
        if found is None:
            fail("give a root .kicad_sch, or run inside a directory with one KiCad project", code=2)
        return found.resolve()
    path = value.expanduser()
    if path.is_dir():
        found = find_project_root(path)
        if found is None:
            fail(f"{path} does not contain exactly one KiCad project", code=2)
        return found.resolve()
    if path.suffix == ".kicad_pro":
        path = path.with_suffix(".kicad_sch")
    if not path.is_file() or path.suffix != ".kicad_sch":
        fail(f"not a .kicad_sch file: {path}", code=2)
    return path.resolve()


def short_path(path: Path) -> str:
    home = Path.home()
    if path == home:
        return "~"
    if path.is_relative_to(home):
        return f"~/{path.relative_to(home)}"
    return str(path)


def apply_plan(plan: OperationPlan, *, dry_run: bool) -> list[Path]:
    if dry_run:
        if not runtime.json_output:
            for change in plan.changes:
                console().print(
                    status_line(PLAN, f"{change.description}  {short_path(change.path)}")
                )
        return []
    try:
        return plan.apply()
    except MutationError as error:
        fail(str(error), code=2)
