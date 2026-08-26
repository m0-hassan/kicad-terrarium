import pytest

from kicad_terrarium.core.extract import (
    InheritanceError,
    assemble_library,
    extends_closure,
    library_version,
    merge_symbols,
    pluck_symbols,
    prune_library,
    symbol_blocks,
    vendor_library,
)

LIB = """(kicad_symbol_lib
\t(version 20251024)
\t(generator "kicad_symbol_editor")
\t(symbol "R"
\t\t(property "Description" "Resistor (generic)")
\t\t(property "Datasheet" "" (hide yes))
\t)
\t(symbol "R_US"
\t\t(extends "R")
\t)
\t(symbol "C"
\t\t(property "Description" "Capacitor")
\t)
)
"""


def test_symbol_blocks_copies_byte_for_byte():
    blocks = symbol_blocks(LIB)
    assert set(blocks) == {"R", "R_US", "C"}
    assert blocks["R"] in LIB  # verbatim slice, hide flag intact
    assert "(hide yes)" in blocks["R"]


def test_symbol_blocks_survives_parens_inside_strings():
    # "(generic)" inside the Description must not desync the depth count
    assert symbol_blocks(LIB)["R"].endswith("\t)")


def test_symbol_blocks_ignores_layout():
    # hand-edited libraries legally join `)` and the next `(symbol` on one
    # line (seen in the wild); extraction must track depth, not indentation
    lib = '(kicad_symbol_lib (version 20251024)\n\t(symbol "A"\n\t)\t(symbol "B"\n\t)\n)\n'
    assert set(symbol_blocks(lib)) == {"A", "B"}


def test_symbol_blocks_rejects_a_balanced_but_wrong_document():
    with pytest.raises(ValueError, match="kicad_symbol_lib"):
        symbol_blocks('(kicad_sch (symbol "A"))')


def test_extends_closure_pulls_in_parents_first():
    ordered, missing = extends_closure({"R_US"}, symbol_blocks(LIB))
    assert ordered == ["R", "R_US"]
    assert missing == set()


def test_extends_closure_reports_missing_names():
    ordered, missing = extends_closure({"C", "Nope"}, symbol_blocks(LIB))
    assert ordered == ["C"]
    assert missing == {"Nope"}


def test_extends_closure_ignores_parent_like_text_in_a_property():
    blocks = symbol_blocks(
        "(kicad_symbol_lib (version 20251024) "
        '(symbol "A" (property "Description" "example (extends \\"NotAParent\\")")))'
    )
    assert extends_closure({"A"}, blocks) == (["A"], set())


def test_extends_closure_rejects_cycles():
    cyclic = {
        "A": '(symbol "A" (extends "B"))',
        "B": '(symbol "B" (extends "A"))',
    }
    with pytest.raises(InheritanceError, match="A -> B -> A"):
        extends_closure({"A"}, cyclic)


def test_assemble_library_reuses_source_version():
    blocks = symbol_blocks(LIB)
    out = assemble_library(["C"], blocks, LIB)
    assert "(version 20251024)" in out and out.startswith("(kicad_symbol_lib")


def test_assemble_library_preserves_crlf_without_doubling_carriage_returns():
    source = LIB.replace("\n", "\r\n")
    blocks = symbol_blocks(source)
    out = assemble_library(["R"], blocks, source)
    assert "\r\r\n" not in out
    assert blocks["R"] in out
    assert out.count("\r\n") == out.count("\n")


def test_vendor_library_end_to_end():
    out, kept, missing = vendor_library(LIB, {"R_US"})
    assert kept == ["R", "R_US"] and missing == set()
    assert '(symbol "C"' not in out and "(hide yes)" in out


def test_pluck_symbols_includes_parents():
    additions, missing = pluck_symbols(LIB, {"R_US"})
    assert set(additions) == {"R", "R_US"} and missing == set()


def test_merge_symbols_into_none_creates_library():
    additions, _ = pluck_symbols(LIB, {"C"})
    out, added = merge_symbols(None, additions, library_version(LIB))
    assert added == ["C"]
    assert out.startswith("(kicad_symbol_lib") and '(symbol "C"' in out


def test_merge_symbols_appends_without_touching_existing():
    base, _ = merge_symbols(None, pluck_symbols(LIB, {"C"})[0], "20251024")
    merged, added = merge_symbols(base, pluck_symbols(LIB, {"R_US"})[0])
    assert added == ["R", "R_US"]
    assert '(symbol "C"' in merged  # existing symbol preserved
    assert merged.count('(symbol "R_US"') == 1


def test_merge_symbols_skips_duplicates():
    base, _ = merge_symbols(None, pluck_symbols(LIB, {"C"})[0], "20251024")
    merged, added = merge_symbols(base, pluck_symbols(LIB, {"C"})[0])
    assert added == [] and merged == base


def test_prune_library_keeps_used_and_parents_removes_the_rest():
    out, kept, removed = prune_library(LIB, {"R_US"})
    assert kept == ["R", "R_US"]  # parent kept even though not used directly
    assert removed == ["C"]
    assert '(symbol "C"' not in out and "(hide yes)" in out  # kept blocks byte-exact


def test_prune_library_nothing_used_removes_everything():
    out, kept, removed = prune_library(LIB, set())
    assert kept == []
    assert set(removed) == {"R", "R_US", "C"}
    assert '(symbol "' not in out  # empty library


def test_prune_library_all_used_is_a_noop():
    _, kept, removed = prune_library(LIB, {"R", "R_US", "C"})
    assert removed == [] and set(kept) == {"R", "R_US", "C"}


def test_prune_refuses_to_preserve_a_symbol_without_its_parent():
    broken = '(kicad_symbol_lib (version 20251024) (symbol "Child" (extends "Gone")))'
    with pytest.raises(ValueError, match="missing used definitions or parents"):
        prune_library(broken, {"Child"})


def test_prune_refuses_to_delete_a_library_missing_its_used_symbol():
    with pytest.raises(ValueError, match="Missing"):
        prune_library(LIB, {"Missing"})
