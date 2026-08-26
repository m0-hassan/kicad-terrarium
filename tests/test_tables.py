import pytest

from kicad_terrarium.core.tables import (
    merge_sym_lib_table,
    parse_library_entries,
    portable_project_uri,
    remove_from_sym_lib_table,
    upsert_sym_lib_table,
    upsert_sym_lib_uris,
    validate_library_nickname,
)
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


def test_remove_from_sym_lib_table_drops_named_entries_only():
    table = merge_sym_lib_table(None, ["Device", "power", "mo-parts"])
    out = remove_from_sym_lib_table(table, ["mo-parts"])
    assert registered_libraries(out) == {"Device", "power"}
    assert out.startswith("(sym_lib_table") and out.rstrip().endswith(")")


def test_remove_handles_multiline_and_single_line_entries():
    table = """(sym_lib_table
  (lib
    (name "drop")
    (type "KiCad")
    (uri "/tmp/drop.kicad_sym"))
  (lib (name "keep")(type "KiCad")(uri "/tmp/keep.kicad_sym")))"""
    out = remove_from_sym_lib_table(table, ["drop"])
    assert registered_libraries(out) == {"keep"}


def test_upsert_replaces_external_registration_with_canonical_local_uri():
    table = '(sym_lib_table (lib (name "Foo")(type "KiCad")(uri "/outside/Foo.kicad_sym")))'
    out = upsert_sym_lib_table(table, ["Foo"])
    assert out.count('(name "Foo")') == 1
    assert "${KIPRJMOD}/library/Foo.kicad_sym" in out


def test_merge_deduplicates_duplicate_requested_names():
    out = merge_sym_lib_table(None, ["Foo", "Foo"])
    assert out.count('(name "Foo")') == 1


def test_upsert_explicit_uri_preserves_noncanonical_project_layout():
    out = upsert_sym_lib_uris(None, {"Foo": "${KIPRJMOD}/parts/custom.kicad_sym"})
    assert out.count('(name "Foo")') == 1
    assert "${KIPRJMOD}/parts/custom.kicad_sym" in out


def test_upsert_can_hide_a_loaded_dependency_and_preserve_provenance():
    out = upsert_sym_lib_uris(
        None,
        {"Terrarium__Device": "${KIPRJMOD}/library/terrarium/Device.kicad_sym"},
        hidden_names={"Terrarium__Device"},
        descriptions={
            "Terrarium__Device": ("Managed by kicad-terrarium; mode=sealed; source=Device")
        },
    )
    [entry] = parse_library_entries(out)
    assert entry.hidden is True
    assert entry.enabled is True
    assert entry.description.endswith("source=Device")


def test_portable_project_uri_rejects_machine_specific_locations():
    assert portable_project_uri("${KIPRJMOD}/parts/custom.kicad_sym")
    assert portable_project_uri("parts/custom.kicad_sym")
    assert not portable_project_uri("${MY_LIBS}/custom.kicad_sym")
    assert not portable_project_uri("/Users/me/custom.kicad_sym")
    assert not portable_project_uri(r"C:\\Users\\me\\custom.kicad_sym")


def test_generated_library_names_are_portable_to_windows():
    for name in ("CON", "bad.", "bad?name", "bad/name"):
        with pytest.raises(ValueError, match="unsafe"):
            validate_library_nickname(name)


def test_structural_table_parser_rejects_incomplete_entries():
    with pytest.raises(ValueError, match="quoted uri"):
        parse_library_entries('(sym_lib_table (lib (name "Foo")(type "KiCad")))')
