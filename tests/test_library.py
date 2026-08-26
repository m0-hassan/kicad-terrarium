from kicad_terrarium.core.library import discover_libraries, find_symbol_sources

LIB = '(kicad_symbol_lib (version 20251024) (symbol "{name}"))'


def test_directory_vault_supports_nested_packed_sublibraries(tmp_path):
    vault = tmp_path / "vault"
    nested = vault / "sensors"
    nested.mkdir(parents=True)
    (nested / "environmental.kicad_sym").write_text(LIB.format(name="SHT41"))
    (vault / "passives.kicad_sym").write_text(LIB.format(name="R_Custom"))
    libraries = discover_libraries(vault)
    assert [(item.group, item.nickname) for item in libraries] == [
        ((), "passives"),
        (("sensors",), "environmental"),
    ]


def test_unpacked_symdir_is_one_logical_library(tmp_path):
    directory = tmp_path / "Device.kicad_symdir"
    directory.mkdir()
    (directory / "R.kicad_sym").write_text(LIB.format(name="R"))
    (directory / "C.kicad_sym").write_text(LIB.format(name="C"))
    libraries = discover_libraries(directory)
    assert len(libraries) == 1
    assert libraries[0].nickname == "Device"
    assert {match.symbol for match in find_symbol_sources(directory, "R")} == {"R"}


def test_duplicate_names_across_sublibraries_remain_ambiguous(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.kicad_sym").write_text(LIB.format(name="Shared"))
    (vault / "b.kicad_sym").write_text(LIB.format(name="Shared"))
    assert len(find_symbol_sources(vault, "Shared")) == 2
    assert len(find_symbol_sources(vault, "Shared", library="b")) == 1


def test_nested_selector_disambiguates_repeated_library_nicknames(tmp_path):
    vault = tmp_path / "vault"
    for group in ("a", "b"):
        directory = vault / group
        directory.mkdir(parents=True)
        (directory / "parts.kicad_sym").write_text(LIB.format(name="Shared"))

    assert len(find_symbol_sources(vault, "Shared", library="parts")) == 2
    selected = find_symbol_sources(vault, "Shared", library="b/parts")
    assert len(selected) == 1
    assert selected[0].library.selector == "b/parts"
