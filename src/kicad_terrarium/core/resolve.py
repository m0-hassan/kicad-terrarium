"""Resolve KiCad project/global library tables and path variables."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from kicad_terrarium.core.models import (
    Diagnostic,
    DiagnosticLevel,
    LibraryEntry,
    ResolutionResult,
    ResolvedLibrary,
)
from kicad_terrarium.core.tables import parse_library_entries

_VARIABLE = re.compile(r"\$\{([^}]+)\}")
_VERSIONED_DIR = re.compile(r"KICAD\d+_(SYMBOL|FOOTPRINT|3DMODEL|TEMPLATE)_DIR")


def default_config_dir() -> Path:
    """The platform's KiCad per-user configuration root."""
    if sys.platform == "darwin":
        return Path.home() / "Library/Preferences/kicad"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "kicad"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kicad"


def default_share_dir() -> Path:
    """Best platform fallback for KiCad's shared data root."""
    if sys.platform == "darwin":
        return Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport")
    if sys.platform == "win32":
        return Path(os.environ.get("ProgramFiles") or "C:/Program Files") / "KiCad/share/kicad"
    return Path("/usr/share/kicad")


DEFAULT_SHARE = default_share_dir()
DEFAULT_CONFIG = default_config_dir()


def _builtin_value(name: str, share_dir: Path) -> str | None:
    match = _VERSIONED_DIR.fullmatch(name)
    if match is None:
        return None
    folder = {
        "SYMBOL": "symbols",
        "FOOTPRINT": "footprints",
        "3DMODEL": "3dmodels",
        "TEMPLATE": "template",
    }[match.group(1)]
    return str(share_dir / folder)


