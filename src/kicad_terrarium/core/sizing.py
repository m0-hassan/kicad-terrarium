"""Value→package rules for passives.

A 100 nF and a 10 µF are not the same size: MLCC capacitance scales with
physical volume, and DC-bias derating punishes an undersized part, so package
choice is partly a function of value. This is deterministic mechanics, so it
belongs here — but only for capacitors and resistors. Inductor packages
depend on saturation current, which no value reveals, so `footprint_for`
returns None for them: that stays a human decision.

Resistors take a single package regardless of value (package is set by power
and voltage, not resistance); only capacitors use a value→package table.
"""

import re
from dataclasses import dataclass

# symbol names (the part after "lib:") this understands
RESISTOR_SYMBOLS = {"R", "R_US", "R_Small", "R_Small_US"}
CAPACITOR_SYMBOLS = {"C", "C_Small", "C_Polarized", "C_Polarized_Small", "CP", "CP_Small"}
# not sized: package depends on saturation current, a human decision
INDUCTOR_SYMBOLS = {"L", "L_Small", "L_Core_Ferrite"}

_CAP_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3}
_RES_MULT = {"R": 1.0, "r": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}


def _parse_value(text: str, mults: dict[str, float]) -> float | None:
    """Parse an RKM-style value: '4.7n', '4n7', '100n', '10k', '4R7', '100'.

    The multiplier letter may sit at the end (4.7n) or stand in for the
    decimal point (4n7); a bare number is taken as base units.
    """
    s = text.strip()
    if not s:
        return None
    for i, ch in enumerate(s):
        if ch in mults:
            head, tail = s[:i], s[i + 1 :]
            try:
                if not tail:
                    num = float(head)
                elif re.fullmatch(r"\d+", tail):
                    num = float(f"{head or '0'}.{tail}")  # embedded-decimal: 4n7 -> 4.7
                else:
                    return None
            except ValueError:
                return None
            return num * mults[ch]
    try:
        return float(s)
    except ValueError:
        return None


def parse_capacitance(value: str) -> float | None:
    """Farads from a KiCad capacitor value like '100nF', '4.7nF', '10uF'."""
    return _parse_value(value.strip().rstrip("Ff"), _CAP_MULT)


def parse_resistance(value: str) -> float | None:
    """Ohms from a KiCad resistor value like '10k', '33R', '4R7', '100'."""
    cleaned = value.strip().rstrip("Ω").removesuffix("ohm").removesuffix("Ohm").strip()
    return _parse_value(cleaned, _RES_MULT)


@dataclass
class Rules:
    """resistor: one footprint. capacitor: (max_farads_inclusive, footprint)
    thresholds, ascending; a None threshold is the catch-all for larger."""

    resistor: str
    capacitor: list[tuple[float | None, str]]


def default_rules() -> Rules:
    """The hand-solder-friendly defaults validated on a real board: all R at
    0603; C at 0603 up to 1 µF, 0805 above (0402 floor avoided by design)."""
    return Rules(
        resistor="Resistor_SMD:R_0603_1608Metric",
        capacitor=[
            (1e-6, "Capacitor_SMD:C_0603_1608Metric"),
            (None, "Capacitor_SMD:C_0805_2012Metric"),
        ],
    )


def rules_from_config(sizing: dict) -> Rules:
    """Build Rules from a config `sizing` block, falling back to defaults.

    Capacitor thresholds are written as human value strings ("1uF") and
    parsed here; an entry without "max" is the catch-all.
    """
    base = default_rules()
    resistor = sizing.get("resistor", base.resistor)
    cap_cfg = sizing.get("capacitor")
    if not cap_cfg:
        return Rules(resistor=resistor, capacitor=base.capacitor)
    capacitor: list[tuple[float | None, str]] = []
    for entry in cap_cfg:
        max_str = entry.get("max")
        capacitor.append((parse_capacitance(max_str) if max_str else None, entry["footprint"]))
    capacitor.sort(key=lambda t: (t[0] is None, t[0]))  # ascending, catch-all last
    return Rules(resistor=resistor, capacitor=capacitor)


def footprint_for(lib_id: str, value: str, rules: Rules) -> str | None:
    """The footprint for a passive, or None if this isn't a sizable R/C or the
    value doesn't parse (inductors and everything else return None)."""
    name = lib_id.split(":")[-1]
    if name in RESISTOR_SYMBOLS:
        return rules.resistor
    if name in CAPACITOR_SYMBOLS:
        farads = parse_capacitance(value)
        if farads is None:
            return None
        for threshold, footprint in rules.capacitor:
            if threshold is None or farads <= threshold:
                return footprint
    return None
