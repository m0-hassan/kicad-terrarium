from kicad_terrarium.core.extract import (
    assemble_library,
    extends_closure,
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


def test_extends_closure_pulls_in_parents_first():
    ordered, missing = extends_closure({"R_US"}, symbol_blocks(LIB))
    assert ordered == ["R", "R_US"]
    assert missing == set()


def test_extends_closure_reports_missing_names():
    ordered, missing = extends_closure({"C", "Nope"}, symbol_blocks(LIB))
    assert ordered == ["C"]
    assert missing == {"Nope"}


def test_assemble_library_reuses_source_version():
    blocks = symbol_blocks(LIB)
    out = assemble_library(["C"], blocks, LIB)
    assert "(version 20251024)" in out and out.startswith("(kicad_symbol_lib")


def test_vendor_library_end_to_end():
    out, kept, missing = vendor_library(LIB, {"R_US"})
    assert kept == ["R", "R_US"] and missing == set()
    assert '(symbol "C"' not in out and "(hide yes)" in out
