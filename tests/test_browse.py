from kicad_terrarium.core.browse import Browser, Item, Screen, search_items


def make_browser() -> Browser:
    tree = [
        Item("Curated library", children=[Item("Conn_Coaxial_INVERT", action=("pluck", "coax"))]),
        Item("Projects", children=[Item("PID")]),
    ]
    return Browser(Screen("kicad-terrarium", tree))


def test_move_wraps_at_both_ends():
    b = make_browser()
    assert b.screen.cursor == 0
    b.move(-1)  # up from the top wraps to the bottom
    assert b.screen.cursor == 1
    b.move(1)  # down from the bottom wraps to the top
    assert b.screen.cursor == 0


def test_enter_submenu_pushes_screen_and_back_pops():
    b = make_browser()
    assert b.enter() is None  # into "Curated library"
    assert b.screen.title == "Curated library"
    assert [i.label for i in b.screen.items] == ["Conn_Coaxial_INVERT"]
    assert b.back() is True
    assert b.screen.title == "kicad-terrarium"


def test_enter_leaf_returns_its_action():
    b = make_browser()
    b.enter()  # into Curated library
    assert b.enter() == ("pluck", "coax")  # leaf action bubbles up


def test_back_at_root_is_false():
    assert make_browser().back() is False


def test_enter_empty_screen_is_none():
    assert Browser(Screen("empty", [])).enter() is None


def test_search_flattens_matching_leaves_and_keeps_actions():
    root = make_browser().screen
    matches = search_items(root.items, "coax")
    assert len(matches) == 1
    assert matches[0].action == ("pluck", "coax")
