from kicad_terrarium.core.tables import merge_sym_lib_table
from kicad_terrarium.core.verify import registered_libraries


def test_merge_into_empty_creates_valid_table():
    out = merge_sym_lib_table(None, ["Device", "power"])
    assert registered_libraries(out) == {"Device", "power"}
    assert out.startswith("(sym_lib_table") and out.rstrip().endswith(")")


def test_merge_preserves_existing_entries_and_skips_duplicates():
    existing = (
        "(sym_lib_table\n\t(version 7)\n"
        '\t(lib (name "mine")(type "KiCad")(uri "${KIPRJMOD}/library/custom.kicad_sym")'
        '(options "")(descr "hand-made"))\n)\n'
    )
    out = merge_sym_lib_table(existing, ["mine", "Device"])
    assert registered_libraries(out) == {"mine", "Device"}
    assert "hand-made" in out  # existing entry untouched, not rewritten
    assert out.count('(name "mine")') == 1
