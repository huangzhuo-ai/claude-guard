"""GUI 整屏快照显示链路测试（无头 offscreen）。

验证：会话跑起来后，MainWindow 的轮询能把 supervisor.render_session()
的整屏快照刷进 output_view。用改造后的 fake_claude（带状态栏画面）。
"""
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAKE = str(Path(__file__).parent / "fake_claude.py")


@pytest.fixture
def win(tmp_path, monkeypatch):
    from claude_guard.session_registry import SessionRegistry  # noqa: F401
    import gui.app as appmod
    monkeypatch.setattr(appmod, "_DB", tmp_path / "reg.db")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    w = appmod.MainWindow()
    yield w
    w.close()


def _pump(ms=3000):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def test_snapshot_reaches_output_view(win):
    from PySide6.QtCore import Qt, QThread
    from gui.workers import SessionWorker

    sid = "gui-" + uuid.uuid4().hex[:8]
    win.registry.add(sid, ".", "verify", "skip", max_rounds=1)
    win._refresh_list()
    for i in range(win.session_list.count()):
        it = win.session_list.item(i)
        if it.data(Qt.UserRole) == sid:
            win.session_list.setCurrentItem(it)
            break

    worker = SessionWorker(win.supervisor, sid,
                           launch_cmd=[sys.executable, FAKE],
                           instruction="go")
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    win._threads[sid] = thread
    thread.start()

    _pump(4000)
    text = win.output_view.toPlainText()
    thread.quit(); thread.wait(2000)

    assert "? for shortcuts" in text or "Claude ready" in text, repr(text)
