# Shadow vs. Consolidate: how `seal` makes a project self-contained

This is the central design decision in kicad-terrarium, so it's worth writing
down in full — including what the two strategies even are, for anyone new to
the terms.

## The problem

A KiCad schematic doesn't store its symbols. It stores *references* — a placed
resistor is just a pointer that says `Device:R`, meaning "look up the symbol
`R` in the library named `Device`." The actual drawing lives in a separate
library file (`Device.kicad_sym`) on your machine, registered in a lookup
table (`sym-lib-table`).

That's why a project breaks when you send it to someone else: their machine
has a different set of libraries, so `Device:R` might resolve to nothing. To
make a project **self-contained**, you have to bring the symbols it uses
*inside* the project. There are two ways to do that.

## The two strategies

Both strategies copy **only the symbols the project actually uses** — this is
the first thing people get wrong. Neither one copies a whole library. On a real
board, the project's local `Device.kicad_sym` holds **10 symbols, not the 537**
in KiCad's stock Device library. So "bloat from copying huge libraries" is not
a real difference between them — both are minimal.

The difference is purely *organizational*: how those copied symbols are filed,
and whether the schematic's references are touched.

### Shadow (what `seal` does)

Copy each used library's symbols into a **separate local file that keeps the
original library's name**, and register it locally. Because a project-table
entry outranks a global one, `Device:R` now quietly resolves to your *local*
`library/Device.kicad_sym`. The local copy "shadows" the global one — same
name, higher priority.

- **Multiple local files**, one per source library.
- **Original names** kept (`Device`, `power`, `Connector`, …).
- **References untouched** — no schematic sheet is edited at all.

On a real project:

```
library/Device.kicad_sym          (10 symbols)
library/power.kicad_sym           (7 symbols)
library/Connector.kicad_sym       (3 symbols)
library/74xGxx.kicad_sym          (5 symbols)
...  14 files, ~50 symbols total, every reference unchanged
```

### Consolidate (the AL-MAWJA style)

Merge every used symbol into **one local library named after the project**,
and **rewrite every reference** to point at it: `Device:R` → `PID:R`,
`power:GND` → `PID:GND`, and so on.

- **One local file** (`PID.kicad_sym`).
- **Project name** for everything.
- **Every reference rewritten** across every sheet.

```
library/PID.kicad_sym             (~50 symbols)
...  1 file, but every sheet's references have been edited
```

Both end up self-contained. Both hold the same ~50 symbols. The question is
which *shape* is better.

## The tradeoff

| | Shadow (default) | Consolidate |
|---|---|---|
| Symbols copied | only used (minimal) | only used (minimal) |
| Local files | many, original names | one, project name |
| Schematic references | **untouched** | **all rewritten** |
| First-run git diff | tiny (added files only) | huge (every sheet edited) |
| Re-running later | always a tiny diff | idempotent *after* the first pass |
| Name collisions | impossible | possible (two libs with a same-named symbol) |
| Provenance | preserved (you see origins) | flattened (all `PID:…`) |
| Upstream updates | can re-pull a fixed stock symbol | severed |
| Tidiness | 14 files shadowing stock names | one clean project library |

## Why shadow is the default

Being honest: this is a real tradeoff, not a landslide. Consolidate's appeal —
one clean, uniquely-named library — is genuine, and it's idempotent after the
first pass, so a couple of the usual objections are weaker than they sound.
Shadow wins the **default** on four points that matter for terrarium's actual
mission (portable, version-controlled, collaborated-on projects):

1. **Non-destructive.** Shadow never edits your schematic files — it only adds
   libraries and a registry entry. Consolidate rewrites every reference in
   every sheet. If a tool is going to touch your *design* files, the bar is
   much higher, and the failure mode is much worse (a bad library you can
   regenerate vs. a corrupted schematic).

2. **Clean git diffs, every time.** The killer use case is "seal before you
   push, so collaborators get exactly what you had." Shadow's diff is always
   just "added some library files." Consolidate's first pass rewrites hundreds
   of references — an enormous, noisy commit, and a near-guaranteed merge
   conflict for any teammate editing the same sheets.

3. **No collisions.** If two libraries each define a symbol named `R`, shadow
   keeps them distinct (`Device:R`, `OtherLib:R`). Consolidate would try to
   make both `PID:R` and has to detect and disambiguate — a correctness burden
   for a gain that's purely cosmetic.

4. **Provenance, and the library name as metadata.** A library name is not
   just a label — it's KiCad's categorization system. `Device`, `power`,
   `Connector`, `Amplifier_Operational`, `MCU_ST_STM32G4` *are* the taxonomy,
   and knowing a symbol comes from the RF library vs. the connector library vs.
   the device library is real, professionally useful information. Shadow keeps
   it, so a sealed project reads like any other KiCad project. Consolidate
   flattens every symbol into `PID:…`, discarding that categorization — and
   severs the upstream link, so `Device:R` can no longer re-pull a fixed stock
   symbol the way it could when it still knew it was Device's R.

## When consolidate genuinely makes sense

For a **frozen archival snapshot** or a hand-off where you want one tidy,
uniquely-named library and will never merge upstream again, consolidate is
reasonable — which is exactly why AL-MAWJA was built that way by hand. If
kicad-terrarium ever offers it, it should be an explicit, clearly-labeled
export mode (with collision handling and a loud "this rewrites your sheets"
warning), **never the default**. The `graft` command is the reference-rewriting
engine such a mode would use.

## The related worry: does `pluck` cause bloat?

Separate concern, worth stating plainly. `pluck` copies a symbol from your
curated library into a project-local library. It only ever adds the symbol you
name, so it won't dump a whole library in — but a symbol you pluck and then
*don't place* will linger, and `seal` doesn't remove it (it only adds used
symbols; it doesn't prune existing local ones).

The fix is not consolidate — it's a **prune** step: trim every project-local
library down to exactly the symbols the schematic references. That keeps a
project minimal no matter how much you plucked while exploring, and it's a
natural read-the-refs-and-filter operation that fits terrarium's shape. It's on
the roadmap.
