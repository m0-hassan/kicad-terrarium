from collections.abc import Callable
from pathlib import Path

from kicad_terrarium.core.discover import find_lib_ids, sheet_files

# "How to read a file" is a parameter so tests can substitute an in-memory
# fake. Path.read_text accessed on the CLASS is an ordinary function taking
# the path as its first argument: Path.read_text(p) == p.read_text().
ReadText = Callable[[Path], str]


def project_schematics(root: Path, read_text: ReadText = Path.read_text) -> list[Path]:
    """
    Walk from 'root', following sub-sheet references, and return every reachable
    .kicad_sch file (root included), each exactly once.

    A Sheetfile reference is relative to the folder of the file that names it.
    """
    ordered: list[Path] = []  # results, in discovery order
    seen: set[Path] = set()  # guards against revisits and cycles
    worklist: list[Path] = [root]  # files still waiting to be processed

    while worklist:
        current = worklist.pop().resolve()

        if current in seen:
            continue

        seen.add(current)
        ordered.append(current)

        for child_name in sheet_files(read_text(current)):
            worklist.append(current.parent / child_name)

    return ordered


def project_lib_ids(root: Path, read_text: ReadText = Path.read_text) -> list[str]:
    """Every lib_id across the root schematic and all its sub-sheets, in order."""
    all_ids: list[str] = []
    for sheet in project_schematics(root, read_text):
        all_ids += find_lib_ids(read_text(sheet))
    return all_ids
