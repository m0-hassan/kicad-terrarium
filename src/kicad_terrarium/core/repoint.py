def repoint_text(text: str, old_library: str, new_library: str) -> tuple[str, int]:
    """
    Rewrite lib references from old_library to new_library in one schematic.

    The library name appears as "<library><symbol>" in BOTH the symbol instances (lib_id)
    AND the top-of-file lib_symbols cache.

    Example: repoint_text('(lib_id "old:C") (symbol "old:C"', "old", "new") -> ('(lib_id "new:C") (symbol "new:C"', 2)
    """
    old = f'"{old_library}:'
    new = f'"{new_library}:'

    count = text.count(old)
    replaced_text = text.replace(old, new)

    return (replaced_text, count)
