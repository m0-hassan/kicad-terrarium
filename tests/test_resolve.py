from pathlib import Path

from kicad_terrarium.core.resolve import (
    configured_path_variables,
    direct_library_registration,
    expand_uri,
    resolve_global_library_details,
    resolve_library_details,
)


def test_expand_uri_substitutes_kiprjmod_and_versioned_symbol_dir():
    assert expand_uri("${KIPRJMOD}/library/x.kicad_sym", Path("/proj")) == Path(
        "/proj/library/x.kicad_sym"
    )
    assert expand_uri(
        "${KICAD10_SYMBOL_DIR}/Device.kicad_sym", Path("/proj"), share_dir=Path("/share")
    ) == Path("/share/symbols/Device.kicad_sym")


def test_expand_uri_resolves_nested_user_variables():
    assert expand_uri(
        "${LIB_ROOT}/${FAMILY}/Part.kicad_sym",
        Path("/proj"),
        variables={
            "LIB_ROOT": "${HOME}/libs",
            "FAMILY": "sensors",
            "HOME": "/users/me",
        },
    ) == Path("/users/me/libs/sensors/Part.kicad_sym")


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
    details = resolve_library_details(proj, share_dir=share, config_dir=config)
    assert {name: item.path for name, item in details.libraries.items()} == {
        "dev": proj / "library/dev.kicad_sym"
    }


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
    details = resolve_library_details(tmp_path / "proj", share_dir=share, config_dir=config)
    assert {name: item.path for name, item in details.libraries.items()} == {
        "Device": share / "symbols/Device.kicad_sym"
    }


def test_resolve_reads_custom_kicad_path_variables(tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    source = custom / "Mine.kicad_sym"
    source.write_text("x")
    config = tmp_path / "config"
    version = config / "10.0"
    version.mkdir(parents=True)
    (version / "kicad_common.json").write_text(
        '{"environment":{"vars":{"MY_LIBS":"' + str(custom) + '"}}}'
    )
    (version / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Mine")(type "KiCad")(uri "${MY_LIBS}/Mine.kicad_sym")))'
    )
    details = resolve_library_details(tmp_path / "project", config_dir=config)
    assert {name: item.path for name, item in details.libraries.items()} == {"Mine": source}
    assert configured_path_variables(config, table_name="sym-lib-table") == {"MY_LIBS": str(custom)}


def test_direct_registration_uses_custom_kicad_path_variables(tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    source = custom / "Mine.pretty"
    source.mkdir()
    config = tmp_path / "config"
    version = config / "10.0"
    version.mkdir(parents=True)
    (version / "kicad_common.json").write_text(
        '{"environment":{"vars":{"MY_LIBS":"' + str(custom) + '"}}}'
    )
    (version / "fp-lib-table").write_text("(fp_lib_table)")
    project = tmp_path / "project"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Mine")(type "KiCad")(uri "${MY_LIBS}/Mine.pretty")))'
    )

    registration = direct_library_registration(
        project,
        "Mine",
        table_name="fp-lib-table",
        config_dir=config,
    )

    assert registration is not None
    assert registration[1] == source


def test_dangling_project_registration_does_not_fall_back_to_global(tmp_path):
    share = tmp_path / "share"
    (share / "symbols").mkdir(parents=True)
    global_source = share / "symbols" / "Foo.kicad_sym"
    global_source.write_text("global")
    config = tmp_path / "config"
    (config / "10.0").mkdir(parents=True)
    (config / "10.0/sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Foo")(type "KiCad")'
        '(uri "${KICAD10_SYMBOL_DIR}/Foo.kicad_sym")))'
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Foo")(type "KiCad")(uri "/missing/Foo.kicad_sym")))'
    )
    details = resolve_library_details(project, share_dir=share, config_dir=config)
    assert "Foo" not in details.libraries
    assert any(item.code == "missing-library" for item in details.diagnostics)

    global_details = resolve_global_library_details(
        project,
        share_dir=share,
        config_dir=config,
    )
    assert global_details.libraries["Foo"].path == global_source
