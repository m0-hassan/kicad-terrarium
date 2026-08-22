from pathlib import Path

from kicad_terrarium.core.project import project_lib_ids, project_schematics

# An in-memory "project": root -> sub-sheet -> back to root (a cycle).
FAKE_SHEETS = {
    Path("/proj/root.kicad_sch").resolve(): ('(property "Sheetfile" "sub/power.kicad_sch"'),
    Path("/proj/sub/power.kicad_sch").resolve(): (
        '(lib_id "Device:R") (property "Sheetfile" "../root.kicad_sch"'
    ),
}


def fake_read(path: Path) -> str:
    return FAKE_SHEETS[path.resolve()]


def test_walk_finds_root_and_children_in_order():
    sheets = project_schematics(Path("/proj/root.kicad_sch"), read_text=fake_read)
    assert [s.name for s in sheets] == ["root.kicad_sch", "power.kicad_sch"]


def test_walk_survives_reference_cycles():
    # power.kicad_sch points back at root; without the seen-set this loops forever
    sheets = project_schematics(Path("/proj/root.kicad_sch"), read_text=fake_read)
    assert len(sheets) == 2


def test_project_lib_ids_aggregates_across_sheets():
    assert project_lib_ids(Path("/proj/root.kicad_sch"), read_text=fake_read) == ["Device:R"]
