"""SessionWorker：在 Qt 工作线程里跑 Supervisor，把输出通过 signal 推给主线程。"""
from PySide6.QtCore import QObject, Signal, QThread


class SessionWorker(QObject):
    output = Signal(str, str)    # (session_id, text)
    status_changed = Signal(str, str)  # (session_id, new_status)
    finished = Signal(str)       # session_id

    def __init__(self, supervisor, session_id, launch_cmd=None, instruction=None):
        super().__init__()
        self._sup = supervisor
        self._sid = session_id
        self._launch_cmd = launch_cmd
        self._instruction = instruction

    def run(self):
        host = self._sup._sessions.get(self._sid, {}).get("host")
        if host:
            host.read_output(lambda t: self.output.emit(self._sid, t))
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
