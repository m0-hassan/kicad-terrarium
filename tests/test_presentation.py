from rich.text import Text

from kicad_terrarium.presentation import (
    DONE,
    detect_theme,
    line_colors,
    render_banner,
    status_line,
)


def test_theme_detection_honors_explicit_and_colorfgbg(monkeypatch):
    assert detect_theme("light") == "light"
    assert detect_theme("dark") == "dark"
    monkeypatch.setenv("COLORFGBG", "0;15")
    assert detect_theme("auto") == "light"
    monkeypatch.setenv("COLORFGBG", "not-a-number")
    assert detect_theme("auto") == "dark"


def test_banner_and_status_use_structured_rich_text():
    assert isinstance(render_banner("light"), Text)
    assert status_line(DONE, "finished").plain == "done      finished"
    assert line_colors(0, ["green"]) == []
    assert line_colors(2, []) == []


def test_gradient_interpolates_between_botanical_stops():
    assert line_colors(5, ["#000000", "#ffffff"]) == [
        "#000000",
        "#404040",
        "#808080",
        "#bfbfbf",
        "#ffffff",
    ]
