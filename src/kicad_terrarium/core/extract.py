"""Byte-exact symbol extraction from .kicad_sym files.

kiutils must never WRITE a symbol library: round-tripping a KiCad 10 file
silently drops every `(hide yes)` property flag and mangles `(show_name no)`,
making all symbol properties visible in the editor. Vendoring therefore
copies symbol blocks verbatim and only synthesizes the surrounding header.
"""

from kicad_terrarium.core.sexpr import atoms, child_forms, forms, quoted_tokens


class SymbolConflictError(ValueError):
    """Two sources define the same symbol name with different bytes."""


class InheritanceError(ValueError):
    """A symbol inheritance graph contains a cycle."""


def symbol_blocks(lib_text: str) -> dict[str, str]:
    """Top-level (symbol "NAME" ...) blocks, byte-for-byte, keyed by name.

    Found by structural depth, never by indentation: hand-edited libraries
    legally put `)` and the next `(symbol` on one line, so layout means
    nothing. A block is any `(symbol` whose paren sits at depth 1, i.e.
    directly inside `(kicad_symbol_lib`.
    """
    all_forms = forms(lib_text)
    roots = [form for form in all_forms if form.depth == 0]
    if len(roots) != 1 or roots[0].head != "kicad_symbol_lib":
        found = roots[0].head if len(roots) == 1 else f"{len(roots)} root forms"
        raise ValueError(f"expected one kicad_symbol_lib root, found {found}")
    blocks: dict[str, str] = {}
    for symbol in child_forms(all_forms, roots[0], "symbol"):
        names = quoted_tokens(lib_text, symbol)
        if not names:
            raise ValueError("top-level symbol has no quoted name")
        name = names[0].value
        block = lib_text[symbol.start : symbol.end]
        if name in blocks and blocks[name] != block:
            raise SymbolConflictError(f"conflicting definitions for symbol {name!r}")
        blocks[name] = block
    return blocks


def _parent_name(block: str) -> str | None:
    all_forms = forms(block)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "symbol"]
    if len(roots) != 1:
        raise ValueError("invalid symbol block")
    parents = child_forms(all_forms, roots[0], "extends")
    if len(parents) > 1:
        raise ValueError("symbol has more than one extends form")
    if not parents:
        return None
    names = quoted_tokens(block, parents[0])
    if len(names) != 1:
        raise ValueError("symbol extends form needs one quoted parent")
    return names[0].value


def extends_closure(wanted: set[str], blocks: dict[str, str]) -> tuple[list[str], set[str]]:
    """Names to vendor: `wanted` plus every transitive (extends ...) parent.

    Stock libraries inherit heavily (OPA2197xD extends NCS2325D, ...); a
    vendored library without the parents parses fine but cannot be drawn.

    Returns (names ordered parents-first, wanted names absent from blocks).
    """
    missing = {name for name in wanted if name not in blocks}
    ordered: list[str] = []
    seen: set[str] = set()
    for name in sorted(wanted - missing):
        chain = [name]
        current = name
        while True:
            parent = _parent_name(blocks[current])
            if parent is None:
                break
            if parent in chain:
                cycle = " -> ".join((*chain, parent))
                raise InheritanceError(f"symbol inheritance cycle: {cycle}")
            if parent not in blocks:
                missing.add(parent)
                break
            chain.append(parent)
            current = parent
        for n in reversed(chain):  # root ancestor first
            if n not in seen:
                seen.add(n)
                ordered.append(n)
    return ordered, missing


def library_version(lib_text: str) -> str:
    """The `(version N)` of a .kicad_sym, or the current default if absent."""
    all_forms = forms(lib_text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "kicad_symbol_lib"]
    if len(roots) != 1:
        raise ValueError("invalid kicad symbol library")
    versions = child_forms(all_forms, roots[0], "version")
    values = atoms(lib_text, versions[0]) if len(versions) == 1 else []
    if not values:
        return "20251024"
    if len(values) != 1 or not values[0].isdigit():
        raise ValueError("invalid symbol-library version")
    return values[0]


def _wrap_library(body: str, version: str, newline: str = "\n") -> str:
    return (
        f"(kicad_symbol_lib{newline}"
        f"\t(version {version}){newline}"
        f'\t(generator "kicad-terrarium"){newline}'
        f"{body}{newline}){newline}"
    )


def assemble_library(names: list[str], blocks: dict[str, str], source_text: str) -> str:
    """A .kicad_sym file holding `names`, format version copied from source."""
    newline = "\r\n" if "\r\n" in source_text else "\n"
    return _wrap_library(
        newline.join(blocks[name] for name in names),
        library_version(source_text),
        newline,
    )


def vendor_library(source_text: str, wanted: set[str]) -> tuple[str, list[str], set[str]]:
    """One library, vendored: (output file text, names kept, names missing)."""
    blocks = symbol_blocks(source_text)
    ordered, missing = extends_closure(wanted, blocks)
    return assemble_library(ordered, blocks, source_text), ordered, missing


def pluck_symbols(source_text: str, wanted: set[str]) -> tuple[dict[str, str], set[str]]:
    """Symbol blocks to copy for `wanted`, parents included: ({name: block}, missing)."""
    blocks = symbol_blocks(source_text)
    ordered, missing = extends_closure(wanted, blocks)
    return {n: blocks[n] for n in ordered}, missing


def merge_symbols(
    dest_text: str | None, additions: dict[str, str], version: str = "20251024"
) -> tuple[str, list[str]]:
    """Add symbol blocks to a library, skipping names already present.

    `dest_text` None creates a new library at `version`; otherwise existing
    symbols are left byte-for-byte untouched. Returns (library text, names
    actually added).
    """
    if dest_text is None:
        newline = "\r\n" if any("\r\n" in block for block in additions.values()) else "\n"
        return _wrap_library(newline.join(additions.values()), version, newline), list(additions)
    existing = symbol_blocks(dest_text)
    conflicts = [
        name for name, block in additions.items() if name in existing and existing[name] != block
    ]
    if conflicts:
        raise SymbolConflictError(
            "destination already has different definitions for: " + ", ".join(sorted(conflicts))
        )
    added = [name for name in additions if name not in existing]
    if not added:
        return dest_text, []
    all_forms = forms(dest_text)
    roots = [form for form in all_forms if form.depth == 0 and form.head == "kicad_symbol_lib"]
    if len(roots) != 1:
        raise ValueError("destination is not a valid symbol library")
    close = roots[0].end - 1
    newline = "\r\n" if "\r\n" in dest_text else "\n"
    body = newline.join(additions[name] for name in added)
    prefix = dest_text[:close]
    separator = "" if prefix.endswith(("\n", "\r")) else newline
    return prefix + separator + body + newline + dest_text[close:], added


def prune_library(lib_text: str, used: set[str]) -> tuple[str, list[str], list[str]]:
    """Rewrite a library keeping only `used` symbols and their extends parents.

    A parent kept only because a used symbol inherits from it stays even when
    it isn't referenced directly. Returns (new text, kept names parents-first,
    removed names).
    """
    blocks = symbol_blocks(lib_text)
    keep_ordered, missing = extends_closure(used, blocks)
    if missing:
        raise ValueError(
            "cannot prune a library with missing used definitions or parents: "
            + ", ".join(sorted(missing))
        )
    keep = set(keep_ordered)
    removed = [name for name in blocks if name not in keep]
    return assemble_library(keep_ordered, blocks, lib_text), keep_ordered, removed
