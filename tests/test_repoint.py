from kicad_terrarium.core.repoint import repoint_text

def test_repoint_rewrites_instance_and_cache_together():
    text = 'lib_id "old:C" (symbol "old: C"'
    result, count = repoint_text(text, "old", "new")

    assert result == 'lib_id "new:C" (symbol "new: C"'
    assert count == 2

def test_repoint_leaves_other_libraries_untouched():
    text = 'lib_id "old:C" (lib_id "keep: C"'
    result, count = repoint_text(text, "old", "new")

    assert "keep" in result and "old" not in result
    assert count == 1
