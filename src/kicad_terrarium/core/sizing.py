"""Validated, explicit value-to-footprint policies for passives.

``fit`` is an automation policy, not an electrical-design oracle. Its bundled
profile optimizes for comfortable hand assembly; voltage rating, dielectric,
power, tolerance, and supply availability remain engineering constraints the
schematic value alone cannot express.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

RESISTOR_SYMBOLS = {"R", "R_US", "R_Small", "R_Small_US"}
CAPACITOR_SYMBOLS = {"C", "C_Small"}
POLARIZED_CAPACITOR_SYMBOLS = {"C_Polarized", "C_Polarized_Small", "CP", "CP_Small"}
INDUCTOR_SYMBOLS = {"L", "L_Small", "L_Core_Ferrite"}

_CAP_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3}
_RES_MULT = {"R": 1.0, "r": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
_SAFE_ID_PART = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')


class SizingConfigError(ValueError):
    """A fit policy is incomplete, ambiguous, or malformed."""


def _parse_value(text: str, multipliers: dict[str, float]) -> float | None:
    value = text.strip()
    if not value:
        return None
    for index, character in enumerate(value):
        if character not in multipliers:
            continue
        head, tail = value[:index], value[index + 1 :]
        try:
            if not tail:
                number = float(head)
            elif re.fullmatch(r"\d+", tail):
                number = float(f"{head or '0'}.{tail}")
            else:
                return None
        except ValueError:
            return None
        parsed = number * multipliers[character]
        return parsed if math.isfinite(parsed) else None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def parse_capacitance(value: str) -> float | None:
    """Farads from values such as ``100nF``, ``4n7``, or ``1µF``."""
    return _parse_value(value.strip().rstrip("Ff"), _CAP_MULT)


def parse_resistance(value: str) -> float | None:
    """Ohms from values such as ``10k``, ``33R``, or ``4R7``."""
    cleaned = value.strip().rstrip("Ω").removesuffix("ohm").removesuffix("Ohm").strip()
    return _parse_value(cleaned, _RES_MULT)


@dataclass(frozen=True)
class Rules:
    """One resistor package and ordered capacitor upper bounds."""

    resistor: str
    capacitor: list[tuple[float | None, str]]
    name: str = "custom"
    description: str = "User-defined footprint assignment policy."


def default_rules() -> Rules:
    """The bundled hand-assembly profile; deliberately not an EE validator."""
    return Rules(
        resistor="Resistor_SMD:R_0603_1608Metric",
        capacitor=[
            (1e-6, "Capacitor_SMD:C_0603_1608Metric"),
            (None, "Capacitor_SMD:C_0805_2012Metric"),
        ],
        name="hand-solder",
        description=(
            "Hand-assembly baseline: 0603 resistors; generic non-polar capacitors use "
            "0603 through 1 µF, then 0805. Does not validate voltage, dielectric, power, "
            "tolerance, or stock."
        ),
    )


def _footprint(value: object, field: str, *, strict: bool) -> str:
    valid_id = False
    if isinstance(value, str):
        library, separator, name = value.partition(":")
        valid_id = bool(
            separator
            and library == library.strip()
            and name == name.strip()
            and _SAFE_ID_PART.fullmatch(library)
            and _SAFE_ID_PART.fullmatch(name)
        )
    if not isinstance(value, str) or not value.strip() or (strict and not valid_id):
        expected = "Library:Footprint" if strict else "footprint"
        raise SizingConfigError(f"{field} must be a non-empty {expected} string")
    return value


def rules_from_config(sizing: dict[str, Any], *, strict_footprints: bool = False) -> Rules:
    """Validate a legacy/custom ``sizing`` block; empty selects hand-solder."""
    if not sizing:
        return default_rules()
    if not isinstance(sizing, dict):
        raise SizingConfigError("sizing must be an object")
    base = default_rules()
    resistor = _footprint(
        sizing.get("resistor", base.resistor),
        "sizing.resistor",
        strict=strict_footprints,
    )
    cap_config = sizing.get("capacitor")
    if cap_config is None:
        return Rules(resistor, base.capacitor, "custom", "Custom passive footprint policy.")
    if not isinstance(cap_config, list) or not cap_config:
        raise SizingConfigError("sizing.capacitor must be a non-empty list")

    capacitor: list[tuple[float | None, str]] = []
    catch_alls = 0
    for index, raw_entry in enumerate(cap_config):
        if not isinstance(raw_entry, dict):
            raise SizingConfigError(f"sizing.capacitor[{index}] must be an object")
        footprint = _footprint(
            raw_entry.get("footprint"),
            f"sizing.capacitor[{index}].footprint",
            strict=strict_footprints,
        )
        maximum = raw_entry.get("max")
        if maximum is None:
            catch_alls += 1
            threshold = None
        elif not isinstance(maximum, str) or (threshold := parse_capacitance(maximum)) is None:
            raise SizingConfigError(
                f"sizing.capacitor[{index}].max is not a valid capacitance: {maximum!r}"
            )
        elif threshold <= 0:
            raise SizingConfigError(f"sizing.capacitor[{index}].max must be positive")
        capacitor.append((threshold, footprint))
    if catch_alls != 1:
        raise SizingConfigError("sizing.capacitor needs exactly one catch-all entry without max")
    capacitor.sort(key=lambda item: (item[0] is None, item[0] or 0.0))
    thresholds = [threshold for threshold, _ in capacitor if threshold is not None]
    if len(thresholds) != len(set(thresholds)):
        raise SizingConfigError("sizing.capacitor max thresholds must be unique")
    return Rules(resistor, capacitor, "custom", "Custom passive footprint policy.")


def footprint_for(lib_id: str, value: str, rules: Rules) -> str | None:
    """Apply a chosen policy to supported R/C symbols; never infer inductors."""
    name = lib_id.split(":")[-1]
    if name in RESISTOR_SYMBOLS:
        return rules.resistor
    if name in CAPACITOR_SYMBOLS:
        farads = parse_capacitance(value)
        if farads is None or farads <= 0:
            return None
        for threshold, footprint in rules.capacitor:
            if threshold is None or farads <= threshold:
                return footprint
    return None
