from kicad_terrarium.core.verify import external_libraries, registered_libraries


def test_nothing_external_when_all_registered():
    assert external_libraries({"terrarium"}, {"terrarium"}) == set()


def test_flags_libraries_not_in_the_table():
    assert external_libraries({"terrarium", "Device"}, {"terrarium"}) == {"Device"}


def test_registered_libraries_parses_names_from_table():
    table = '(sym_lib_table (lib (name "terrarium")(type "KiCad")) (lib (name "power")))'
    assert registered_libraries(table) == {"terrarium", "power"}


def test_registered_libraries_ignores_names_outside_lib_entries():
    table = '(sym_lib_table (name "loose") (lib (name "real")(type "KiCad")))'
    assert registered_libraries(table) == {"real"}
