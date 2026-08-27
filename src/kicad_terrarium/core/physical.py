"""Plan footprint-source and custom-model containment for project sealing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from kicad_terrarium.core.discover import placed_symbols
from kicad_terrarium.core.footprints import (
    board_footprint_ids,
    is_embedded_model_path,
    is_stock_model_path,
    repoint_schematic_footprints,
    rewrite_board_assets,
    rewrite_model_paths,
)
from kicad_terrarium.core.io import OperationPlan, read_utf8
from kicad_terrarium.core.managed import (
    TERRARIUM_LIBRARY_DIRECTORY,
    TERRARIUM_LIBRARY_PREFIX,
    is_terrarium_managed,
    managed_description,
    terrarium_library_nickname,
)
from kicad_terrarium.core.models import FootprintId
from kicad_terrarium.core.resolve import (
    configured_path_variables,
    direct_library_registration,
    expand_uri,
    resolve_global_library_details,
    resolve_library_details,
)
from kicad_terrarium.core.tables import (
    portable_project_uri,
    remove_from_fp_lib_table,
    upsert_fp_lib_uris,
    validate_library_nickname,
)

TERRARIUM_FOOTPRINT_DIRECTORY = TERRARIUM_LIBRARY_DIRECTORY / "footprints"
TERRARIUM_MODEL_DIRECTORY = TERRARIUM_LIBRARY_DIRECTORY / "models"
_VARIABLE = re.compile(r"\$\{[^}]+\}")
_SAFE_MODEL_STEM = re.compile(r"[^A-Za-z0-9._-]+")


class PhysicalSealError(ValueError):
    """A footprint/model seal cannot be safely and completely planned."""


@dataclass
class FootprintSealLibraryResult:
    nickname: str
    used: int
    kept: int
    changed: bool
    sources: tuple[str, ...] = ()


@dataclass
class PhysicalSealResult:
    sheets: dict[Path, str]
    libraries: list[FootprintSealLibraryResult] = field(default_factory=list)
    model_files: int = 0
    changed_model_files: int = 0
    board: Path | None = None


@dataclass
class _FootprintGroup:
    nickname: str
    destination: Path
    wanted: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    candidates: list[Path] = field(default_factory=list)
    hidden: bool = True
    description: str = ""


def _project_uri(project_dir: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(project_dir):
        raise PhysicalSealError(f"project asset is outside the project: {path}")
    return f"${{KIPRJMOD}}/{resolved.relative_to(project_dir).as_posix()}"


def _module(directory: Path, footprint: str) -> Path | None:
    if not directory.is_dir():
        return None
    candidate = directory / f"{footprint}.kicad_mod"
    resolved = candidate.resolve()
    if not resolved.is_relative_to(directory.resolve()):
        raise PhysicalSealError(f"footprint path escapes its source library: {candidate}")
    return candidate if candidate.is_file() else None


def _model_stem(path: Path) -> str:
    stem = _SAFE_MODEL_STEM.sub("_", path.stem).strip("._-")
    return stem or "model"


class _ModelVendor:
    def __init__(self, project_dir: Path, plan: OperationPlan) -> None:
        self.project_dir = project_dir
        self.plan = plan
        self.variables = configured_path_variables()
        self.pending: dict[Path, bytes] = {}
        self.portable_files: set[Path] = set()

    @staticmethod
    def _family(source: Path) -> list[Path]:
        family = [source]
        if source.suffix.casefold() == ".wrl":
            for suffix in (".step", ".stp"):
                companion = source.with_suffix(suffix)
                if companion.is_file():
                    family.append(companion)
        return family

    def _destination_family(
        self,
        source: Path,
        group: str,
    ) -> tuple[Path, list[tuple[Path, bytes]]]:
        family = self._family(source)
        payloads = [(path, path.read_bytes()) for path in family]
        digest = hashlib.sha256()
        for path, payload in payloads:
            digest.update(path.suffix.casefold().encode("ascii", errors="ignore"))
            digest.update(b"\0")
            digest.update(payload)
        destination_stem = f"{_model_stem(source)}-{digest.hexdigest()[:12]}"
        directory = self.project_dir / TERRARIUM_MODEL_DIRECTORY / group
        destination = directory / f"{destination_stem}{source.suffix.casefold()}"
        outputs = [
            (directory / f"{destination_stem}{path.suffix.casefold()}", payload)
            for path, payload in payloads
        ]
        return destination, outputs

    def portable_uri(self, original: str, *, base_dir: Path, group: str) -> str:
        if is_stock_model_path(original) or is_embedded_model_path(original):
            return original
        validate_library_nickname(group)
        source = expand_uri(
            original,
            self.project_dir,
            variables=self.variables,
            base_dir=base_dir,
        )
        if _VARIABLE.search(str(source)):
            raise PhysicalSealError(f"3D model has an unresolved path variable: {original}")
        resolved = source.resolve()
        if original.startswith("${KIPRJMOD}") and not resolved.is_relative_to(self.project_dir):
            raise PhysicalSealError(f"3D model escapes the project: {original}")
        if not resolved.is_file():
            raise PhysicalSealError(f"3D model does not exist: {original} ({resolved})")
        if resolved.is_relative_to(self.project_dir):
            self.portable_files.add(resolved)
            return _project_uri(self.project_dir, resolved)

        destination, outputs = self._destination_family(resolved, group)
        for target, payload in outputs:
            previous = self.pending.get(target)
            if previous is not None and previous != payload:
                raise PhysicalSealError(f"3D model destination collision: {target}")
            self.pending[target] = payload
        self.portable_files.add(destination.resolve())
        return _project_uri(self.project_dir, destination)

    def add_writes(self) -> int:
        before = len(self.plan.changes)
        for destination, payload in sorted(self.pending.items()):
            self.plan.write(destination, payload, "seal custom 3D model")
        return len(self.plan.changes) - before


def _used_footprint_ids(
    sheets: dict[Path, str],
    board_text: str | None,
) -> list[FootprintId]:
    values = [
        item.footprint
        for text in sheets.values()
        for item in placed_symbols(text)
        if item.footprint
    ]
    if board_text is not None:
        values.extend(board_footprint_ids(board_text))
    result: list[FootprintId] = []
    for value in values:
        try:
            footprint_id = FootprintId.parse(value)
            validate_library_nickname(footprint_id.library)
        except ValueError as error:
            raise PhysicalSealError(str(error)) from error
        result.append(footprint_id)
    return result


def extend_seal_plan(
    root: Path,
    plan: OperationPlan,
    sheets: dict[Path, str],
) -> PhysicalSealResult:
    """Add complete footprint/model containment to an existing seal plan."""
    project_dir = root.parent
    board = root.with_suffix(".kicad_pcb")
    board_text = read_utf8(board) if board.is_file() else None
    footprint_ids = _used_footprint_ids(sheets, board_text)
    used_libraries = sorted({item.library for item in footprint_ids})

    table = project_dir / "fp-lib-table"
    table_text = read_utf8(table) if table.is_file() else None
    visible = resolve_library_details(project_dir, table_name="fp-lib-table")
    global_visible = resolve_global_library_details(project_dir, table_name="fp-lib-table")
    vendor = _ModelVendor(project_dir, plan)
    results: list[FootprintSealLibraryResult] = []
    groups: dict[str, _FootprintGroup] = {}
    rewritten: dict[str, str] = {}
    remove_registrations: set[str] = set()
    registrations: dict[str, str] = {}
    hidden_names: set[str] = set()
    descriptions: dict[str, str] = {}
    source_bases: dict[str, Path] = {}

    def add_candidate(group: _FootprintGroup, path: Path | None) -> None:
        if path is not None and path.is_dir() and path not in group.candidates:
            group.candidates.append(path)

    for source_nickname in used_libraries:
        wanted = {item.name for item in footprint_ids if item.library == source_nickname}
        visible_source = visible.libraries.get(source_nickname)
        current_path = visible_source.path.resolve() if visible_source else None
        if current_path is not None and current_path.is_dir():
            source_bases[source_nickname] = current_path
        direct_registration = direct_library_registration(
            project_dir, source_nickname, table_name="fp-lib-table"
        )
        source_entry = (
            direct_registration[0]
            if direct_registration is not None
            else (visible_source.entry if visible_source is not None else None)
        )
        managed_local = (
            current_path is not None
            and current_path.is_relative_to(project_dir)
            and is_terrarium_managed(source_entry)
        )
        direct_external_source = (
            direct_registration is not None
            and direct_registration[0].library_type.casefold() == "kicad"
            and current_path is not None
            and not current_path.is_relative_to(project_dir)
        )
        already_namespaced = managed_local and source_nickname.startswith(TERRARIUM_LIBRARY_PREFIX)

        if (
            current_path is not None
            and current_path.is_relative_to(project_dir)
            and not managed_local
        ):
            if (
                direct_registration is not None
                and direct_registration[0].library_type.casefold() != "kicad"
            ):
                raise PhysicalSealError(
                    f"{source_nickname}: direct project nickname is already used by "
                    f"a {direct_registration[0].library_type!r} entry"
                )
            if not current_path.is_dir():
                raise PhysicalSealError(
                    f"{source_nickname}: project footprint library is not a directory"
                )
            changed = False
            for name in sorted(wanted):
                source_module = _module(current_path, name)
                if source_module is None:
                    raise PhysicalSealError(
                        f"{source_nickname}: project-local library is missing {name}.kicad_mod"
                    )
                original = read_utf8(source_module)

                def portable_local_model(
                    model: str,
                    base: Path = source_module.parent,
                    group: str = source_nickname,
                ) -> str:
                    return vendor.portable_uri(model, base_dir=base, group=group)

                output, replacements = rewrite_model_paths(
                    original,
                    portable_local_model,
                )
                if replacements:
                    plan.write(source_module, output, "make footprint 3D models portable")
                    changed = True
            needs_direct_registration = (
                direct_registration is None
                or direct_registration[0].library_type.casefold() != "kicad"
                or direct_registration[1] != current_path
                or not portable_project_uri(direct_registration[0].uri)
            )
            if needs_direct_registration:
                registrations[source_nickname] = _project_uri(project_dir, current_path)
                descriptions[source_nickname] = (
                    source_entry.description
                    if source_entry is not None and source_entry.description
                    else "Project-local footprint library; portable registration maintained "
                    "by kicad-terrarium"
                )
                if source_entry is not None and source_entry.hidden:
                    hidden_names.add(source_nickname)
            results.append(
                FootprintSealLibraryResult(
                    source_nickname,
                    len(wanted),
                    len(list(current_path.glob("*.kicad_mod"))),
                    changed or needs_direct_registration,
                    (source_nickname,),
                )
            )
            continue

        final_nickname = (
            source_nickname if already_namespaced else terrarium_library_nickname(source_nickname)
        )
        if final_nickname != source_nickname:
            rewritten[source_nickname] = final_nickname

        target_registration = direct_library_registration(
            project_dir, final_nickname, table_name="fp-lib-table"
        )
        target_entry = target_registration[0] if target_registration is not None else None
        target_path = target_registration[1] if target_registration is not None else None
        if target_registration is not None:
            target_entry, target_path = target_registration
            if (
                not is_terrarium_managed(target_entry)
                or target_entry.library_type.casefold() != "kicad"
                or target_path is None
                or not target_path.is_relative_to(project_dir)
                or target_path.suffix != ".pretty"
                or (target_path.exists() and not target_path.is_dir())
            ):
                raise PhysicalSealError(
                    f"{final_nickname}: reserved Terrarium nickname is already used by "
                    "a non-managed footprint library"
                )
            destination = target_path
        elif already_namespaced and current_path is not None:
            destination = current_path
            target_entry = source_entry
        else:
            destination = project_dir / TERRARIUM_FOOTPRINT_DIRECTORY / f"{source_nickname}.pretty"
            collision = visible.libraries.get(final_nickname)
            if collision is not None:
                raise PhysicalSealError(
                    f"{final_nickname}: reserved Terrarium nickname already exists"
                )
            if destination.exists():
                raise PhysicalSealError(
                    f"{final_nickname}: refusing to adopt unregistered destination {destination}"
                )

        group = groups.get(final_nickname)
        if group is None:
            source_stays_searchable = (
                (visible_source is not None and visible_source.entry.scope != "project")
                or source_nickname in global_visible.libraries
                or (
                    direct_registration is not None
                    and not managed_local
                    and not direct_external_source
                )
            )
            group = _FootprintGroup(
                final_nickname,
                destination,
                hidden=target_entry.hidden if target_entry is not None else source_stays_searchable,
                description=(
                    target_entry.description
                    if target_entry is not None and is_terrarium_managed(target_entry)
                    else ""
                ),
            )
            groups[final_nickname] = group
            add_candidate(group, target_path)
        elif group.destination != destination:
            raise PhysicalSealError(
                f"{final_nickname}: sources resolve to conflicting footprint destinations"
            )
        group.wanted.update(wanted)
        group.sources.add(source_nickname)
        add_candidate(group, current_path)

        if managed_local and not already_namespaced:
            remove_registrations.add(source_nickname)
        elif direct_external_source:
            remove_registrations.add(source_nickname)

    for group in groups.values():
        changed = False
        desired: set[Path] = set()
        for name in sorted(group.wanted):
            source_module = next(
                (
                    module
                    for candidate in group.candidates
                    if (module := _module(candidate, name)) is not None
                ),
                None,
            )
            if source_module is None:
                raise PhysicalSealError(
                    f"{', '.join(sorted(group.sources))}: cannot seal missing footprint {name}"
                )

            def portable_managed_model(
                model: str,
                base: Path = source_module.parent,
                nickname: str = group.nickname,
            ) -> str:
                return vendor.portable_uri(model, base_dir=base, group=nickname)

            output, _replacements = rewrite_model_paths(
                read_utf8(source_module), portable_managed_model
            )
            destination_module = group.destination / f"{name}.kicad_mod"
            desired.add(destination_module.resolve())
            before = destination_module.read_bytes() if destination_module.is_file() else None
            plan.write(destination_module, output, f"seal {group.nickname}:{name}")
            changed = changed or before != output.encode("utf-8")
        existing_registration = direct_library_registration(
            project_dir, group.nickname, table_name="fp-lib-table"
        )
        existing_entry = existing_registration[0] if existing_registration is not None else None
        if group.destination.is_dir() and is_terrarium_managed(existing_entry):
            for stale in sorted(group.destination.glob("*.kicad_mod")):
                if stale.resolve() not in desired:
                    plan.delete(stale, f"remove unused footprint from {group.nickname}")
                    changed = True
        registrations[group.nickname] = _project_uri(project_dir, group.destination)
        descriptions[group.nickname] = group.description or managed_description(
            "sealed-footprints", group.sources
        )
        if group.hidden:
            hidden_names.add(group.nickname)
        source_bases[group.nickname] = group.destination
        results.append(
            FootprintSealLibraryResult(
                group.nickname,
                len(group.wanted),
                len(group.wanted),
                changed or any(rewritten.get(source) == group.nickname for source in group.sources),
                tuple(sorted(group.sources)),
            )
        )

    updated_sheets: dict[Path, str] = {}
    for sheet, text in sheets.items():
        output, _counts = repoint_schematic_footprints(text, rewritten)
        updated_sheets[sheet] = output

    if board_text is not None:

        def board_model(library: str, model: str) -> str:
            base = source_bases.get(library, project_dir)
            group = rewritten.get(library, library or "Board")
            return vendor.portable_uri(model, base_dir=base, group=group)

        board_output, _counts, _models = rewrite_board_assets(
            board_text,
            rewritten,
            board_model,
        )
        plan.write(board, board_output, "point board at sealed footprints and models")

    if remove_registrations or registrations:
        updated_table = table_text
        if updated_table is not None and remove_registrations:
            updated_table = remove_from_fp_lib_table(updated_table, sorted(remove_registrations))
        updated_table = upsert_fp_lib_uris(
            updated_table,
            registrations,
            hidden_names=hidden_names,
            descriptions=descriptions,
        )
        plan.write(table, updated_table, "activate namespaced Terrarium footprints")

    changed_model_files = vendor.add_writes()
    return PhysicalSealResult(
        updated_sheets,
        sorted(results, key=lambda item: item.nickname),
        len(vendor.portable_files),
        changed_model_files,
        board if board_text is not None else None,
    )