def expand_uri(
    uri: str,
    project_dir: Path,
    share_dir: Path = DEFAULT_SHARE,
    *,
    variables: dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Expand KiCad/environment path variables and relative table URIs."""
    values = dict(os.environ)
    if variables:
        values.update(variables)
    values["KIPRJMOD"] = str(project_dir)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return values.get(name) or _builtin_value(name, share_dir) or match.group(0)

    expanded_uri = uri
    seen: set[str] = set()
    for _iteration in range(10):
        if expanded_uri in seen:
            break
        seen.add(expanded_uri)
        substituted = _VARIABLE.sub(replace, expanded_uri)
        if substituted == expanded_uri:
            break
        expanded_uri = substituted
    expanded = Path(expanded_uri).expanduser()
    if not expanded.is_absolute() and not _VARIABLE.search(str(expanded)):
        expanded = (base_dir or project_dir) / expanded
    return expanded


def newest_global_table(table_name: str, config_dir: Path = DEFAULT_CONFIG) -> Path | None:
    """The newest versioned KiCad config table, comparing version tuples."""

    def version_key(path: Path) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in path.parent.name.split("."))
        except ValueError:
            return (-1,)

    tables = [path for path in config_dir.glob(f"*/{table_name}") if path.is_file()]
    return max(tables, key=version_key) if tables else None


def _config_variables(table_path: Path | None) -> dict[str, str]:
    """Read KiCad's user-defined path variables from ``kicad_common.json``."""
    if table_path is None:
        return {}
    common = table_path.parent / "kicad_common.json"
    if not common.is_file():
        return {}
    try:
        raw = json.loads(common.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    environment = raw.get("environment", {})
    values = environment.get("vars", {}) if isinstance(environment, dict) else {}
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def configured_path_variables(
    config_dir: Path = DEFAULT_CONFIG,
    *,
    table_name: str = "fp-lib-table",
) -> dict[str, str]:
    """User-defined KiCad path variables from the newest matching configuration."""
    return _config_variables(newest_global_table(table_name, config_dir))


def direct_library_registration(
    project_dir: Path,
    nickname: str,
    *,
    table_name: str,
    share_dir: Path = DEFAULT_SHARE,
    config_dir: Path = DEFAULT_CONFIG,
) -> tuple[LibraryEntry, Path] | None:
    """One enabled direct project-table row and its expanded path, if present."""
    table = project_dir / table_name
    if not table.is_file():
        return None
    entries = [
        entry
        for entry in parse_library_entries(table.read_bytes().decode("utf-8"))
        if entry.enabled and entry.nickname == nickname
    ]
    if len(entries) > 1:
        raise ValueError(f"{nickname!r} is registered more than once in {table}")
    if not entries:
        return None
    entry = entries[0]
    path = expand_uri(
        entry.uri,
        project_dir,
        share_dir,
        variables=configured_path_variables(config_dir, table_name=table_name),
        base_dir=table.parent,
    )
    unresolved = _VARIABLE.findall(str(path))
    if unresolved:
        raise ValueError(
            f"{nickname}: unresolved path variable(s): {', '.join(sorted(set(unresolved)))}"
        )
    return entry, path.resolve()


def _resolve(
    project_dir: Path,
    table_name: str,
    share_dir: Path,
    config_dir: Path,
    *,
    include_project: bool = True,
) -> ResolutionResult:
    result = ResolutionResult()
    global_table = newest_global_table(table_name, config_dir)
    variables = _config_variables(global_table)
    seen_tables: set[Path] = set()

    def diagnostic(level: DiagnosticLevel, message: str, path: Path | None, code: str) -> None:
        result.diagnostics.append(Diagnostic(level, message, path, code))

    def load(
        table_path: Path, *, project_scope: bool, nested: bool = False
    ) -> dict[str, ResolvedLibrary]:
        canonical = table_path.resolve()
        if canonical in seen_tables:
            diagnostic(
                "warning",
                f"library-table cycle ignored: {table_path}",
                table_path,
                "table-cycle",
            )
            return {}
        seen_tables.add(canonical)
        try:
            text = table_path.read_text(encoding="utf-8")
            entries = parse_library_entries(
                text,
                scope="project" if project_scope else ("nested" if nested else "global"),
            )
        except (OSError, ValueError) as error:
            diagnostic("error", f"cannot read library table: {error}", table_path, "invalid-table")
            return {}

        found: dict[str, ResolvedLibrary] = {}
        for entry in entries:
            if not entry.enabled:
                continue
            expanded = expand_uri(
                entry.uri,
                project_dir,
                share_dir,
                variables=variables,
                base_dir=table_path.parent,
            )
            unresolved = _VARIABLE.findall(str(expanded))
            if entry.library_type.casefold() == "table":
                if unresolved:
                    diagnostic(
                        "warning",
                        f"{entry.nickname}: unresolved path variable(s): {', '.join(unresolved)}",
                        table_path,
                        "unresolved-variable",
                    )
                elif expanded.is_file():
                    found.update(load(expanded, project_scope=project_scope, nested=True))
                else:
                    diagnostic(
                        "warning",
                        f"nested table does not exist: {expanded}",
                        expanded,
                        "missing-table",
                    )
                continue

            # A closer-scope entry owns its nickname even when broken. This is
            # KiCad's shadowing behavior and prevents a global fallback from
            # concealing a dangling project registration.
            found.pop(entry.nickname, None)
            if unresolved:
                diagnostic(
                    "warning",
                    f"{entry.nickname}: unresolved path variable(s): {', '.join(unresolved)}",
                    table_path,
                    "unresolved-variable",
                )
                continue
            if entry.library_type.casefold() != "kicad":
                diagnostic(
                    "warning",
                    f"{entry.nickname}: library type {entry.library_type!r} "
                    "is not file-backed by Terrarium",
                    table_path,
                    "unsupported-library-type",
                )
                continue
            if not expanded.exists():
                diagnostic(
                    "warning",
                    f"{entry.nickname}: path does not exist: {expanded}",
                    expanded,
                    "missing-library",
                )
                continue
            found[entry.nickname] = ResolvedLibrary(entry, expanded)
        return found

    if global_table is not None:
        result.libraries.update(load(global_table, project_scope=False))
    project_table = project_dir / table_name
    if include_project and project_table.is_file():
        # Project nicknames shadow globals, including broken registrations.
        try:
            project_entries = parse_library_entries(
                project_table.read_text(encoding="utf-8"),
                scope="project",
            )
            for entry in project_entries:
                result.libraries.pop(entry.nickname, None)
        except (OSError, ValueError):
            pass
        result.libraries.update(load(project_table, project_scope=True))
    return result


def resolve_library_details(
    project_dir: Path,
    *,
    table_name: str = "sym-lib-table",
    share_dir: Path = DEFAULT_SHARE,
    config_dir: Path = DEFAULT_CONFIG,
) -> ResolutionResult:
    """Detailed resolution with diagnostics for every unavailable entry."""
    return _resolve(project_dir, table_name, share_dir, config_dir)


def resolve_global_library_details(
    project_dir: Path,
    *,
    table_name: str = "sym-lib-table",
    share_dir: Path = DEFAULT_SHARE,
    config_dir: Path = DEFAULT_CONFIG,
) -> ResolutionResult:
    """Resolve only the user/global table, ignoring project-level shadows."""
    return _resolve(
        project_dir,
        table_name,
        share_dir,
        config_dir,
        include_project=False,
    )


def resolve_footprint_libs(
    project_dir: Path,
    share_dir: Path = DEFAULT_SHARE,
    config_dir: Path = DEFAULT_CONFIG,
) -> dict[str, Path]:
    """Resolve footprint-library nicknames to paths for physical audits."""
    details = _resolve(project_dir, "fp-lib-table", share_dir, config_dir)
    return {name: library.path for name, library in details.libraries.items()}
