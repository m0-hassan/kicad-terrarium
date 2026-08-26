from pathlib import Path

import pytest

from kicad_terrarium.core.extract import SymbolConflictError, symbol_blocks
from kicad_terrarium.core.library import find_symbol_sources
from kicad_terrarium.core.models import LibraryEntry, ResolutionResult, ResolvedLibrary
from kicad_terrarium.core.verify import verify_project
from kicad_terrarium.core.workflows import (
    WorkflowError,
    plan_pluck,
    plan_seal,
)

LIB = '(kicad_symbol_lib\n (version 20251024)\n (symbol "{name}"))\n'


def _project(tmp_path: Path, lib_id: str = "Foo:A") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "board.kicad_sch"
    root.write_text(
        f'(kicad_sch (lib_symbols (symbol "{lib_id}")) '
        f'(symbol (lib_id "{lib_id}") (property "Reference" "U1") '
        '(property "Value" "x") (property "Footprint" "")))'
    )
    (tmp_path / "board.kicad_pro").write_text("{}")
    return root


def test_pluck_rejects_same_name_different_definition(tmp_path):
    source = tmp_path / "source.kicad_sym"
    source.write_text(LIB.format(name="A"))
    symbol = find_symbol_sources(source, "A")[0]
    project = tmp_path / "project"
    project.mkdir()
    root = _project(project)
    library = project / "library/terrarium"
    library.mkdir(parents=True)
    (library / "source.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20251024) (symbol "A" (property "Value" "different")))'
    )
    with pytest.raises(SymbolConflictError):
        plan_pluck(symbol, root)


def test_pluck_preserves_nested_source_identity_in_its_project_namespace(tmp_path):
    source = tmp_path / "vault/sensors/environmental.kicad_sym"
    source.parent.mkdir(parents=True)
    source.write_text(LIB.format(name="SHT41"))
    symbol = find_symbol_sources(tmp_path / "vault", "SHT41")[0]
    root = _project(tmp_path / "project")

    result = plan_pluck(symbol, root)
    result.plan.apply()

    assert result.destination == (root.parent / "library/terrarium/sensors/environmental.kicad_sym")
    assert (
        '(name "Terrarium__sensors__environmental")' in (root.parent / "sym-lib-table").read_text()
    )


def test_seal_fails_before_writing_when_definition_is_missing(tmp_path, monkeypatch):
    root = _project(tmp_path)
    empty = ResolutionResult()
    monkeypatch.setattr(
        "kicad_terrarium.core.workflows.resolve_library_details", lambda _path: empty
    )
    with pytest.raises(WorkflowError, match="cannot seal"):
        plan_seal(root)
    assert not (tmp_path / "library").exists()


def test_seal_then_deep_verify_checks_actual_symbol_definitions(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = _project(project)
    source = tmp_path / "global" / "Foo.kicad_sym"
    source.parent.mkdir()
    source.write_text(LIB.format(name="A"))
    entry = LibraryEntry("Foo", "KiCad", str(source), scope="global")
    resolved = ResolutionResult({"Foo": ResolvedLibrary(entry, source)})
    monkeypatch.setattr(
        "kicad_terrarium.core.workflows.resolve_library_details", lambda _path: resolved
    )
    monkeypatch.setattr(
        "kicad_terrarium.core.workflows.resolve_global_library_details",
        lambda _path: resolved,
    )
    result = plan_seal(root)
    assert result.plan is not None
    result.plan.apply()
    assert verify_project(root).ok

    assert "Terrarium__Foo:A" in root.read_text()
    table = (project / "sym-lib-table").read_text()
    assert '(name "Foo")' not in table
    assert '(name "Terrarium__Foo")' in table
    assert "(hidden)" in table

    sealed = project / "library/terrarium/Foo.kicad_sym"
    sealed.write_text(LIB.format(name="Wrong"))
    report = verify_project(root)
    assert not report.ok
    assert any(item.code == "missing-symbol" for item in report.diagnostics)


def test_seal_directly_registers_a_nested_project_local_source(tmp_path):
    project = tmp_path / "project"
    root = _project(project)
    parts = project / "parts"
    parts.mkdir()
    source = parts / "custom.kicad_sym"
    source.write_text(LIB.format(name="A"))
    tables = project / "tables"
    tables.mkdir()
    (tables / "local.sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Foo")(type "KiCad")(uri "${KIPRJMOD}/parts/custom.kicad_sym")))'
    )
    (project / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "local")(type "Table")'
        '(uri "${KIPRJMOD}/tables/local.sym-lib-table")))'
    )

    result = plan_seal(root)
    result.plan.apply()

    assert verify_project(root).ok
    table = (project / "sym-lib-table").read_text()
    assert '(name "Foo")' in table
    assert "${KIPRJMOD}/parts/custom.kicad_sym" in table


