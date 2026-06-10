"""claude-guard 主窗口。

布局：
  左侧 — 会话列表（QListWidget）
  右侧 — 实时输出（QPlainTextEdit，只读）
  底部工具栏 — 新建 / 恢复 / 停止 / 导出 / 导入 / 自启开关
"""
import sys
import winreg
from pathlib import Path

from typing import Optional

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QComboBox, QSplitter, QStatusBar,
    QToolBar, QVBoxLayout, QWidget,
)

from claude_guard.session_registry import SessionRegistry
from claude_guard.supervisor import Supervisor
from claude_guard import snapshotter
from gui.workers import SessionWorker

_AUTORUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTORUN_NAME = "claude-guard"
_DB = Path.home() / ".claude-guard" / "registry.db"

STATUS_COLOR = {
    "running": "#2ecc71",
    "paused":  "#f39c12",
    "stuck":   "#e74c3c",
    "crashed": "#c0392b",
    "done":    "#95a5a6",
}


class NewSessionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建会话")
        self.resize(480, 220)
        form = QFormLayout(self)

        self.session_id = QLineEdit()
        self.session_id.setPlaceholderText("例：my-project-v1")
        self.work_dir = QLineEdit()
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.work_dir)
        dir_row.addWidget(btn_browse)

        self.goal = QLineEdit()
        self.goal.setPlaceholderText("目标任务描述（自动续接时会用到）")
        self.permission = QComboBox()
        self.permission.addItems(["skip", "allowlist", "notify"])
        self.max_rounds = QSpinBox()
        self.max_rounds.setRange(1, 9999)
        self.max_rounds.setValue(20)

        form.addRow("会话 ID *", self.session_id)
        form.addRow("工作目录 *", dir_row)
        form.addRow("目标任务 *", self.goal)
        form.addRow("权限模式", self.permission)
        form.addRow("最大轮次", self.max_rounds)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择工作目录")
        if d:
            self.work_dir.setText(d)

    def _accept(self):
        if not self.session_id.text().strip():
            QMessageBox.warning(self, "必填", "请填写会话 ID")
            return
        if not self.work_dir.text().strip():
            QMessageBox.warning(self, "必填", "请选择工作目录")
            return
        if not self.goal.text().strip():
            QMessageBox.warning(self, "必填", "请填写目标任务")
            return
        self.accept()

    def values(self):
        return {
            "session_id": self.session_id.text().strip(),
            "work_dir":   self.work_dir.text().strip(),
            "goal":       self.goal.text().strip(),
            "permission": self.permission.currentText(),
            "max_rounds": self.max_rounds.value(),
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("claude-guard")
        self.resize(1000, 640)

        _DB.parent.mkdir(parents=True, exist_ok=True)
        self.registry = SessionRegistry(_DB)
        self.supervisor = Supervisor(self.registry, idle_seconds=60.0)
        self._threads: dict[str, QThread] = {}

        self._build_ui()
        self._refresh_list()

    # ── UI 构建 ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # 工具栏
        tb = QToolBar("操作")
        tb.setMovable(False)
        self.addToolBar(tb)

        btn_new    = QPushButton("＋ 新建")
        btn_resume = QPushButton("▶ 恢复")
        btn_stop   = QPushButton("■ 停止")
        btn_export = QPushButton("⬆ 导出")
        btn_import = QPushButton("⬇ 导入")
        self._autorun_cb = QCheckBox("开机自启")
        self._autorun_cb.setChecked(self._autorun_enabled())
        self._autorun_cb.stateChanged.connect(self._toggle_autorun)

        for w in (btn_new, btn_resume, btn_stop, btn_export, btn_import,
                  QLabel("  "), self._autorun_cb):
            tb.addWidget(w)

        btn_new.clicked.connect(self._on_new)
        btn_resume.clicked.connect(self._on_resume)
        btn_stop.clicked.connect(self._on_stop)
        btn_export.clicked.connect(self._on_export)
        btn_import.clicked.connect(self._on_import)

        # 分割布局
        splitter = QSplitter(Qt.Horizontal)

        # 左：会话列表
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.addWidget(QLabel("会话列表"))
        self.session_list = QListWidget()
        self.session_list.currentItemChanged.connect(self._on_session_selected)
        lv.addWidget(self.session_list)
        splitter.addWidget(left)

        # 右：实时输出
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 4, 4, 4)
        self._output_label = QLabel("输出")
        rv.addWidget(self._output_label)
        self.output_view = QPlainTextEdit()
        self.output_view.setReadOnly(True)
        self.output_view.setFont(QFont("Consolas", 10))
        self.output_view.setMaximumBlockCount(5000)
        rv.addWidget(self.output_view)
        splitter.addWidget(right)

        splitter.setSizes([260, 740])

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.addWidget(splitter)
        self.setCentralWidget(container)

        self.setStatusBar(QStatusBar())

    # ── 会话列表 ────────────────────────────────────────────────────────────

    def _refresh_list(self):
        self.session_list.clear()
        for row in self.registry.list_resumable():
            sid = row["session_id"]
            status = row["status"]
            label = f"{sid}\n{status}  {row['rounds']}/{row['max_rounds']}轮  {row['goal'][:30]}"
            item = QListWidgetItem(label)
            color = STATUS_COLOR.get(status, "#bdc3c7")
            item.setForeground(Qt.GlobalColor.white if status == "running"
                               else Qt.GlobalColor.black)
            item.setBackground(Qt.GlobalColor.darkGreen if status == "running"
                               else Qt.GlobalColor.white)
            item.setData(Qt.UserRole, sid)
            self.session_list.addItem(item)

    def _selected_sid(self) -> Optional[str]:
        item = self.session_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_session_selected(self, current, _previous):
        if current:
            sid = current.data(Qt.UserRole)
            self._output_label.setText(f"输出 — {sid}")
            # 清屏，等新输出推入
            self.output_view.clear()

    # ── 新建 / 恢复 / 停止 ──────────────────────────────────────────────────

    def _on_new(self):
        dlg = NewSessionDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        sid = v["session_id"]
        if self.registry.get(sid):
            QMessageBox.warning(self, "重复", f"会话 {sid} 已存在，请先恢复或删除。")
            return
        self.registry.add(
            session_id=sid,
            work_dir=v["work_dir"],
            goal=v["goal"],
            permission_mode=v["permission"],
            max_rounds=v["max_rounds"],
        )
        self._launch_session(sid)
        self._refresh_list()
        self.statusBar().showMessage(f"已启动会话 {sid}", 3000)

    def _on_resume(self):
        sid = self._selected_sid()
        if not sid:
            return
        self._launch_session(sid, resume=True)
        self.statusBar().showMessage(f"已恢复会话 {sid}", 3000)

    def _on_stop(self):
        sid = self._selected_sid()
        if not sid:
            return
        self.supervisor.stop_session(sid)
        self._refresh_list()
        self.statusBar().showMessage(f"已停止会话 {sid}", 3000)

    def _launch_session(self, sid, resume=False):
        if sid in self._threads and self._threads[sid].isRunning():
            return  # 已在跑

        row = self.registry.get(sid)
        if not row:
            return

        launch = ["claude", "--resume", sid] if resume else ["claude"]
        instruction = f"继续之前未完成的任务：{row['goal']}"

        worker = SessionWorker(self.supervisor, sid,
                               launch_cmd=launch, instruction=instruction)
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._on_output)
        worker.status_changed.connect(self._on_status_changed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._refresh_list)

        self._threads[sid] = thread
        thread.start()

    def _on_output(self, sid, text):
        if self._selected_sid() == sid:
            self.output_view.moveCursor(self.output_view.textCursor().End)
            self.output_view.insertPlainText(text)

    def _on_status_changed(self, sid, status):
        self._refresh_list()
        self.statusBar().showMessage(
            f"会话 {sid} 状态变为 {status}"
            + ("  ⚠ 已达最大轮次，请检查" if status == "stuck" else ""),
            5000,
        )

    # ── 开机自启 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _autorun_enabled() -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTORUN_KEY)
            winreg.QueryValueEx(key, _AUTORUN_NAME)
            winreg.CloseKey(key)
            return True
        except OSError:
            return False

    def _toggle_autorun(self, state):
        exe = sys.executable  # 打包后应替换为 exe 路径
        # 注意：stateChanged 传来的 state 是 int，与 Qt.Checked 枚举直接比较
        # 在 PySide6 下不可靠；直接读复选框的实际勾选状态。
        if self._autorun_cb.isChecked():
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     _AUTORUN_KEY, 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, _AUTORUN_NAME, 0, winreg.REG_SZ,
                                  f'"{exe}" -m gui.app')
                winreg.CloseKey(key)
                self._autorun_cb.setChecked(True)
                self.statusBar().showMessage("已注册开机自启", 3000)
            except OSError as e:
                self._autorun_cb.setChecked(False)
                QMessageBox.warning(
                    self, "注册失败",
                    f"写入注册表失败：{e}\n\n"
                    "可能原因：被安全软件/杀毒拦截，或权限不足。\n\n"
                    "解决办法：\n"
                    "① 在安全软件中信任 claude-guard，再重试；\n"
                    "② 或手动将快捷方式放入 shell:startup 文件夹。",
                )
        else:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     _AUTORUN_KEY, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, _AUTORUN_NAME)
                winreg.CloseKey(key)
            except OSError:
                pass
            self.statusBar().showMessage("已取消开机自启", 3000)

    # ── 导出 / 导入（Snapshotter） ──────────────────────────────────────────

    def _on_export(self):
        rows = self.registry.list_resumable()
        if not rows:
            QMessageBox.information(self, "导出", "没有可导出的会话。")
            return
        sid = self._selected_sid()
        ids = [sid] if sid else [r["session_id"] for r in rows]
        out, _ = QFileDialog.getSaveFileName(
            self, "导出会话快照", "claude-guard-snapshot.zip",
            "Zip 文件 (*.zip)")
        if not out:
            return
        try:
            snapshotter.export_snapshot(self.registry, ids, out)
            QMessageBox.information(
                self, "导出成功",
                f"已导出 {len(ids)} 个会话到：\n{out}")
        except FileNotFoundError as e:
            QMessageBox.warning(self, "导出失败", str(e))
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"{type(e).__name__}: {e}")

    def _on_import(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self, "选择会话快照", "", "Zip 文件 (*.zip)")
        if not zip_path:
            return

        def resolver(session_id, old_path):
            # 路径差异：原工作目录在本机不存在，弹窗让用户重新指定
            QMessageBox.information(
                self, "路径差异",
                f"会话 {session_id} 的原工作目录在本机不存在：\n{old_path}\n\n"
                "请重新指定该项目在本机的目录。")
            new_dir = QFileDialog.getExistingDirectory(
                self, f"为会话 {session_id} 选择工作目录")
            return new_dir or None

        try:
            result = snapshotter.import_snapshot(
                zip_path, self.registry, resolve_path=resolver)
            self._refresh_list()
            msg = f"已导入 {len(result['imported'])} 个会话。"
            if result["skipped"]:
                msg += f"\n跳过 {len(result['skipped'])} 个（未指定目录）。"
            QMessageBox.information(self, "导入完成", msg)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"{type(e).__name__}: {e}")

    # ── 关闭 ─────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        # 停止所有运行中会话（标 paused，保留上下文）
        for sid, thread in list(self._threads.items()):
            if thread.isRunning():
                self.supervisor.stop_session(sid)
        self.registry.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("claude-guard")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
