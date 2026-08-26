import stat
from pathlib import Path

import pytest

from kicad_terrarium.core.io import MutationError, OperationPlan


def test_operation_plan_writes_atomically_and_keeps_unique_backups(tmp_path):
    target = tmp_path / "project" / "file.txt"
    target.parent.mkdir()
    target.write_text("before")
    target.chmod(0o640)
    plan = OperationPlan(tmp_path / "project")
    plan.write(target, "after", "update")
    assert plan.apply() == [target.resolve()]
    assert target.read_text() == "after"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert target.with_name("file.txt.bak").read_text() == "before"

    second = OperationPlan(tmp_path / "project")
    second.write(target, "again", "update again")
    second.apply()
    assert target.with_name("file.txt.bak.1").read_text() == "after"


def test_operation_plan_detects_a_stale_file(tmp_path):
    target = tmp_path / "project" / "file.txt"
    target.parent.mkdir()
    target.write_text("planned")
    plan = OperationPlan(target.parent)
    plan.write(target, "new", "update")
    target.write_text("changed elsewhere")
    with pytest.raises(MutationError, match="changed while"):
        plan.apply()
    assert target.read_text() == "changed elsewhere"


def test_operation_plan_rejects_path_escape(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    plan = OperationPlan(root)
    with pytest.raises(MutationError, match="outside"):
        plan.write(tmp_path / "outside.txt", "x", "escape")


def test_operation_plan_detects_an_ancestor_replaced_by_a_symlink(tmp_path):
    root = tmp_path / "project"
    library = root / "library"
    library.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = library / "part.kicad_sym"
    plan = OperationPlan(root)
    plan.write(target, "x", "write part")
    library.rename(root / "original-library")
    library.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MutationError, match="escaped"):
        plan.apply()
    assert not (outside / target.name).exists()


def test_operation_plan_rejects_a_directory_destination(tmp_path):
    root = tmp_path / "project"
    target = root / "library.kicad_sym"
    target.mkdir(parents=True)
    plan = OperationPlan(root)
    with pytest.raises(MutationError, match="not a regular file"):
        plan.write(target, "x", "replace directory")


def test_operation_plan_creates_an_explicit_directory(tmp_path):
    directory = tmp_path / "nested/vault"
    plan = OperationPlan(tmp_path)
    plan.mkdir(directory, "create vault")
    assert plan.apply() == [directory.resolve()]
    assert directory.is_dir()


def test_operation_plan_respects_kicad_lock(tmp_path):
    root = tmp_path / "project.kicad_sch"
    root.write_text("x")
    lock = tmp_path / "~project.kicad_sch.lck"
    lock.write_text("locked")
    plan = OperationPlan(tmp_path, protected_projects=(root,))
    plan.write(tmp_path / "library.kicad_sym", "x", "write")
    with pytest.raises(MutationError, match="open"):
        plan.apply()


def test_operation_plan_respects_a_symbol_library_lock(tmp_path):
    target = tmp_path / "vault.kicad_sym"
    target.write_text("old")
    (tmp_path / "~vault.kicad_sym.lck").write_text("locked")
    plan = OperationPlan(tmp_path)
    plan.write(target, "new", "update vault")
    with pytest.raises(MutationError, match="open"):
        plan.apply()


def test_operation_plan_rolls_back_a_partial_commit(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    first, second = root / "a", root / "b"
    first.write_text("a0")
    second.write_text("b0")
    plan = OperationPlan(root)
    plan.write(first, "a1", "first")
    plan.write(second, "b1", "second")

    def fail_sync(_path: Path) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(OperationPlan, "_sync_directory", staticmethod(fail_sync))
    with pytest.raises(MutationError, match="rolled back"):
        plan.apply()
    assert first.read_text() == "a0"
    assert second.read_text() == "b0"


def test_operation_plan_rolls_back_a_created_directory(tmp_path, monkeypatch):
    directory = tmp_path / "vault"
    target = tmp_path / "config.json"
    target.write_text("before")
    plan = OperationPlan(tmp_path)
    plan.mkdir(directory, "create vault")
    plan.write(target, "after", "write config")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("kicad_terrarium.core.io.os.replace", fail_replace)
    with pytest.raises(MutationError, match="rolled back"):
        plan.apply()
    assert not directory.exists()
    assert target.read_text() == "before"
