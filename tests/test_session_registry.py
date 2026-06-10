"""SessionRegistry 测试：SQLite 会话账本。"""
import threading

import pytest

from claude_guard.session_registry import SessionRegistry


@pytest.fixture
def reg(tmp_path):
    return SessionRegistry(tmp_path / "registry.db")


def test_add_and_get(reg):
    reg.add(
        session_id="abc-123",
        work_dir="D:/proj",
        goal="实现登录功能",
        permission_mode="skip",
        max_rounds=20,
    )
    row = reg.get("abc-123")
    assert row["session_id"] == "abc-123"
    assert row["work_dir"] == "D:/proj"
    assert row["goal"] == "实现登录功能"
    assert row["permission_mode"] == "skip"
    assert row["status"] == "running"
    assert row["rounds"] == 0
    assert row["max_rounds"] == 20


def test_get_missing_returns_none(reg):
    assert reg.get("nope") is None


def test_update_status_flow(reg):
    reg.add(session_id="s1", work_dir="d", goal="g", permission_mode="skip")
    for status in ("paused", "running", "done"):
        reg.update_status("s1", status)
        assert reg.get("s1")["status"] == status


def test_increment_rounds(reg):
    reg.add(session_id="s1", work_dir="d", goal="g", permission_mode="skip")
    assert reg.increment_rounds("s1") == 1
    assert reg.increment_rounds("s1") == 2
    assert reg.get("s1")["rounds"] == 2


def test_list_resumable(reg):
    reg.add(session_id="r1", work_dir="d", goal="g", permission_mode="skip")
    reg.add(session_id="r2", work_dir="d", goal="g", permission_mode="skip")
    reg.add(session_id="d1", work_dir="d", goal="g", permission_mode="skip")
    reg.update_status("r2", "paused")
    reg.update_status("d1", "done")
    ids = {r["session_id"] for r in reg.list_resumable()}
    assert ids == {"r1", "r2"}  # running + paused 可恢复，done 不可


def test_concurrent_increment_not_corrupted(reg):
    reg.add(session_id="s1", work_dir="d", goal="g", permission_mode="skip")

    def worker():
        for _ in range(50):
            reg.increment_rounds("s1")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert reg.get("s1")["rounds"] == 100


def test_corrupted_db_falls_back_to_backup(tmp_path):
    db = tmp_path / "registry.db"
    reg = SessionRegistry(db)
    reg.add(session_id="s1", work_dir="d", goal="g", permission_mode="skip")
    reg.backup()  # 显式生成一份好备份
    reg.close()

    # 损坏主库
    db.write_bytes(b"this is not a valid sqlite file")

    # 重新打开应自动回退备份并能读到 s1
    reg2 = SessionRegistry(db)
    assert reg2.get("s1") is not None
