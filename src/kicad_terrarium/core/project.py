from collections.abc import Callable
from pathlib import Path

from kicad_terrarium.core.discover import find_lib_ids, sheet_files
from kicad_terrarium.core.io import read_utf8
from kicad_terrarium.core.sexpr import SExprError

# "How to read a file" remains injectable for tests. The production default is
# explicitly UTF-8 so Windows' locale encoding cannot corrupt KiCad input.
ReadText = Callable[[Path], str]


class ProjectError(ValueError):
    """The schematic graph is missing or crosses a requested boundary."""


def project_schematics(
    root: Path,
    read_text: ReadText = read_utf8,
    *,
    allow_external: bool = True,
) -> list[Path]:
    """
    Walk from 'root', following sub-sheet references, and return every reachable
    .kicad_sch file (root included), each exactly once.

    A Sheetfile reference is relative to the folder of the file that names it.
    """
    boundary = root.resolve().parent
    ordered: list[Path] = []  # results, in discovery order
    seen: set[Path] = set()  # guards against revisits and cycles
    worklist: list[Path] = [root]  # files still waiting to be processed

    while worklist:
        current = worklist.pop().resolve()

        if current in seen:
            continue

        if not allow_external and not current.is_relative_to(boundary):
            raise ProjectError(f"sub-sheet is outside the project: {current}")

        seen.add(current)
        ordered.append(current)

        text = read_text(current)
        try:
            children = sheet_files(text)
        except SExprError as error:
            raise ProjectError(f"invalid schematic {current}: {error}") from error
        for child_name in children:
            worklist.append(current.parent / child_name)

    return ordered


def project_lib_ids(
    root: Path,
    read_text: ReadText = read_utf8,
    *,
    allow_external: bool = True,
) -> list[str]:
    """Every lib_id across the root schematic and all its sub-sheets, in order."""
    all_ids: list[str] = []
    for sheet in project_schematics(root, read_text, allow_external=allow_external):
        text = read_text(sheet)
        try:
            all_ids += find_lib_ids(text)
        except SExprError as error:
            raise ProjectError(f"invalid schematic {sheet}: {error}") from error
    return all_ids
