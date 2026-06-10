"""Supervisor：会话编排大脑。

组合 PtyHost + IdleDetector + SessionRegistry，管理一个会话的完整生命周期：
  拉起 → 等 idle → 发续接指令 → 轮次++ → 循环 → 到上限标 stuck
  遇到 permission_prompt → 按 permission_mode 处理
  进程异常退出 → 标 crashed，不重启
"""
import threading

from claude_guard.idle_detector import IdleDetector
from claude_guard.pty_host import PtyHost

_DEFAULT_INSTRUCTION = "继续之前未完成的任务"
_POLL = 0.1  # 主循环轮询间隔（秒）


class Supervisor:
    def __init__(self, registry, idle_seconds=60.0):
        self._registry = registry
        self._idle_seconds = idle_seconds
        self._sessions = {}  # session_id -> {"host": PtyHost, "done": Event}

    def start_session(self, session_id, launch_cmd=None, instruction=None):
        """在后台线程里启动并监管一个会话。

        launch_cmd: 要运行的命令列表（默认 ['claude', '--resume', session_id]）
        instruction: 每轮发给进程的续接指令（默认中文模板）
        """
        row = self._registry.get(session_id)
        if row is None:
            raise ValueError(f"session {session_id} not in registry")

        cmd = launch_cmd or ["claude", "--resume", session_id]
        inst = instruction or f"{_DEFAULT_INSTRUCTION}：{row['goal']}"
        done_event = threading.Event()
        host = PtyHost()
        self._sessions[session_id] = {"host": host, "done": done_event}

        t = threading.Thread(
            target=self._run,
            args=(session_id, host, cmd, row["work_dir"], inst, done_event),
            daemon=True,
        )
        t.start()

    def _run(self, session_id, host, cmd, work_dir, instruction, done):
        det = IdleDetector(idle_seconds=self._idle_seconds)
        host.read_output(det.feed)
        try:
            host.start(cmd, cwd=work_dir)
            self._registry.update_status(session_id, "running")

            # 等初始 idle（进程启动完成）
            if not self._wait_idle(host, det, session_id):
                return  # 提前退出

            # 主循环
            while True:
                row = self._registry.get(session_id)
                if row["rounds"] >= row["max_rounds"]:
                    self._registry.update_status(session_id, "stuck")
                    host.terminate()
                    return

                det.reset()
                host.send_line(instruction)

                # 等这一轮结束
                if not self._wait_idle(host, det, session_id):
                    return  # 进程已退出或被停止

                self._registry.increment_rounds(session_id)

        finally:
            done.set()

    def _wait_idle(self, host, det, session_id) -> bool:
        """轮询直到 idle/permission_prompt，或进程退出。
        返回 True 表示到达 idle；False 表示进程退出（调用方应结束循环）。
        """
        import time

        while True:
            if not host.is_alive():
                exit_code = host.wait(timeout=2)
                status = "done" if exit_code == 0 else "crashed"
                self._registry.update_status(session_id, status)
                return False

            state = det.state
            if state == "permission_prompt":
                return self._handle_permission(host, det, session_id)
            if state == "idle":
                return True
            time.sleep(_POLL)

    def _handle_permission(self, host, det, session_id) -> bool:
        """按 permission_mode 处理权限询问。
        返回 True 表示应继续循环；False 表示暂停（调用方结束）。
        """
        mode = self._registry.get(session_id)["permission_mode"]
        if mode == "skip":
            det.reset()
            host.send_line("y")
            return True  # 继续
        # notify / allowlist：暂停等用户介入
        self._registry.update_status(session_id, "paused")
        host.terminate()
        return False

    def stop_session(self, session_id):
        """干净停止一个会话。"""
        entry = self._sessions.get(session_id)
        if entry:
            entry["host"].terminate()
            self._registry.update_status(session_id, "paused")

    def wait_session(self, session_id, timeout=None):
        """阻塞等待会话结束（done 事件）。"""
        entry = self._sessions.get(session_id)
        if entry:
            entry["done"].wait(timeout=timeout)

    def is_session_alive(self, session_id) -> bool:
        entry = self._sessions.get(session_id)
        return bool(entry and entry["host"].is_alive())