def test_seal_migrates_a_managed_shadow_and_keeps_global_search_available(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = _project(project)
    old_library = project / "library/Foo.kicad_sym"
    old_library.parent.mkdir()
    old_library.write_text(LIB.format(name="A"))
    (project / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Foo")(type "KiCad")'
        '(uri "${KIPRJMOD}/library/Foo.kicad_sym")(options "")'
        '(descr "Managed by kicad-terrarium")))'
    )
    global_source = tmp_path / "global/Foo.kicad_sym"
    global_source.parent.mkdir()
    global_source.write_text('(kicad_symbol_lib (version 20251024) (symbol "A") (symbol "B"))')
    global_entry = LibraryEntry("Foo", "KiCad", str(global_source), scope="global")
    globals_only = ResolutionResult({"Foo": ResolvedLibrary(global_entry, global_source)})
    monkeypatch.setattr(
        "kicad_terrarium.core.workflows.resolve_global_library_details",
        lambda _path: globals_only,
    )

    result = plan_seal(root)
    result.plan.apply()

    target = project / "library/terrarium/Foo.kicad_sym"
    assert set(symbol_blocks(target.read_text())) == {"A"}
    assert "Terrarium__Foo:A" in root.read_text()
    table = (project / "sym-lib-table").read_text()
    assert '(name "Foo")' not in table
    assert '(name "Terrarium__Foo")' in table
    assert "(hidden)" in table
    assert not old_library.exists()
    assert old_library.with_name("Foo.kicad_sym.bak").is_file()
    assert root.with_name("board.kicad_sch.bak").is_file()
    assert (project / "sym-lib-table.bak").is_file()
    assert verify_project(root).ok

    second = plan_seal(root)
    assert second.plan.changes == []


def test_seal_merges_new_global_usage_into_an_existing_namespaced_workbench(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = _project(project)
    root.write_text(
        '(kicad_sch (lib_symbols (symbol "Foo:A") (symbol "Terrarium__Foo:B"))'
        '(symbol (lib_id "Foo:A")) (symbol (lib_id "Terrarium__Foo:B")))'
    )
    target = project / "library/terrarium/Foo.kicad_sym"
    target.parent.mkdir(parents=True)
    target.write_text(LIB.format(name="B"))
    (project / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Terrarium__Foo")(type "KiCad")'
        '(uri "${KIPRJMOD}/library/terrarium/Foo.kicad_sym")(options "")'
        '(descr "Managed by kicad-terrarium; mode=workbench; source=Foo")))'
    )
    global_source = tmp_path / "global/Foo.kicad_sym"
    global_source.parent.mkdir()
    global_source.write_text(LIB.format(name="A"))
    global_entry = LibraryEntry("Foo", "KiCad", str(global_source), scope="global")
    target_entry = LibraryEntry(
        "Terrarium__Foo",
        "KiCad",
        "${KIPRJMOD}/library/terrarium/Foo.kicad_sym",
        description="Managed by kicad-terrarium; mode=workbench; source=Foo",
    )
    visible = ResolutionResult(
        {
            "Foo": ResolvedLibrary(global_entry, global_source),
            "Terrarium__Foo": ResolvedLibrary(target_entry, target),
        }
    )
    monkeypatch.setattr(
        "kicad_terrarium.core.workflows.resolve_library_details",
        lambda _path: visible,
    )
    monkeypatch.setattr(
        "kicad_terrarium.core.workflows.resolve_global_library_details",
        lambda _path: ResolutionResult({"Foo": ResolvedLibrary(global_entry, global_source)}),
    )

    result = plan_seal(root)
    result.plan.apply()

    assert set(symbol_blocks(target.read_text())) == {"A", "B"}
    assert 'lib_id "Terrarium__Foo:A"' in root.read_text()
    assert "(hidden)" not in (project / "sym-lib-table").read_text()
    assert verify_project(root).ok


def test_seal_retires_a_used_machine_specific_project_registration(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = _project(project)
    external = tmp_path / "personal/Foo.kicad_sym"
    external.parent.mkdir()
    external.write_text(LIB.format(name="A"))
    (project / "sym-lib-table").write_text(
        f'(sym_lib_table (lib (name "Foo")(type "KiCad")(uri "{external}")'
        '(options "")(descr "Personal source")))'
    )
    monkeypatch.setattr(
        "kicad_terrarium.core.workflows.resolve_global_library_details",
        lambda _path: ResolutionResult(),
    )

    result = plan_seal(root)
    result.plan.apply()

    table = (project / "sym-lib-table").read_text()
    assert '(name "Foo")' not in table
    assert '(name "Terrarium__Foo")' in table
    assert "(hidden)" not in table
    assert external.is_file()
    assert verify_project(root).ok
