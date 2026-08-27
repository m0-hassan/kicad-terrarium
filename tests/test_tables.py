import pytest

from kicad_terrarium.core.tables import (
    parse_library_entries,
    portable_project_uri,
    remove_from_fp_lib_table,
    remove_from_sym_lib_table,
    upsert_fp_lib_uris,
    upsert_sym_lib_uris,
    validate_library_nickname,
)


def _names(text: str) -> set[str]:
    return {entry.nickname for entry in parse_library_entries(text)}


def test_parser_handles_compact_and_spaced_table_fields():
    for entry in (
        '(lib (name "a")(type "KiCad")(uri "/tmp/a.kicad_sym")(options ""))',
        '(lib (name "a") (type "KiCad") (uri "/tmp/a.kicad_sym") (options ""))',
    ):
        [parsed] = parse_library_entries(f"(sym_lib_table {entry})")
        assert (parsed.nickname, parsed.library_type, parsed.uri) == (
            "a",
            "KiCad",
            "/tmp/a.kicad_sym",
        )


def test_remove_from_sym_lib_table_drops_named_entries_only():
    table = """(sym_lib_table
  (lib (name "Device")(type "KiCad")(uri "/tmp/Device.kicad_sym"))
  (lib (name "power")(type "KiCad")(uri "/tmp/power.kicad_sym"))
  (lib (name "mo-parts")(type "KiCad")(uri "/tmp/mo-parts.kicad_sym")))"""
    out = remove_from_sym_lib_table(table, ["mo-parts"])
    assert _names(out) == {"Device", "power"}
    assert out.startswith("(sym_lib_table") and out.rstrip().endswith(")")


def test_remove_handles_multiline_and_single_line_entries():
    table = """(sym_lib_table
  (lib
    (name "drop")
    (type "KiCad")
    (uri "/tmp/drop.kicad_sym"))
    (lib (name "keep")(type "KiCad")(uri "/tmp/keep.kicad_sym")))"""
    out = remove_from_sym_lib_table(table, ["drop"])
    assert _names(out) == {"keep"}


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


def test_footprint_table_edits_use_the_fp_root_and_portable_uris():
    original = '(fp_lib_table (lib (name "Old")(type "KiCad")(uri "/tmp/old.pretty")))'
    without_old = remove_from_fp_lib_table(original, ["Old"])
    output = upsert_fp_lib_uris(
        without_old,
        {"Terrarium__Parts": "${KIPRJMOD}/library/terrarium/footprints/Parts.pretty"},
        hidden_names={"Terrarium__Parts"},
    )

    [entry] = parse_library_entries(output)
    assert entry.nickname == "Terrarium__Parts"
    assert entry.hidden is True


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
