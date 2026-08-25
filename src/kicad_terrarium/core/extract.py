"""Byte-exact symbol extraction from .kicad_sym files.

kiutils must never WRITE a symbol library: round-tripping a KiCad 10 file
silently drops every `(hide yes)` property flag and mangles `(show_name no)`,
making all symbol properties visible in the editor. Vendoring therefore
copies symbol blocks verbatim and only synthesizes the surrounding header.
"""

import re

_SYMBOL_HEAD = re.compile(r'\(symbol\s+"([^"]+)"')
_EXTENDS = re.compile(r'\(extends "([^"]+)"\)')
_VERSION = re.compile(r"\(version (\d+)\)")


def block_end(text: str, start: int) -> int:
    """Index just past the ')' matching the '(' at text[start].

    Quoted strings are skipped, so parentheses inside descriptions like
    "amplifier (dual)" cannot desynchronize the depth count.
    """
    depth = 0
    in_string = False
    i = start
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 1  # skip the escaped character
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced s-expression")


def symbol_blocks(lib_text: str) -> dict[str, str]:
    """Top-level (symbol "NAME" ...) blocks, byte-for-byte, keyed by name.

    Found by depth tracking, never by indentation: hand-edited libraries
    legally put `)` and the next `(symbol` on one line, so layout means
    nothing. A block is any `(symbol` whose paren sits at depth 1, i.e.
    directly inside `(kicad_symbol_lib`.
    """
    blocks: dict[str, str] = {}
    depth = 0
    in_string = False
    i = 0
    while i < len(lib_text):
        c = lib_text[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "(":
            if depth == 1:
                m = _SYMBOL_HEAD.match(lib_text, i)
                if m:
                    end = block_end(lib_text, i)
                    blocks[m.group(1)] = lib_text[i:end]
                    i = end  # the block is balanced, so depth is unchanged
                    continue
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return blocks


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
            m = _EXTENDS.search(blocks[current])
            if not m:
                break
            parent = m.group(1)
            if parent in chain:  # inheritance cycle: stop, keep what we have
                break
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
    m = _VERSION.search(lib_text)
    return m.group(1) if m else "20251024"


def _wrap_library(body: str, version: str) -> str:
    return f'(kicad_symbol_lib\n\t(version {version})\n\t(generator "kicad-terrarium")\n{body}\n)\n'


def assemble_library(names: list[str], blocks: dict[str, str], source_text: str) -> str:
    """A .kicad_sym file holding `names`, format version copied from source."""
    return _wrap_library("\n".join(blocks[n] for n in names), library_version(source_text))


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
        return _wrap_library("\n".join(additions.values()), version), list(additions)
    existing = set(symbol_blocks(dest_text))
    added = [n for n in additions if n not in existing]
    if not added:
        return dest_text, []
    trimmed = dest_text.rstrip()
    close = trimmed.rfind(")")  # the library's closing paren
    return trimmed[:close] + "\n".join(additions[n] for n in added) + "\n)\n", added


def prune_library(lib_text: str, used: set[str]) -> tuple[str, list[str], list[str]]:
    """Rewrite a library keeping only `used` symbols and their extends parents.

    A parent kept only because a used symbol inherits from it stays even when
    it isn't referenced directly. Returns (new text, kept names parents-first,
    removed names).
    """
    blocks = symbol_blocks(lib_text)
    keep_ordered, _missing = extends_closure(used & set(blocks), blocks)
    keep = set(keep_ordered)
    removed = [name for name in blocks if name not in keep]
    return assemble_library(keep_ordered, blocks, lib_text), keep_ordered, removed
