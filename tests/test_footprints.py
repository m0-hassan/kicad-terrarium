from kicad_terrarium.core.footprints import (
    board_footprint_ids,
    model_paths,
    repoint_schematic_footprints,
    rewrite_board_assets,
)


def test_repoint_schematic_footprints_touches_only_placed_properties():
    text = """(kicad_sch
      (lib_symbols (symbol "Parts:Widget" (property "Footprint" "Parts:Cached")))
      (symbol (lib_id "Local:A")
        (property "Description" "Parts:Widget")
        (property "Footprint" "Parts:Widget")))"""

    output, counts = repoint_schematic_footprints(text, {"Parts": "Terrarium__Parts"})

    assert counts == {"Parts": 1}
    assert '"Terrarium__Parts:Widget"' in output
    assert '"Parts:Cached"' in output
    assert '"Parts:Widget"' in output


def test_board_discovery_and_rewrite_are_scoped_to_footprint_forms():
    text = """(kicad_pcb
      (property "note" "Parts:Untouched")
      (footprint "Parts:Widget"
        (property "Value" "Parts:Untouched")
        (model "/models/widget.step")))"""

    assert board_footprint_ids(text) == ["Parts:Widget"]
    output, counts, models = rewrite_board_assets(
        text,
        {"Parts": "Terrarium__Parts"},
        lambda library, model: (
            "${KIPRJMOD}/library/widget.step"
            if library == "Parts" and model == "/models/widget.step"
            else model
        ),
    )

    assert counts == {"Parts": 1}
    assert models == 1
    assert '"Terrarium__Parts:Widget"' in output
    assert output.count('"Parts:Untouched"') == 2
    assert model_paths(output) == ["${KIPRJMOD}/library/widget.step"]
