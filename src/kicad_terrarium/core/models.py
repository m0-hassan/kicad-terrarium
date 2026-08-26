"""Domain objects shared by project, library, and mutation workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, order=True)
class SymbolId:
    """A KiCad symbol's stable ``library:name`` identity."""

    library: str
    name: str

    @classmethod
    def parse(cls, value: str) -> SymbolId:
        library, separator, name = value.partition(":")
        if not separator or not library or not name:
            raise ValueError(f"invalid symbol ID: {value!r}")
        return cls(library, name)

    def __str__(self) -> str:
        return f"{self.library}:{self.name}"


TableScope = Literal["project", "global", "nested"]


@dataclass(frozen=True)
class LibraryEntry:
    """One parsed symbol- or footprint-library table entry."""

    nickname: str
    library_type: str
    uri: str
    scope: TableScope = "project"
    enabled: bool = True
    hidden: bool = False
    description: str = ""


@dataclass(frozen=True)
class ResolvedLibrary:
    """A library entry paired with the local path Terrarium resolved."""

    entry: LibraryEntry
    path: Path


DiagnosticLevel = Literal["error", "warning"]


@dataclass(frozen=True)
class Diagnostic:
    """A user-facing fact that carries stable severity and optional context."""

    level: DiagnosticLevel
    message: str
    path: Path | None = None
    code: str | None = None


@dataclass
class ResolutionResult:
    """Resolved libraries plus every unsupported or unavailable entry."""

    libraries: dict[str, ResolvedLibrary] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class PlacedSymbol:
    """The project-relevant fields of one placed schematic symbol."""

    reference: str
    symbol_id: SymbolId
    value: str = ""
    footprint: str = ""
    on_board: bool = True
    dnp: bool = False
