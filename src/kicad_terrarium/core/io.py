"""Transactional, containment-checked filesystem changes.

Commands build one plan first. Applying it verifies that inputs have not
changed, stages every write beside its destination, creates unique backups,
and rolls back already-applied changes if a later operation fails.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class MutationError(RuntimeError):
    """A mutation was unsafe or could not be completed atomically."""


ChangeKind = Literal["write", "delete", "mkdir"]


def _digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def read_bytes_if_exists(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def read_utf8(path: Path) -> str:
    """Decode UTF-8 without universal-newline normalization."""
    return path.read_bytes().decode("utf-8")


@dataclass(frozen=True)
class PlannedChange:
    kind: ChangeKind
    path: Path
    content: bytes | None
    expected_digest: str | None
    description: str

    @property
    def changed(self) -> bool:
        if self.kind == "mkdir":
            return not self.path.is_dir()
        current = read_bytes_if_exists(self.path)
        return self.kind == "delete" or current != self.content


class OperationPlan:
    """A batch of file/directory changes constrained to explicit roots."""

    def __init__(
        self,
        *allowed_roots: Path,
        protected_projects: tuple[Path, ...] = (),
    ) -> None:
        if not allowed_roots:
            raise ValueError("an operation plan needs at least one allowed root")
        self.allowed_roots = tuple(path.resolve() for path in allowed_roots)
        self.protected_projects = tuple(path.resolve() for path in protected_projects)
        self.changes: list[PlannedChange] = []

    def _checked_path(self, path: Path) -> Path:
        absolute = path.resolve()
        if not any(absolute.is_relative_to(root) for root in self.allowed_roots):
            raise MutationError(f"refusing to write outside the operation boundary: {path}")
        if absolute in self.allowed_roots:
            raise MutationError(f"refusing to replace an operation root: {path}")
        if absolute.exists() and not absolute.is_file():
            raise MutationError(f"operation target is not a regular file: {path}")
        if any(change.path == absolute for change in self.changes):
            raise MutationError(f"operation plans the same path twice: {path}")
        return absolute

    def write(self, path: Path, content: str | bytes, description: str) -> None:
        target = self._checked_path(path)
        payload = content.encode("utf-8") if isinstance(content, str) else content
        before = read_bytes_if_exists(target)
        if before == payload:
            return
        self.changes.append(PlannedChange("write", target, payload, _digest(before), description))

    def delete(self, path: Path, description: str) -> None:
        target = self._checked_path(path)
        before = read_bytes_if_exists(target)
        if before is None:
            return
        self.changes.append(PlannedChange("delete", target, None, _digest(before), description))

    def mkdir(self, path: Path, description: str) -> None:
        absolute = path.resolve()
        if not any(absolute.is_relative_to(root) for root in self.allowed_roots):
            raise MutationError(f"refusing to create a directory outside the boundary: {path}")
        if absolute in self.allowed_roots:
            raise MutationError(f"refusing to replace an operation root: {path}")
        if absolute.exists():
            if absolute.is_dir():
                return
            raise MutationError(f"directory target is an existing file: {path}")
        if any(change.path == absolute for change in self.changes):
            raise MutationError(f"operation plans the same path twice: {path}")
        self.changes.append(PlannedChange("mkdir", absolute, None, None, description))

    def _assert_unlocked(self) -> None:
        candidates = {
            change.path.with_name(f"~{change.path.name}.lck")
            for change in self.changes
            if change.kind != "mkdir"
        }
        for root in self.protected_projects:
            candidates.update(
                {
                    root.with_name(f"~{root.name}.lck"),
                    root.with_name(f"~{root.stem}.kicad_pro.lck"),
                    root.with_name(f"~{root.stem}.kicad_sch.lck"),
                }
            )
        locked = next((path for path in candidates if path.exists()), None)
        if locked is not None:
            raise MutationError(f"KiCad appears to have this file open: {locked}")

    def _assert_unchanged(self) -> None:
        for change in self.changes:
            if not self._matches_expected(change):
                raise MutationError(
                    f"file changed while the operation was being planned: {change.path}"
                )

    def _assert_contained(self) -> None:
        for change in self.changes:
            resolved = change.path.resolve()
            if resolved != change.path or not any(
                resolved.is_relative_to(root) for root in self.allowed_roots
            ):
                raise MutationError(f"operation path escaped its boundary: {change.path}")

    @staticmethod
    def _matches_expected(change: PlannedChange) -> bool:
        if change.kind == "mkdir" or change.expected_digest is None:
            return not change.path.exists()
        return _digest(read_bytes_if_exists(change.path)) == change.expected_digest

    @staticmethod
    def _backup_path(path: Path) -> Path:
        candidate = path.with_name(path.name + ".bak")
        counter = 1
        while candidate.exists():
            candidate = path.with_name(f"{path.name}.bak.{counter}")
            counter += 1
        return candidate

    @staticmethod
    def _stage(path: Path, content: bytes, mode: int | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        staged = Path(name)
        try:
            target_mode = mode
            if target_mode is None:
                target_mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else 0o644
            with os.fdopen(descriptor, "wb") as handle:
                os.chmod(staged, target_mode)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            staged.unlink(missing_ok=True)
            raise
        return staged

    @staticmethod
    def _sync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def apply(self) -> list[Path]:
        """Apply the complete plan or restore every destination to its prior bytes."""
        if not self.changes:
            return []
        self._assert_contained()
        self._assert_unlocked()
        self._assert_unchanged()
        originals = {change.path: read_bytes_if_exists(change.path) for change in self.changes}
        original_modes = {
            change.path: stat.S_IMODE(change.path.stat().st_mode) if change.path.is_file() else None
            for change in self.changes
        }
        staged: dict[Path, Path] = {}
        committed: list[Path] = []
        try:
            for change in self.changes:
                if change.kind == "write":
                    if change.content is None:
                        raise MutationError(f"write has no staged content: {change.path}")
                    staged[change.path] = self._stage(change.path, change.content)
            self._assert_contained()
            self._assert_unlocked()
            for change in self.changes:
                if change.kind == "mkdir":
                    continue
                original = originals[change.path]
                if original is not None:
                    shutil.copy2(change.path, self._backup_path(change.path))
            for change in self.changes:
                # Close the plan/apply race immediately before each commit.
                if not self._matches_expected(change):
                    raise MutationError(f"file changed before commit: {change.path}")
                if change.kind == "write":
                    os.replace(staged.pop(change.path), change.path)
                elif change.kind == "delete":
                    change.path.unlink()
                else:
                    change.path.mkdir(parents=True)
                committed.append(change.path)
                self._sync_directory(change.path.parent)
        except Exception as error:
            rollback_errors: list[str] = []
            for path in reversed(committed):
                try:
                    change = next(item for item in self.changes if item.path == path)
                    if change.kind == "mkdir":
                        path.rmdir()
                        continue
                    original = originals[path]
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        restore = self._stage(path, original, original_modes[path])
                        os.replace(restore, path)
                except Exception as rollback_error:
                    rollback_errors.append(f"{path}: {rollback_error}")
            if rollback_errors:
                details = "; ".join(rollback_errors)
                raise MutationError(
                    f"operation failed and rollback was incomplete: {error}; {details}"
                ) from error
            if isinstance(error, MutationError):
                raise
            raise MutationError(f"operation failed and was rolled back: {error}") from error
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)
        return committed
