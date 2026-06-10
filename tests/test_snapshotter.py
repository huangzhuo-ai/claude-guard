"""Snapshotter 测试：导出/导入迁移，全部在临时目录，不依赖真 Claude。"""
import json
import zipfile
from pathlib import Path

import pytest

from claude_guard.session_registry import SessionRegistry
from claude_guard.snapshotter import (
    export_snapshot,
    import_snapshot,
    work_dir_to_project_name,
)


def test_work_dir_to_project_name():
    """工作目录路径 -> Claude 项目目录名：分隔符和冒号换成 -。"""
    assert work_dir_to_project_name(r"D:\Code\app") == "D--Code-app"
    assert work_dir_to_project_name("C:/Users/huang") == "C--Users-huang"


def _setup_machine(tmp_path, sessions):
    """造一台机器：registry + 假 .jsonl 文件。返回 (registry, projects_dir)。"""
    reg = SessionRegistry(tmp_path / "reg.db")
    projects = tmp_path / "projects"
    for s in sessions:
        reg.add(s["session_id"], s["work_dir"], s["goal"], "skip")
        pname = work_dir_to_project_name(s["work_dir"])
        d = projects / pname
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{s['session_id']}.jsonl").write_text(
            f"context-of-{s['session_id']}", encoding="utf-8"
        )
    return reg, projects


def test_export_creates_zip_with_manifest_and_jsonl(tmp_path):
    reg, projects = _setup_machine(tmp_path, [
        {"session_id": "s1", "work_dir": r"D:\proj\a", "goal": "任务A"},
    ])
    out = tmp_path / "snap.zip"
    export_snapshot(reg, ["s1"], out, claude_projects_dir=projects)

    assert out.exists()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "manifest.json" in names
        assert "sessions.json" in names
        assert "jsonl/D--proj-a/s1.jsonl" in names
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["sessions"][0]["session_id"] == "s1"
        assert z.read("jsonl/D--proj-a/s1.jsonl").decode() == "context-of-s1"


def test_export_missing_jsonl_raises(tmp_path):
    """会话的 .jsonl 缺失时导出应明确报错，不静默。"""
    reg = SessionRegistry(tmp_path / "reg.db")
    reg.add("ghost", r"D:\proj\x", "g", "skip")
    out = tmp_path / "snap.zip"
    with pytest.raises(FileNotFoundError):
        export_snapshot(reg, ["ghost"], out,
                        claude_projects_dir=tmp_path / "empty")


def test_import_restores_jsonl_and_registry(tmp_path):
    # A 机导出
    reg_a, proj_a = _setup_machine(tmp_path / "A", [
        {"session_id": "s1", "work_dir": str(tmp_path / "A" / "code"),
         "goal": "任务A"},
    ])
    snap = tmp_path / "snap.zip"
    export_snapshot(reg_a, ["s1"], snap, claude_projects_dir=proj_a)

    # B 机导入（原工作目录恰好也存在）
    work_b = tmp_path / "A" / "code"  # 同路径，直接命中
    reg_b = SessionRegistry(tmp_path / "B" / "reg.db")
    proj_b = tmp_path / "B" / "projects"
    result = import_snapshot(snap, reg_b, claude_projects_dir=proj_b)

    assert result["imported"] == ["s1"]
    row = reg_b.get("s1")
    assert row is not None
    assert row["status"] == "paused"  # 导入后为暂停
    pname = work_dir_to_project_name(str(work_b))
    restored = proj_b / pname / "s1.jsonl"
    assert restored.exists()
    assert restored.read_text(encoding="utf-8") == "context-of-s1"


def test_import_path_difference_calls_resolver(tmp_path):
    """原路径在 B 机不存在 -> 调用 resolve_path 让用户重新指定目录。"""
    reg_a, proj_a = _setup_machine(tmp_path / "A", [
        {"session_id": "s1", "work_dir": r"D:\nonexistent\on\B", "goal": "g"},
    ])
    snap = tmp_path / "snap.zip"
    export_snapshot(reg_a, ["s1"], snap, claude_projects_dir=proj_a)

    new_dir = tmp_path / "B" / "relocated"
    new_dir.mkdir(parents=True)
    calls = []

    def resolver(session_id, old_path):
        calls.append((session_id, old_path))
        return str(new_dir)

    reg_b = SessionRegistry(tmp_path / "B" / "reg.db")
    proj_b = tmp_path / "B" / "projects"
    import_snapshot(snap, reg_b, claude_projects_dir=proj_b,
                    resolve_path=resolver)

    assert calls == [("s1", r"D:\nonexistent\on\B")]
    # 工作目录已改成新路径
    assert reg_b.get("s1")["work_dir"] == str(new_dir)
    # .jsonl 落在新路径对应的项目目录
    pname = work_dir_to_project_name(str(new_dir))
    assert (proj_b / pname / "s1.jsonl").exists()


def test_import_skips_when_resolver_returns_none(tmp_path):
    """resolver 返回 None -> 跳过该会话，不导入。"""
    reg_a, proj_a = _setup_machine(tmp_path / "A", [
        {"session_id": "s1", "work_dir": r"D:\gone", "goal": "g"},
    ])
    snap = tmp_path / "snap.zip"
    export_snapshot(reg_a, ["s1"], snap, claude_projects_dir=proj_a)

    reg_b = SessionRegistry(tmp_path / "B" / "reg.db")
    proj_b = tmp_path / "B" / "projects"
    result = import_snapshot(snap, reg_b, claude_projects_dir=proj_b,
                             resolve_path=lambda sid, old: None)

    assert result["skipped"] == ["s1"]
    assert reg_b.get("s1") is None
