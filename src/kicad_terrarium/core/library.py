"""Discover packed, unpacked, and nested vault symbol libraries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kicad_terrarium.core.extract import SymbolConflictError, library_version, symbol_blocks
from kicad_terrarium.core.io import read_utf8
from kicad_terrarium.core.tables import validate_library_nickname


@dataclass(frozen=True)
class LibrarySource:
    """One logical KiCad library, backed by one packed file or many files."""

    nickname: str
    files: tuple[Path, ...]
    group: tuple[str, ...] = ()
    unpacked: bool = False

    @property
    def label(self) -> str:
        return " / ".join((*self.group, self.nickname))

    @property
    def selector(self) -> str:
        """Unambiguous slash-delimited name accepted by --from-library."""
        return "/".join((*self.group, self.nickname))


@dataclass(frozen=True)
class SymbolSource:
    symbol: str
    library: LibrarySource


def _project_library_target(source: Path) -> Path:
    if source.is_file() and source.suffix in {".kicad_sch", ".kicad_pro"}:
        return source.parent / "library"
    if source.is_dir() and any(source.glob("*.kicad_pro")) and (source / "library").is_dir():
        return source / "library"
    return source


def _inside_unpacked(path: Path, root: Path) -> bool:
    return any(parent != root and parent.suffix == ".kicad_symdir" for parent in path.parents)


def discover_libraries(source: Path) -> list[LibrarySource]:
    """Discover a file, an unpacked library, or a folder of sub-libraries.

    An ordinary directory is a vault hierarchy. Each packed ``.kicad_sym`` is
    a logical library; each ``.kicad_symdir`` is one unpacked logical library.
    """
    target = _project_library_target(source)
    if target.is_file():
        if target.suffix != ".kicad_sym":
            return []
        return [LibrarySource(validate_library_nickname(target.stem), (target,))]
    if not target.is_dir():
        return []
    if target.suffix == ".kicad_symdir":
        files = tuple(sorted(target.rglob("*.kicad_sym")))
        return [
            LibrarySource(
                validate_library_nickname(target.name.removesuffix(".kicad_symdir")),
                files,
                unpacked=True,
            )
        ]

    discovered: list[LibrarySource] = []
    unpacked_dirs = sorted(path for path in target.rglob("*.kicad_symdir") if path.is_dir())
    for directory in unpacked_dirs:
        relative = directory.relative_to(target)
        discovered.append(
            LibrarySource(
                validate_library_nickname(directory.name.removesuffix(".kicad_symdir")),
                tuple(sorted(directory.rglob("*.kicad_sym"))),
                tuple(relative.parts[:-1]),
                unpacked=True,
            )
        )
    for file in sorted(target.rglob("*.kicad_sym")):
        if _inside_unpacked(file, target):
            continue
        relative = file.relative_to(target)
        discovered.append(
            LibrarySource(
                validate_library_nickname(file.stem),
                (file,),
                tuple(relative.parts[:-1]),
            )
        )
    return discovered


def source_blocks(source: LibrarySource) -> dict[str, str]:
    """Merge the definitions of a logical library, rejecting conflicts."""
    merged: dict[str, str] = {}
    for file in source.files:
        for name, block in symbol_blocks(read_utf8(file)).items():
            if name in merged and merged[name] != block:
                raise SymbolConflictError(
                    f"{source.label} has conflicting definitions for symbol {name!r}"
                )
            merged[name] = block
    return merged


def source_version(source: LibrarySource) -> str:
    """The first member's format version, or Terrarium's current default."""
    return library_version(read_utf8(source.files[0])) if source.files else "20251024"


def find_symbol_sources(
    source: Path,
    symbol: str,
    *,
    library: str | None = None,
) -> list[SymbolSource]:
    """Every matching definition; callers must resolve ambiguity explicitly."""
    matches: list[SymbolSource] = []
    selector = library.replace("\\", "/").strip("/") if library is not None else None
    for candidate in discover_libraries(source):
        if selector is not None and selector not in {candidate.nickname, candidate.selector}:
            continue
        if symbol in source_blocks(candidate):
            matches.append(SymbolSource(symbol, candidate))
    return matches
