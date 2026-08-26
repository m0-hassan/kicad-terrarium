import pytest

from kicad_terrarium.core.discover import placed_symbols, reassign_footprints
from kicad_terrarium.core.repoint import repoint_libraries
from kicad_terrarium.core.sexpr import (
    SExprError,
    apply_replacements,
    atoms,
    child_forms,
    descendant_forms,
    forms,
    quote,
    quoted_tokens,
    root_form,
)

REFORMATTED = """(kicad_sch (lib_symbols (symbol "Foo:A" (pin (number "1"))))
  (symbol (lib_id "Foo:A") (property "Reference" "U1")
    (property "Value" "Widget (custom)") (property "Footprint" "")))"""


def test_structural_discovery_does_not_depend_on_tabs_or_newlines():
    symbols = placed_symbols(REFORMATTED)
    assert len(symbols) == 1
    assert symbols[0].reference == "U1"
    assert str(symbols[0].symbol_id) == "Foo:A"


def test_exact_span_footprint_edit_preserves_unrelated_text():
    output, applied = reassign_footprints(
        REFORMATTED,
        lambda _ref, _lib, _value, current: "Package:One" if not current else None,
    )
    assert applied == [("U1", "Package:One")]
    assert '(property "Value" "Widget (custom)")' in output
    assert output.count("Package:One") == 1


def test_repoint_never_changes_descriptions_or_values():
    text = """(kicad_sch
      (lib_symbols (symbol "old:A" (property "Description" "old:do not edit")))
      (symbol (lib_id "old:A") (property "Value" "old:A")))"""
    output, counts = repoint_libraries(text, {"old": "new"})
    assert counts == {"old": 2}
    assert '(symbol "new:A"' in output
    assert '(lib_id "new:A")' in output
    assert '"old:do not edit"' in output
    assert '(property "Value" "old:A")' in output


def test_child_forms_cannot_leak_from_a_later_sibling():
    text = '(root (one (value "a")) (two (value "b")))'
    all_forms = forms(text)
    root = root_form(text, "root")
    one = child_forms(all_forms, root, "one")[0]
    assert len(child_forms(all_forms, one, "value")) == 1


def test_malformed_document_is_rejected():
    with pytest.raises(SExprError):
        forms('(root "unterminated)')


def test_tokens_atoms_descendants_and_escaping():
    text = r'(root yes (child "line\n\"quoted\"") (nested (child "deep")))'
    all_forms = forms(text)
    root = root_form(text)
    assert atoms(text, root) == ["yes"]
    children = descendant_forms(all_forms, root, "child")
    assert len(children) == 2
    assert quoted_tokens(text, children[0])[0].value == 'line\n"quoted"'
    assert quote('a\\b"c') == '"a\\\\b\\"c"'


def test_atoms_allows_whitespace_between_open_paren_and_head():
    text = "(   value yes)"
    assert atoms(text, root_form(text, "value")) == ["yes"]


def test_root_validation_and_replacement_overlap_errors():
    with pytest.raises(SExprError, match="expected one"):
        root_form("(a)(b)")
    with pytest.raises(SExprError, match="expected \\(wanted"):
        root_form("(actual)", "wanted")
    with pytest.raises(ValueError, match="overlapping"):
        apply_replacements("abcdef", [(1, 4, "x"), (3, 5, "y")])
    assert apply_replacements("abcdef", [(1, 2, "X"), (4, 5, "Y")]) == "aXcdYf"
