from kicad_terrarium.commands.browser import _build_browse_tree, _PluckAction, _SproutAction
from kicad_terrarium.commands.transfer import _execute_pluck, _execute_sprout
from kicad_terrarium.core.extract import symbol_blocks
from kicad_terrarium.core.library import find_symbol_sources

LIB = '(kicad_symbol_lib (version 20251024)\n\t(symbol "{name}"\n\t)\n)\n'


def _make_project(root: str, name: str, symbol: str):
    from pathlib import Path

    proj = Path(root) / name
    (proj / "library").mkdir(parents=True)
    (proj / f"{name}.kicad_pro").write_text("{}")
    (proj / "library" / "extras.kicad_sym").write_text(LIB.format(name=symbol))
    return proj


def test_browse_tree_curated_plucks_directly_projects_offer_choice(tmp_path):
    curated = tmp_path / "custom_symbols.kicad_sym"
    curated.write_text(LIB.format(name="MyPart"))
    roots = tmp_path / "roots"
    _make_project(str(roots), "ProjA", "Widget")

    tree = _build_browse_tree(curated, [roots], dest_name="Dest")
    assert [i.label for i in tree.items] == ["Vault", "Projects"]

    # a curated symbol is a direct pluck leaf (no sprout — you're already there)
    curated_part = next(i for i in tree.items if i.label == "Vault").children[0]
    assert curated_part.children is None
    assert isinstance(curated_part.action, _PluckAction)

    # a project symbol opens a pluck-or-sprout choice
    widget = next(i for i in tree.items if i.label == "Projects").children[0].children[0]
    assert widget.children is not None
    kinds = {type(c.action) for c in widget.children}
    assert kinds == {_PluckAction, _SproutAction}


def test_browse_tree_omits_sprout_when_no_curated_library(tmp_path):
    roots = tmp_path / "roots"
    _make_project(str(roots), "ProjA", "Widget")
    tree = _build_browse_tree(None, [roots], dest_name="Dest")
    widget = next(i for i in tree.items if i.label == "Projects").children[0].children[0]
    assert {type(c.action) for c in widget.children} == {_PluckAction}


def test_sprout_adds_symbol_to_curated_library(tmp_path):
    src = tmp_path / "src.kicad_sym"
    src.write_text(LIB.format(name="NewPart"))
    curated = tmp_path / "custom_symbols.kicad_sym"  # doesn't exist yet
    source = find_symbol_sources(src, "NewPart")[0]
    _execute_sprout(source, curated, dry_run=False)
    assert "NewPart" in symbol_blocks(curated.read_text())


def test_nested_browser_pluck_preserves_the_source_namespace(tmp_path):
    vault = tmp_path / "vault/sensors"
    vault.mkdir(parents=True)
    (vault / "environmental.kicad_sym").write_text(LIB.format(name="SHT41"))
    tree = _build_browse_tree(tmp_path / "vault", [], dest_name="board")

    vault_item = next(item for item in tree.items if item.label == "Vault")
    sensor_group = next(item for item in vault_item.children if item.label == "sensors")
    library = next(item for item in sensor_group.children if item.label == "environmental")
    symbol = next(item for item in library.children if item.label == "SHT41")
    assert isinstance(symbol.action, _PluckAction)
    assert symbol.action.source.library.group == ("sensors",)

    project = tmp_path / "project"
    project.mkdir()
    root = project / "board.kicad_sch"
    root.write_text("(kicad_sch)")
    (project / "board.kicad_pro").write_text("{}")
    _execute_pluck(symbol.action.source, root)

    assert (project / "library/terrarium/sensors/environmental.kicad_sym").is_file()
    assert '(name "Terrarium__sensors__environmental")' in (project / "sym-lib-table").read_text()
