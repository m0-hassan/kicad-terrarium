"""Configuration and explicit passive-fit policy commands."""

from __future__ import annotations

import sys
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
from kicad_terrarium.core.config import CONFIG_PATH, Config, dump_config
from kicad_terrarium.core.io import MutationError, OperationPlan
from kicad_terrarium.core.sexpr import SExprError
from kicad_terrarium.core.sizing import SizingConfigError, default_rules, rules_from_config
from kicad_terrarium.core.workflows import footprint_summary, plan_fit
from kicad_terrarium.presentation import DONE, PLAN, UNCHANGED, status_line

_EMPTY_LIBRARY = '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "kicad-terrarium")\n)\n'


def _parse_roots(value: str) -> list[Path]:
    return [Path(item.strip()).expanduser() for item in value.split(",") if item.strip()]


def init(
    vault: Path | None = typer.Option(
        None,
        "--vault",
        help="Reusable .kicad_sym file or folder of nested sub-libraries.",
    ),
    projects: str | None = typer.Option(
        None,
        "--projects",
        help="Comma-separated folders containing KiCad projects.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
) -> None:
    """Configure a file/folder vault and the roots searched by list/browse."""
    existing = load_user_config()
    interactive = vault is None and projects is None
    if interactive and not sys.stdin.isatty():
        fail("init needs --vault and/or --projects when stdin is not interactive", code=2)

    selected_vault = vault.expanduser() if vault is not None else existing.vault
    selected_roots = _parse_roots(projects) if projects is not None else existing.project_roots
    if interactive:
        suggestion = existing.vault or Path.home() / "Documents/KiCad/libraries"
        qualifier = "keep current" if existing.vault else "skip"
        entered = typer.prompt(
            f"Vault file/folder (suggested: {suggestion}; Enter to {qualifier})",
            default="",
            show_default=False,
        ).strip()
        if entered:
            selected_vault = Path(entered).expanduser()
        roots_hint = ", ".join(str(path) for path in existing.project_roots)
        entered_roots = typer.prompt(
            f"Project folders, comma-separated (current: {roots_hint or 'none'}; Enter to keep)",
            default="",
            show_default=False,
        ).strip()
        if entered_roots:
            selected_roots = _parse_roots(entered_roots)

    config = Config(
        curated_library=selected_vault,
        project_roots=selected_roots,
        sizing=existing.sizing,
        fit_profile=existing.fit_profile,
        theme=existing.theme,
    )
    roots = [CONFIG_PATH.parent]
    if selected_vault is not None:
        roots.append(selected_vault.parent)
    try:
        plan = OperationPlan(*roots)
        if (
            selected_vault is not None
            and selected_vault.suffix == ".kicad_sym"
            and not selected_vault.exists()
        ):
            plan.write(selected_vault, _EMPTY_LIBRARY, "create file vault")
        elif selected_vault is not None and selected_vault.suffix != ".kicad_sym":
            plan.mkdir(selected_vault, "create vault folder")
        plan.write(CONFIG_PATH, dump_config(config), "write Terrarium configuration")
    except (OSError, MutationError) as error:
        fail(str(error), code=2)

    if dry_run:
        apply_plan(plan, dry_run=True)
        if not plan.changes:
            console().print(status_line(UNCHANGED, "configuration already matches"))
        return
    changed = apply_plan(plan, dry_run=False)
    console().print(status_line(DONE if changed else UNCHANGED, short_path(CONFIG_PATH)))


def fit(
    root: Path | None = typer.Argument(None, help="Project; defaults to the project here."),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="hand-solder or custom; defaults to the configured profile.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the exact plan; write nothing."),
    precise: bool = typer.Option(False, "--precise", help="List every assigned component."),
) -> None:
    """Fill empty resistor/non-polar-C footprints with a named policy."""
    project = resolve_root(root)
    config = load_user_config()
    chosen = profile or config.fit_profile
    try:
        if chosen == "hand-solder":
            rules = default_rules()
        elif chosen == "custom":
            if not config.sizing:
                raise SizingConfigError(
                    "custom fit profile selected, but config has no sizing rules"
                )
            rules = rules_from_config(config.sizing, strict_footprints=True)
        else:
            raise SizingConfigError(f"unknown fit profile {chosen!r}; use hand-solder or custom")
        result = plan_fit(project, rules)
    except (OSError, UnicodeError, ValueError, SExprError, MutationError) as error:
        fail(str(error), code=2)
    changed = apply_plan(result.plan, dry_run=dry_run)
    console().print(f"[dim]policy: {escape(rules.description)}[/dim]")
    if precise:
        for reference, footprint in sorted(result.applied):
            console().print(f"  {escape(reference)}  {escape(footprint)}")
    else:
        for footprint, count in sorted(footprint_summary(result.applied).items()):
            console().print(f"  {count:>3}  {footprint}")
    status = PLAN if dry_run and result.applied else (DONE if changed else UNCHANGED)
    console().print(status_line(status, f"{len(result.applied)} empty footprints assigned"))
    if result.skipped_inductors:
        console().print(
            "[dim]left unassigned: "
            f"{escape(', '.join(sorted(result.skipped_inductors)))}; "
            "inductor package needs current data[/dim]"
        )
    if result.skipped_polarized_capacitors:
        console().print(
            "[dim]left unassigned: "
            f"{escape(', '.join(sorted(result.skipped_polarized_capacitors)))}; "
            "polarized capacitor technology/package needs explicit selection[/dim]"
        )


def register(app: typer.Typer) -> None:
    app.command()(init)
    app.command()(fit)
