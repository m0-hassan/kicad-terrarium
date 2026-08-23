from pathlib import Path

from kicad_terrarium.core.resolve import expand_uri, parse_lib_table, resolve_libraries

KICAD9_STYLE = '(lib (name "a")(type "KiCad")(uri "/tmp/a.kicad_sym")(options "")(descr ""))'
KICAD10_STYLE = '(lib (name "a") (type "KiCad") (uri "/tmp/a.kicad_sym") (options "") (descr ""))'


def test_parse_lib_table_handles_both_spacing_styles():
    assert parse_lib_table(KICAD9_STYLE) == [("a", "KiCad", "/tmp/a.kicad_sym")]
    assert parse_lib_table(KICAD10_STYLE) == [("a", "KiCad", "/tmp/a.kicad_sym")]


def test_expand_uri_substitutes_kiprjmod_and_versioned_symbol_dir():
    assert expand_uri("${KIPRJMOD}/library/x.kicad_sym", Path("/proj")) == Path(
        "/proj/library/x.kicad_sym"
    )
    assert expand_uri(
        "${KICAD10_SYMBOL_DIR}/Device.kicad_sym", Path("/proj"), share_dir=Path("/share")
    ) == Path("/share/symbols/Device.kicad_sym")


def test_resolve_project_shadows_global_and_drops_missing(tmp_path):
    # fake global config: kicad/9.0 registers "dev" and a dangling "ghost"
    share = tmp_path / "share"
    (share / "symbols").mkdir(parents=True)
    (share / "symbols/dev.kicad_sym").write_text("x")
    config = tmp_path / "config"
    (config / "9.0").mkdir(parents=True)
    (config / "9.0/sym-lib-table").write_text(
        "(sym_lib_table"
        ' (lib (name "dev")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/dev.kicad_sym"))'
        ' (lib (name "ghost")(type "KiCad")(uri "/nope/ghost.kicad_sym")))'
    )
    # project registers its own "dev", which must win
    proj = tmp_path / "proj"
    (proj / "library").mkdir(parents=True)
    (proj / "library/dev.kicad_sym").write_text("x")
    (proj / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "dev")(type "KiCad")(uri "${KIPRJMOD}/library/dev.kicad_sym")))'
    )
    libs = resolve_libraries(proj, share_dir=share, config_dir=config)
    assert libs == {"dev": proj / "library/dev.kicad_sym"}


def test_resolve_follows_nested_table_indirection(tmp_path):
    # KiCad 10 global table points at the stock table via (type "Table")
    share = tmp_path / "share"
    (share / "symbols").mkdir(parents=True)
    (share / "symbols/Device.kicad_sym").write_text("x")
    stock = share / "template-sym-lib-table"
    stock.write_text(
        '(sym_lib_table (lib (name "Device") (type "KiCad")'
        ' (uri "${KICAD10_SYMBOL_DIR}/Device.kicad_sym")))'
    )
    config = tmp_path / "config"
    (config / "10.0").mkdir(parents=True)
    (config / "10.0/sym-lib-table").write_text(
        f'(sym_lib_table (lib (name "KiCad") (type "Table") (uri "{stock}")))'
    )
    libs = resolve_libraries(tmp_path / "proj", share_dir=share, config_dir=config)
    assert libs == {"Device": share / "symbols/Device.kicad_sym"}
