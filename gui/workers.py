"""SessionWorker：在 Qt 工作线程里跑 Supervisor，结束时报状态。

显示走 MainWindow 的 QTimer 轮询 supervisor.render_session()，
故此处不再注册逐块输出回调，也不预建 host（Supervisor 自建）。
"""
from PySide6.QtCore import QObject, Signal


class SessionWorker(QObject):
    status_changed = Signal(str, str)  # (session_id, new_status)
    finished = Signal(str)             # session_id

    def __init__(self, supervisor, session_id, launch_cmd=None,
                 instruction=None):
        super().__init__()
        self._sup = supervisor
        self._sid = session_id
        self._launch_cmd = launch_cmd
        self._instruction = instruction

    def run(self):
        self._sup.start_session(
            self._sid,
            launch_cmd=self._launch_cmd,
            instruction=self._instruction,
        )
        self._sup.wait_session(self._sid)
        row = self._sup._registry.get(self._sid)
        if row:
            self.status_changed.emit(self._sid, row["status"])
        self.finished.emit(self._sid)
