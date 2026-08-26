import pytest

from kicad_terrarium.core.discover import reassign_footprints
from kicad_terrarium.core.sizing import (
    SizingConfigError,
    default_rules,
    footprint_for,
    parse_capacitance,
    parse_resistance,
    rules_from_config,
)


@pytest.mark.parametrize(
    "value, farads",
    [
        ("100nF", 100e-9),
        ("4.7nF", 4.7e-9),
        ("10uF", 10e-6),
        ("470pF", 470e-12),
        ("1uF", 1e-6),
        ("4n7", 4.7e-9),  # RKM embedded-decimal notation
        ("1µF", 1e-6),
    ],
)
def test_parse_capacitance(value, farads):
    assert parse_capacitance(value) == pytest.approx(farads)


@pytest.mark.parametrize(
    "value, ohms",
    [("10k", 10e3), ("33R", 33), ("4R7", 4.7), ("3.32k", 3320), ("100", 100), ("1M", 1e6)],
)
def test_parse_resistance(value, ohms):
    assert parse_resistance(value) == pytest.approx(ohms)


def test_parse_rejects_garbage():
    assert parse_capacitance("DNP") is None
    assert parse_resistance("") is None
    assert parse_capacitance("nan") is None
    assert parse_capacitance("inf") is None


def test_footprint_for_dispatches_by_symbol_and_value():
    rules = default_rules()
    assert footprint_for("Device:R_US", "100k", rules) == "Resistor_SMD:R_0603_1608Metric"
    assert footprint_for("Device:C_Small", "100nF", rules) == "Capacitor_SMD:C_0603_1608Metric"
    assert footprint_for("Device:C_Small", "10uF", rules) == "Capacitor_SMD:C_0805_2012Metric"
    # exactly 1uF is inclusive on the 0603 threshold
    assert footprint_for("Device:C", "1uF", rules) == "Capacitor_SMD:C_0603_1608Metric"


def test_footprint_for_refuses_inductors_and_unknowns():
    rules = default_rules()
    assert footprint_for("Device:L", "15uH", rules) is None
    assert footprint_for("MCU_ST:STM32", "", rules) is None
    assert footprint_for("Device:C", "DNP", rules) is None  # unparseable value
    assert footprint_for("Device:C", "-1uF", rules) is None
    assert footprint_for("Device:C_Polarized", "100uF", rules) is None


def test_rules_from_config_overrides_and_parses_thresholds():
    rules = rules_from_config(
        {
            "resistor": "Resistor_SMD:R_0402_1005Metric",
            "capacitor": [
                {"max": "100nF", "footprint": "small"},
                {"footprint": "big"},
            ],
        }
    )
    assert rules.resistor == "Resistor_SMD:R_0402_1005Metric"
    assert footprint_for("Device:C", "10nF", rules) == "small"
    assert footprint_for("Device:C", "1uF", rules) == "big"


def test_rules_from_config_empty_falls_back_to_defaults():
    assert rules_from_config({}) == default_rules()


def test_invalid_threshold_cannot_silently_become_a_catch_all():
    with pytest.raises(SizingConfigError, match="not a valid capacitance"):
        rules_from_config(
            {
                "capacitor": [
                    {"max": "definitely-not-a-value", "footprint": "small"},
                    {"footprint": "large"},
                ]
            }
        )


def test_cli_strict_rules_require_both_footprint_id_parts():
    with pytest.raises(SizingConfigError, match="Library:Footprint"):
        rules_from_config({"resistor": ":"}, strict_footprints=True)
    with pytest.raises(SizingConfigError, match="Library:Footprint"):
        rules_from_config({"resistor": "Parts:../../escape"}, strict_footprints=True)


SHEET = (
    "(kicad_sch\n"
    '\t(symbol\n\t\t(lib_id "Device:C_Small")\n'
    '\t\t(property "Reference" "C1")\n\t\t(property "Value" "100nF")\n'
    '\t\t(property "Footprint" "")\n\t)\n'
    '\t(symbol\n\t\t(lib_id "Device:L")\n'
    '\t\t(property "Reference" "L1")\n\t\t(property "Value" "15uH")\n'
    '\t\t(property "Footprint" "")\n\t)\n)\n'
)


def test_reassign_footprints_fills_only_matched_and_reports():
    rules = default_rules()

    def decide(ref, lib_id, value, current):
        return None if current else footprint_for(lib_id, value, rules)

    new_text, applied = reassign_footprints(SHEET, decide)
    assert applied == [("C1", "Capacitor_SMD:C_0603_1608Metric")]  # L1 untouched
    assert '(property "Footprint" "Capacitor_SMD:C_0603_1608Metric")' in new_text
    assert '(lib_id "Device:L")' in new_text  # inductor block preserved


def test_reassign_footprints_leaves_assigned_alone():
    filled = SHEET.replace('(property "Footprint" "")', '(property "Footprint" "keep")', 1)

    def decide(ref, lib_id, value, current):
        return "SHOULD_NOT_APPLY" if not current else None

    _, applied = reassign_footprints(filled, decide)
    assert ("C1", "SHOULD_NOT_APPLY") not in applied
