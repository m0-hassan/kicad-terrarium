"""Shared identity and provenance rules for Terrarium-managed libraries."""

from __future__ import annotations

from pathlib import Path

from kicad_terrarium.core.models import LibraryEntry
from kicad_terrarium.core.tables import MANAGED_DESCRIPTION, validate_library_nickname

TERRARIUM_LIBRARY_PREFIX = "Terrarium__"
TERRARIUM_LIBRARY_DIRECTORY = Path("library/terrarium")
_LEGACY_MANAGED_DESCRIPTIONS = (
    MANAGED_DESCRIPTION.casefold(),
    "vendored by kicad-terrarium",
)


def terrarium_library_nickname(
    source_nickname: str,
    group: tuple[str, ...] = (),
) -> str:
    """The deterministic project-local identity for one external source."""
    components = (*group, source_nickname)
    for component in components:
        validate_library_nickname(component)
    return validate_library_nickname(TERRARIUM_LIBRARY_PREFIX + "__".join(components))


def managed_description(mode: str, sources: set[str] | list[str]) -> str:
    """Stable table provenance for a Terrarium-owned library."""
    origin = ", ".join(sorted(sources))
    return f"{MANAGED_DESCRIPTION}; mode={mode}; source={origin}"


def is_terrarium_managed(entry: LibraryEntry | None) -> bool:
    """Whether a table entry explicitly gives Terrarium ownership."""
    if entry is None:
        return False
    description = entry.description.casefold()
    return any(
        description == prefix or description.startswith(prefix + ";")
        for prefix in _LEGACY_MANAGED_DESCRIPTIONS
    )
