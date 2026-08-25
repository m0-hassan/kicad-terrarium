from kicad_terrarium.cli import _PLANT_FRAMES, _draw_plant


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
