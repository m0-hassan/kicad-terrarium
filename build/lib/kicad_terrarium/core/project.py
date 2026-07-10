from pathlib import Path

from kicad_terrarium.core.discover import sheet_files

def project_schematics(root: Path) -> list[Path]:
    """
    Walk from 'root', following sub-sheet references, and return every reachable
    .kicad_sch file (root included), each exactly one.

    A Sheetfile reference is relative to the folder of the file that names it.
    """
    ordered: list[Path] = [] # results, in discovery order
    seen: set[Path] = set() # guards against revisits and cycles
    worklist: list[Path] = [root] # files still waiting to be processed

    while worklist:
        current = worklist.pop().resolve()

        if current in seen:
            continue

        seen.add(current)
        ordered.append(current)

        text = current.read_text()

        for child_name in sheet_files(text):
            child_path = current.parent / child_name
            worklist.append(child_path)

    return ordered
