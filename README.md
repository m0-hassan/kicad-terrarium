# kicad-terrarium

A small CLI I built to make KiCad projects self-contained: copy the symbols a
project actually uses into a local library and repoint every reference at it, so
the project opens cleanly on another machine without the original system or
vendor libraries.

KiCad 10's plugin API is PCB-only, so this works by parsing the schematic files
directly.

## Commands

- `scan` — list the libraries a project uses (follows all sub-sheets)
- `vendor` — write a local library with only the symbols the project uses
- `repoint` — rewrite references to point at the local library
- `verify` — check nothing external is left (exits non-zero if it is)

## Install

```bash
pipx install .
```

## Develop

```bash
pip install -e ".[dev]"
pytest
```

Symbols only for now; footprints are next.
