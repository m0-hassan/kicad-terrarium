from types import SimpleNamespace

from kicad_terrarium.core.vendor import select_symbols


def test_select_symbols_partitions_kept_and_missing():
    lib = SimpleNamespace(symbols=[SimpleNamespace(libId="R"), SimpleNamespace(libId="C")])
    kept, missing = select_symbols(lib, {"R", "X"})
    assert [s.libId for s in kept] == ["R"]
    assert missing == {"X"}
