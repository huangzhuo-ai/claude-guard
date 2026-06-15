"""Supervisor：会话编排大脑。

组合 PtyHost + IdleDetector(内含 ScreenModel) + SessionRegistry，
管理一个会话的完整生命周期：
  拉起 → 等真 idle → 发续接指令 → 轮次++ → 循环 → 到上限标 stuck
  遇到 asking → 按 permission_mode 处理（skip 发回车 / notify 暂停）
  IdleDetector 兜底判 stuck → 标 stuck 结束
  进程异常退出 → 标 crashed，不重启
"""
import threading
import time

from claude_guard.config import GuardConfig
from claude_guard.idle_detector import IdleDetector
from claude_guard.pty_host import PtyHost

_DEFAULT_INSTRUCTION = "继续之前未完成的任务"
_POLL = 0.1  # 主循环轮询间隔（秒）


class Supervisor:
    def __init__(self, registry, config=None):
        self._registry = registry
        self._cfg = config or GuardConfig()
        self._sessions = {}  # session_id -> {"host","done","det"}

    def start_session(self, session_id, launch_cmd=None, instruction=None):
        """在后台线程里启动并监管一个会话。"""
        row = self._registry.get(session_id)
        if row is None:
            raise ValueError(f"session {session_id} not in registry")

        cmd = launch_cmd or ["claude", "--resume", session_id]
        inst = instruction or f"{_DEFAULT_INSTRUCTION}：{row['goal']}"

        det = IdleDetector(self._cfg)
        if session_id in self._sessions:
            host = self._sessions[session_id]["host"]
            done_event = self._sessions[session_id]["done"]
        else:
            host = PtyHost()
            done_event = threading.Event()
        self._sessions[session_id] = {
            "host": host, "done": done_event, "det": det}

        t = threading.Thread(
            target=self._run,
            args=(session_id, host, det, cmd, row["work_dir"], inst,
                  done_event),
            daemon=True,
        )
        t.start()

    def _run(self, session_id, host, det, cmd, work_dir, instruction, done):
        host.read_output(det.feed)
        try:
            host.start(cmd, cwd=work_dir)
            self._registry.update_status(session_id, "running")

            if not self._wait_idle(host, det, session_id):
                return

            while True:
                row = self._registry.get(session_id)
                if row["rounds"] >= row["max_rounds"]:
                    self._registry.update_status(session_id, "stuck")
                    host.terminate()
                    return

                det.reset()
                host.send_line(instruction)

                if not self._wait_idle(host, det, session_id):
                    return

                self._registry.increment_rounds(session_id)
        finally:
            done.set()

    def _wait_idle(self, host, det, session_id) -> bool:
        """轮询直到真 idle，或进程退出/会话暂停/兜底 stuck。

        返回 True 表示到达 idle；False 表示结束循环。
        """
        while True:
            if not host.is_alive():
                exit_code = host.wait(timeout=2)
                status = "done" if exit_code == 0 else "crashed"
                self._registry.update_status(session_id, status)
                return False

            state = det.state
            if state == "asking":
                if not self._handle_asking(host, det, session_id):
                    return False
                continue
            if state == "stuck":
                self._registry.update_status(session_id, "stuck")
                host.terminate()
                return False
            if state == "idle":
                return True
            time.sleep(_POLL)

    def _handle_asking(self, host, det, session_id) -> bool:
        """按 permission_mode 处理 claude 的提问/确认。

        skip：发回车确认（claude 的确认是箭头菜单，默认选中第一项），
              重置计时后继续等真 idle。
        notify/allowlist：暂停等用户介入。
        返回 True 继续；False 结束。
        """
        mode = self._registry.get(session_id)["permission_mode"]
        if mode == "skip":
            det.reset()
            host.send_line("")   # 纯回车
            return True
        self._registry.update_status(session_id, "paused")
        host.terminate()
        return False

    def stop_session(self, session_id):
        entry = self._sessions.get(session_id)
        if entry:
            entry["host"].terminate()
            self._registry.update_status(session_id, "paused")

    def wait_session(self, session_id, timeout=None):
        entry = self._sessions.get(session_id)
        if entry:
            entry["done"].wait(timeout=timeout)

    def is_session_alive(self, session_id) -> bool:
        entry = self._sessions.get(session_id)
        return bool(entry and entry["host"].is_alive())

    def render_session(self, session_id) -> str:
        """当前整屏快照，供 GUI 显示；无会话返回空串。"""
        entry = self._sessions.get(session_id)
        return entry["det"].render() if entry else ""
