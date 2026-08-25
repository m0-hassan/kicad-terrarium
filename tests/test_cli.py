from kicad_terrarium.cli import (
    _PLANT_FRAMES,
    _build_browse_tree,
    _draw_plant,
    _PluckAction,
    _sprout,
    _SproutAction,
)
from kicad_terrarium.core.extract import symbol_blocks

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
    assert [i.label for i in tree.items] == ["Curated library", "Projects"]

    # a curated symbol is a direct pluck leaf (no sprout — you're already there)
    curated_part = next(i for i in tree.items if i.label == "Curated library").children[0]
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
    _sprout("NewPart", src, curated, dry_run=False)
    assert "NewPart" in symbol_blocks(curated.read_text())


class FakeScreen:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def addnstr(self, y: int, x: int, s: str, n: int, attr: int) -> None:
        self.lines.append(s)


def test_draw_plant_renders_the_current_frame_when_there_is_room():
    screen = FakeScreen()
    _draw_plant(screen, height=30, width=80, frame=1)
    assert screen.lines == _PLANT_FRAMES[1]


def test_draw_plant_cycles_frames():
    seen = set()
    for frame in range(len(_PLANT_FRAMES) * 2):  # wraps via modulo
        screen = FakeScreen()
        _draw_plant(screen, 30, 80, frame)
        seen.add(tuple(screen.lines))
    assert seen == {tuple(f) for f in _PLANT_FRAMES}  # every frame appears, sways


def test_draw_plant_skips_when_terminal_too_small():
    screen = FakeScreen()
    _draw_plant(screen, height=5, width=8, frame=0)
    assert screen.lines == []
