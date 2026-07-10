from kicad_terrarium.core.verify import external_libraries, registered_libraries

def test_nothing_external_when_all_registered():
    assert external_libraries({"terrarium"}, {"terrarium"}) == set()

def test_flags_libraries_not_in_the_table():
    external_libraries({"terrarium"}, {"Device"}) == {"Device"}
