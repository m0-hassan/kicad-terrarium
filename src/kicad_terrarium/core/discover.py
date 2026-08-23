import re
from collections import Counter

# Matches lines like (lib_id "al-mawja-library:C") and captures the ID

_LIB_ID_PATTERN = re.compile(r'\(lib_id "([^"]+)"\)')


def find_lib_ids(text: str) -> list[str]:
    """Return every lib_id string in a KiCad file, e.g. ['Device:R', 'Device:C']"""
    return _LIB_ID_PATTERN.findall(text)


_SHEETFILE_PATTERN = re.compile(r'\(property "Sheetfile" "([^"]+)"')


def sheet_files(text: str) -> list[str]:
    """
    Return child sheet filenames a schematic references, e.g. ['power.kicad_sch'].
    """
    return _SHEETFILE_PATTERN.findall(text)


def library_counts(lib_ids: list[str]) -> Counter:
    """
    Count how many symbols reference each library

    Example: ["Device:R", "Device:C", "Connector:X"] -> {"Device": 2, "Connector": 1}
    """
    return Counter(lib_id.split(":", 1)[0] for lib_id in lib_ids)


_INSTANCE_SPLIT = re.compile(r"\n\t\(symbol\n")
_LIB_ID = re.compile(r'\(lib_id "([^"]+)"\)')
_REF_PROP = re.compile(r'\(property "Reference" "([^"]*)"')
_FP_PROP = re.compile(r'\(property "Footprint" "([^"]*)"')


def symbol_instances(text: str) -> list[tuple[str, str, str]]:
    """(reference, lib_id, footprint) for every placed symbol in a schematic.

    Splits on the instance blocks that follow the lib_symbols cache; the
    cache itself never matches because its symbols carry their name on the
    same line.
    """
    instances = []
    for part in _INSTANCE_SPLIT.split(text)[1:]:
        lib_id = _LIB_ID.search(part)
        if not lib_id:
            continue
        ref = _REF_PROP.search(part)
        fp = _FP_PROP.search(part)
        instances.append((ref.group(1) if ref else "?", lib_id.group(1), fp.group(1) if fp else ""))
    return instances


def used_symbols(lib_ids: list[str], library: str) -> set[str]:
    """
    Symbol names used from one specific library.

    Example: used_symbols(["lib:C", "lib:R", "other:X"], "lib") -> {"C", "R"}
    """
    names: set[str] = set()
    for lib_id in lib_ids:
        lib, _, symbol = lib_id.partition(":")
        if lib == library:
            names.add(symbol)
    return names
