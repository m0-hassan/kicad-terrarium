from kicad_terrarium.core.discover import find_lib_ids, library_counts, sheet_files, used_symbols


def test_find_lib_ids_extracts_each_reference():
    text = '(kicad_sch (symbol (lib_id "Device:R")) (symbol (lib_id "Device:C")))'
    assert find_lib_ids(text) == ["Device:R", "Device:C"]


def test_library_counts_tallies_per_library():
    ids = ["Device:R", "Device:C", "Connector:X"]
    assert library_counts(ids) == {"Device": 2, "Connector": 1}


def test_used_symbols_keeps_only_named_library():
    ids = ["al-mawja-library:C", "al-mawja-library:R", "Device:X"]
    assert used_symbols(ids, "al-mawja-library") == {"C", "R"}


def test_sheet_files_only_reads_hierarchical_sheet_properties():
    text = """(kicad_sch
      (symbol (property "Sheetfile" "not-a-sheet.kicad_sch"))
      (sheet (property "Sheetfile" "real-sheet.kicad_sch")))"""
    assert sheet_files(text) == ["real-sheet.kicad_sch"]
