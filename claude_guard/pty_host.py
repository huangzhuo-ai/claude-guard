"""PtyHost：用伪终端托管一个子进程。

唯一直接与 Claude 进程交互的模块，刻意隔离以便用假程序测试。
读取在后台线程进行，输出累积到缓冲区；调用方轮询缓冲区或注册逐块回调。

Windows 经由 pywinpty(winpty) 实现；设计上预留跨平台抽象。
"""
import threading


class PtyHost:
    def __init__(self):
        self._pty = None
        self._reader = None
        self._buffer = []
        self._buf_lock = threading.Lock()
        self._callback = None
        self._stopped = threading.Event()

    def start(self, cmd, cwd="."):
        """启动子进程。cmd 为参数列表（如 [python, script]）。"""
        from winpty import PtyProcess

        # PtyProcess.spawn 接受字符串或列表；用列表避免空格转义问题
        self._pty = PtyProcess.spawn(cmd, cwd=str(cwd))
        self._stopped.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        while not self._stopped.is_set():
            try:
                data = self._pty.read()  # 阻塞读，进程结束抛 EOFError
            except EOFError:
                break
            except Exception:
                break
            if not data:
                continue
            with self._buf_lock:
                self._buffer.append(data)
            if self._callback:
                self._callback(data)

    def read_output(self, callback):
        """注册逐块输出回调。每读到一块输出就调用 callback(text)。"""
        self._callback = callback

    def output_buffer(self) -> str:
        """返回迄今累积的全部输出。"""
        with self._buf_lock:
            return "".join(self._buffer)

    def write(self, text):
        """向进程写入原始文本（模拟键盘输入）。

        注意：在伪终端里，「回车」对应的字符是 \\r（回车符），不是 \\n。
        若调用方传入 \\n，自动归一化为 \\r，以匹配真实终端的按键行为。
        """
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        self._pty.write(text)

    def send_line(self, text):
        """发送一行指令并「按回车」。等价于 write(text + 回车)。"""
        self._pty.write(text + "\r")

    def is_alive(self) -> bool:
        return self._pty is not None and self._pty.isalive()

    def terminate(self):
        """强制结束进程。"""
        self._stopped.set()
        if self._pty is not None and self._pty.isalive():
            try:
                self._pty.terminate(force=True)
            except Exception:
                pass

    def wait(self, timeout=None) -> int:
        """等进程结束，返回退出码。轮询存活状态以支持超时。"""
        import time

        deadline = None if timeout is None else time.time() + timeout
        while self._pty.isalive():
            if deadline is not None and time.time() > deadline:
                raise TimeoutError("process did not exit within timeout")
            time.sleep(0.05)
        return self._pty.exitstatus
