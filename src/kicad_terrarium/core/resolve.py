"""Locate the library files behind every library name a project can see.

Two tables matter, project first (its entries shadow global ones — the same
lookup order KiCad uses):

1. `<project>/sym-lib-table` (or `fp-lib-table` for footprints)
2. the newest global table, e.g. `~/Library/Preferences/kicad/10.0/sym-lib-table`

KiCad 10 adds one indirection: a global entry with `(type "Table")` whose uri
is *another* lib table (the stock one shipped with the app). One level of
recursion follows it.
"""

import re
from pathlib import Path

_LIB_ENTRY = re.compile(r'\(lib\s*\(name "([^"]+)"\)\s*\(type "([^"]+)"\)\s*.*?\(uri "([^"]+)"\)')
_KICAD_SYMBOL_VAR = re.compile(r"\$\{KICAD\d+_SYMBOL_DIR\}")
_KICAD_FOOTPRINT_VAR = re.compile(r"\$\{KICAD\d+_FOOTPRINT_DIR\}")

MAC_SHARE = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport")
MAC_CONFIG = Path.home() / "Library/Preferences/kicad"


def parse_lib_table(table_text: str) -> list[tuple[str, str, str]]:
    """(name, type, uri) rows from one table, tolerant of both KiCad 9's
    `(name "x")(type ...)` spacing and KiCad 10's `(name "x") (type ...)`."""
    return _LIB_ENTRY.findall(table_text)


def expand_uri(uri: str, project_dir: Path, share_dir: Path = MAC_SHARE) -> Path:
    """Substitute the KiCad path variables terrarium understands."""
    uri = uri.replace("${KIPRJMOD}", str(project_dir))
    uri = _KICAD_SYMBOL_VAR.sub(str(share_dir / "symbols"), uri)
    uri = _KICAD_FOOTPRINT_VAR.sub(str(share_dir / "footprints"), uri)
    return Path(uri)


def newest_global_table(table_name: str, config_dir: Path = MAC_CONFIG) -> Path | None:
    """The highest-versioned KiCad config dir's table of that name, if any."""

    def version_key(p: Path) -> float:
        try:
            return float(p.parent.name)
        except ValueError:
            return -1.0

    tables = [p for p in config_dir.glob(f"*/{table_name}") if p.is_file()]
    return max(tables, key=version_key) if tables else None


def _resolve(
    project_dir: Path, table_name: str, share_dir: Path, config_dir: Path
) -> dict[str, Path]:
    """{library name: existing path}, project entries winning; missing dropped.

    Reporting an entry as unresolvable beats crashing on a half-installed
    library set, so entries whose path does not exist are simply omitted.
    """

    def load(table_path: Path, depth: int) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for name, lib_type, uri in parse_lib_table(table_path.read_text()):
            path = expand_uri(uri, project_dir, share_dir)
            if lib_type == "Table":
                if depth < 2 and path.is_file():
                    found.update(load(path, depth + 1))
            elif path.exists():
                found[name] = path
        return found

    result: dict[str, Path] = {}
    global_table = newest_global_table(table_name, config_dir)
    if global_table is not None:
        result.update(load(global_table, 0))
    project_table = project_dir / table_name
    if project_table.is_file():
        result.update(load(project_table, 0))
    return result


def resolve_libraries(
    project_dir: Path,
    share_dir: Path = MAC_SHARE,
    config_dir: Path = MAC_CONFIG,
) -> dict[str, Path]:
    """{symbol library name: .kicad_sym path} for everything resolvable."""
    return _resolve(project_dir, "sym-lib-table", share_dir, config_dir)


def resolve_footprint_libs(
    project_dir: Path,
    share_dir: Path = MAC_SHARE,
    config_dir: Path = MAC_CONFIG,
) -> dict[str, Path]:
    """{footprint library name: .pretty directory} for everything resolvable."""
    return _resolve(project_dir, "fp-lib-table", share_dir, config_dir)
