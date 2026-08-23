"""User configuration: where the curated library and projects live.

Locations only — remembering paths is pure mechanics, not judgment. Stored
as JSON (stdlib read and write, every supported Python, the same style as
KiCad's own config files) at ~/.config/kicad-terrarium/config.json.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".config/kicad-terrarium/config.json"


@dataclass
class Config:
    """Resolved user settings; paths are absolute (``~`` already expanded)."""

    curated_library: Path | None = None
    project_roots: list[Path] = field(default_factory=list)


def parse_config(text: str) -> Config:
    """Config from JSON text; blank text yields defaults."""
    raw = json.loads(text) if text.strip() else {}
    lib = raw.get("curated_library")
    return Config(
        curated_library=Path(lib).expanduser() if lib else None,
        project_roots=[Path(r).expanduser() for r in raw.get("project_roots", [])],
    )


def dump_config(config: Config) -> str:
    """JSON text for a Config, omitting unset fields."""
    data: dict[str, object] = {}
    if config.curated_library is not None:
        data["curated_library"] = str(config.curated_library)
    if config.project_roots:
        data["project_roots"] = [str(p) for p in config.project_roots]
    return json.dumps(data, indent=2) + "\n"


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read the config file, or return defaults if it does not exist."""
    return parse_config(path.read_text()) if path.is_file() else Config()
