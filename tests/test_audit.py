from kicad_terrarium.core.audit import (
    cache_symbol_pins,
    foreign_model_paths,
    missing_pads,
    pad_names,
)
from kicad_terrarium.core.discover import symbol_instances

SHEET = """(kicad_sch
\t(lib_symbols
\t\t(symbol "Comparator:TLV1872"
\t\t\t(symbol "TLV1872_1_1"
\t\t\t\t(pin (number "1")) (pin (number "10"))
\t\t\t)
\t\t)
\t)
\t(symbol
\t\t(lib_id "Comparator:TLV1872")
\t\t(property "Reference" "U1")
\t\t(property "Footprint" "Package_SO:SOIC-8")
\t)
)
"""


def test_symbol_instances_skips_cache_and_reads_properties():
    assert symbol_instances(SHEET) == [("U1", "Comparator:TLV1872", "Package_SO:SOIC-8")]


def test_cache_symbol_pins_collects_numbers_across_units():
    assert cache_symbol_pins(SHEET) == {"Comparator:TLV1872": {"1", "10"}}


def test_pad_names_reads_new_and_old_formats_and_drops_unnamed():
    new = '(pad "1" smd) (pad "SH" thru_hole) (pad "" smd)'
    old = "(pad 3 thru_hole (at 0 0)"
    assert pad_names(new) == {"1", "SH"}
    assert pad_names(old) == {"3"}


def test_missing_pads_is_the_tlv1872_check():
    pins = {str(n) for n in range(1, 11)}  # 10-pin symbol
    pads = {str(n) for n in range(1, 9)}  # 8-pad SOIC footprint
    assert missing_pads(pins, pads) == {"9", "10"}


def test_missing_pads_allows_extra_pads():
    assert missing_pads({"1", "2"}, {"1", "2", "EP"}) == set()


def test_foreign_model_paths_flags_only_untravelable_refs():
    mod = (
        '(model "${KIPRJMOD}/library/3dmodels/a.step")'
        '(model "${KICAD10_3DMODEL_DIR}/b.wrl")'
        '(model "${KICAD_PERSONAL_MODELS}/custom.step")'
        '(model "/Users/someone/Downloads/c.step")'
    )
    assert foreign_model_paths(mod) == [
        "${KICAD_PERSONAL_MODELS}/custom.step",
        "/Users/someone/Downloads/c.step",
    ]
