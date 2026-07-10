from kiutils.symbol import SymbolLib


def select_symbols(source: SymbolLib, wanted: set[str]):
    """
    Keep only the source library's symbols whose name is in 'wanted'.

    Returns (kept_symbols, missing_names); 'missing' = wanted names absent from source.
    """
    kept = [s for s in source.symbols if s.libId in wanted]
    found = {s.libId for s in kept}
    missing = wanted - found  # set difference

    return kept, missing
