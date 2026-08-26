from kicad_terrarium.core.repoint import repoint_libraries


def test_repoint_rewrites_instance_and_cache_together():
    text = '(kicad_sch (lib_id "old:C") (symbol "old: C"))'
    result, counts = repoint_libraries(text, {"old": "new"})

    assert result == '(kicad_sch (lib_id "new:C") (symbol "new: C"))'
    assert counts == {"old": 2}


def test_repoint_leaves_other_libraries_untouched():
    text = '(kicad_sch (lib_id "old:C") (lib_id "keep: C"))'
    result, counts = repoint_libraries(text, {"old": "new"})

    assert "keep" in result and "old" not in result
    assert counts == {"old": 1}


def test_repoint_libraries_rewrites_multiple_sources_in_one_parse():
    text = '(kicad_sch (lib_id "Device:R") (lib_id "Connector:Conn_01x02"))'
    output, counts = repoint_libraries(
        text,
        {
            "Device": "Terrarium__Device",
            "Connector": "Terrarium__Connector",
        },
    )
    assert 'lib_id "Terrarium__Device:R"' in output
    assert 'lib_id "Terrarium__Connector:Conn_01x02"' in output
    assert counts == {"Device": 1, "Connector": 1}
