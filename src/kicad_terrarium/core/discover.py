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
    Return child sheet filenames as schematic references, e.g. ['power.kichad_sch'].
    """
    return _SHEETFILE_PATTERN.findall(text)


def library_counts(lib_ids: list[str]) -> Counter:
    """
    Count how many symbols reference each library

    Example: library_counts(["Device:R", "Device:C", "Connector:X", "Device:L"]) -> {"Device": 3, "Connector: 1}
    """
    return Counter(lib_id.split(":", 1)[0] for lib_id in lib_ids)
