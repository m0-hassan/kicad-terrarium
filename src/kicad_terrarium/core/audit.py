"""Read-only checks for mechanical schematic/footprint mistakes."""

from __future__ import annotations

import re

from kicad_terrarium.core.sexpr import child_forms, descendant_forms, forms, quoted_tokens

_PAD_QUOTED = re.compile(r'\(pad\s+"((?:\\.|[^"\\])*)"')
_PAD_BARE = re.compile(r"\(pad\s+([^\s()\"]+)[\s(]")
_MODEL = re.compile(r'\(model\s+"((?:\\.|[^"\\])*)"')
_STOCK_MODEL = re.compile(r"^\$\{(?:KICAD\d+_3DMODEL_DIR|KISYS3DMOD)\}(?:[/\\]|$)")


def pad_names(mod_text: str) -> set[str]:
    """Pad numbers/names in a ``.kicad_mod``; unnamed pads are omitted."""
    names = set(_PAD_QUOTED.findall(mod_text)) | set(_PAD_BARE.findall(mod_text))
    names.discard("")
    return names


def cache_symbol_pins(sheet_text: str) -> dict[str, set[str]]:
    """Map cached symbol IDs to pin numbers, independent of formatting."""
    all_forms = forms(sheet_text)
    libraries = [form for form in all_forms if form.head == "lib_symbols"]
    if not libraries:
        return {}
    pins: dict[str, set[str]] = {}
    for cached in child_forms(all_forms, libraries[0], "symbol"):
        names = quoted_tokens(sheet_text, cached)
        if not names:
            continue
        numbers: set[str] = set()
        for number in descendant_forms(all_forms, cached, "number"):
            values = quoted_tokens(sheet_text, number)
            if values:
                numbers.add(values[0].value)
        pins[names[0].value] = numbers
    return pins


def missing_pads(pins: set[str], pads: set[str]) -> set[str]:
    """Symbol pin numbers with no matching pad; extra pads are acceptable."""
    return pins - pads


def foreign_model_paths(mod_text: str) -> list[str]:
    """3D model references that are neither project-local nor stock KiCad."""
    return [
        path
        for path in _MODEL.findall(mod_text)
        if not path.startswith("${KIPRJMOD}") and not is_stock_model_path(path)
    ]


def is_stock_model_path(path: str) -> bool:
    """Whether a model URI uses a recognized KiCad installation variable."""
    return _STOCK_MODEL.match(path) is not None


def model_paths(mod_text: str) -> list[str]:
    """Every 3D model URI in a footprint definition."""
    return _MODEL.findall(mod_text)
