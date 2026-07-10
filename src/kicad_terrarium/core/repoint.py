def repoint_text(text: str, old_library: str, new_library: str) -> tuple[str, int]:
    """
    Rewrite lib references from old_library to new_library in one schematic.

    The library name appears as "<library>:<symbol>" in BOTH the symbol instances
    (lib_id) AND the top-of-file lib_symbols cache, so both are rewritten together.

    Example: '(lib_id "old:C")' with old->new becomes '(lib_id "new:C")', count 1.
    """
    old = f'"{old_library}:'
    new = f'"{new_library}:'

    count = text.count(old)
    replaced_text = text.replace(old, new)

    return (replaced_text, count)
