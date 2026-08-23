"""Read-only lint: the mechanical gaps that bite during layout.

Every check here needs no judgment, only thoroughness — count symbol pins,
count footprint pads, compare. Each one exists because it caught a real
defect on a real board (a 10-pin symbol shipped with an 8-pad footprint by
KiCad's own library; a shield pin numbered SH over pads named S1/S2).
"""

import re

from kicad_terrarium.core.extract import block_end

# pads: KiCad 6+ quotes the name; v5-era files leave it bare
_PAD_QUOTED = re.compile(r'\(pad "([^"]*)"')
_PAD_BARE = re.compile(r"\(pad ([^\s()\"]+)[\s(]")
_PIN_NUMBER = re.compile(r'\(number "([^"]+)"')
_MODEL = re.compile(r'\(model "([^"]+)"')
_CACHE_SYMBOL = re.compile(r'\n\t\t\(symbol "([^"]+:[^"]+)"')


def pad_names(mod_text: str) -> set[str]:
    """Pad numbers/names in a .kicad_mod, old or new format, unnamed dropped."""
    names = set(_PAD_QUOTED.findall(mod_text)) | set(_PAD_BARE.findall(mod_text))
    names.discard("")
    return names


def cache_symbol_pins(sheet_text: str) -> dict[str, set[str]]:
    """{lib_id: pin numbers} from a schematic's embedded lib_symbols cache.

    The cache holds the complete resolved symbol (all units, inheritance
    flattened), which makes it the authoritative pin list for every symbol
    the sheet uses — no library lookup required.
    """
    pins: dict[str, set[str]] = {}
    for m in _CACHE_SYMBOL.finditer(sheet_text):
        start = m.start() + 1
        block = sheet_text[start : block_end(sheet_text, start)]
        pins[m.group(1)] = set(_PIN_NUMBER.findall(block))
    return pins


def missing_pads(pins: set[str], pads: set[str]) -> set[str]:
    """Symbol pin numbers with no matching pad — each one a broken net at
    layout time. Extra pads (shields, thermal, mounting) are fine."""
    return pins - pads


def foreign_model_paths(mod_text: str) -> list[str]:
    """3D model references that will not travel with the project: anything
    not anchored to ${KIPRJMOD} (project-local) or ${KICAD...} (stock)."""
    return [
        path
        for path in _MODEL.findall(mod_text)
        if not path.startswith("${KIPRJMOD}") and not path.startswith("${KICAD")
    ]
