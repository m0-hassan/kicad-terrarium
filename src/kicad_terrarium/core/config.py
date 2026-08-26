"""Validated user configuration for vaults, projects, fit, and appearance."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


def default_config_path() -> Path:
    override = os.environ.get("KICAD_TERRARIUM_CONFIG")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "kicad-terrarium/config.json"


CONFIG_PATH = default_config_path()


class ConfigError(ValueError):
    """Configuration is malformed or contains an unsupported value."""


Theme = Literal["auto", "dark", "light"]


@dataclass
class Config:
    """User settings. A vault may be one file or a nested library folder."""

    curated_library: Path | None = None
    project_roots: list[Path] = field(default_factory=list)
    sizing: dict[str, Any] = field(default_factory=dict)
    fit_profile: str = "hand-solder"
    theme: Theme = "auto"

    @property
    def vault(self) -> Path | None:
        """Preferred product term; ``curated_library`` remains API-compatible."""
        return self.curated_library


def _path(value: object, field_name: str) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{field_name} must be a path string")
    return Path(value).expanduser()


def parse_config(text: str) -> Config:
    """Parse and validate JSON; blank text yields documented defaults."""
    try:
        raw = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as error:
        raise ConfigError(f"invalid JSON at line {error.lineno}, column {error.colno}") from error
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a JSON object")
    allowed = {
        "vault",
        "curated_library",
        "project_roots",
        "sizing",
        "fit_profile",
        "theme",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"unknown configuration field(s): {', '.join(unknown)}")
    if "vault" in raw and "curated_library" in raw:
        raise ConfigError("use 'vault', not both 'vault' and legacy 'curated_library'")

    vault_value = raw.get("vault", raw.get("curated_library"))
    roots_value = raw.get("project_roots", [])
    if not isinstance(roots_value, list):
        raise ConfigError("project_roots must be a list of path strings")
    roots = [_path(value, f"project_roots[{index}]") for index, value in enumerate(roots_value)]
    if any(path is None for path in roots):
        raise ConfigError("project_roots cannot contain blank paths")

    sizing = raw.get("sizing", {})
    if not isinstance(sizing, dict):
        raise ConfigError("sizing must be an object")
    # Legacy configs predate named profiles; a sizing block meant "use it".
    fit_profile = raw.get("fit_profile", "custom" if sizing else "hand-solder")
    if not isinstance(fit_profile, str) or fit_profile not in {"hand-solder", "custom"}:
        raise ConfigError("fit_profile must be hand-solder or custom")
    theme = raw.get("theme", "auto")
    if theme not in {"auto", "dark", "light"}:
        raise ConfigError("theme must be auto, dark, or light")

    return Config(
        curated_library=_path(vault_value, "vault"),
        project_roots=[path for path in roots if path is not None],
        sizing=sizing,
        fit_profile=fit_profile,
        theme=theme,
    )


def dump_config(config: Config) -> str:
    """Serialize stable public keys, omitting defaults and unset fields."""
    data: dict[str, object] = {}
    if config.vault is not None:
        data["vault"] = str(config.vault)
    if config.project_roots:
        data["project_roots"] = [str(path) for path in config.project_roots]
    if config.sizing:
        data["sizing"] = config.sizing
    if config.fit_profile != "hand-solder" or config.sizing:
        data["fit_profile"] = config.fit_profile
    if config.theme != "auto":
        data["theme"] = config.theme
    return json.dumps(data, indent=2) + "\n"


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read configuration or return defaults when the file is absent."""
    if not path.is_file():
        return Config()
    try:
        return parse_config(path.read_bytes().decode("utf-8"))
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    except UnicodeError as error:
        raise ConfigError(f"configuration is not UTF-8: {path}") from error
