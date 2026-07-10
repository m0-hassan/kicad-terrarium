from kicad_terrarium.core.discover import find_lib_ids, library_counts, used_symbols

def test_find_lib_ids_extracts_each_reference():
    text = '(lib_id "Device:R") junk (lib_id "Device:C")'
    assert find_lib_ids(text) == ["Device:R", "Device:C"]

def test_library_counts_tallies_per_library():
    ids = ["Device:R", "Device:C", "Connector:X"]
    assert library_counts(ids) == {"Device": 2, "Connector": 1}

def test_used_symbols_keeps_only_named_library():
    ids = ["al-mawja-library:C", "al-mawja-library:R", "Device:X"]
    assert used_symbols(ids, "al-mawja-library") == {"C", "R"}
