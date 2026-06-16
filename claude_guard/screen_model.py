"""ScreenModel：用 pyte 维护一块虚拟终端屏幕。

吃 PtyHost 的原始字节（含 ANSI），渲染成真实画面；并据屏幕底部
状态栏特征判定客观三态 busy/idle/asking。不含计时——时间维度由
IdleDetector 叠加。识别特征来自 GuardConfig，可配置。
"""
import threading

import pyte


class ScreenModel:
    def __init__(self, config):
        self._cfg = config
        self._screen = pyte.Screen(config.screen_cols, config.screen_rows)
        self._stream = pyte.Stream(self._screen)
        self._lock = threading.Lock()

    def feed(self, text: str):
        """喂入一块原始输出。单块坏字节不应打挂调用方。"""
        if not text:
            return
        with self._lock:
            try:
                self._stream.feed(text)
            except Exception:
                pass  # 容忍坏/不完整序列，不影响后续

    def render(self) -> str:
        """当前整屏文本：每行去右侧空白，去掉尾部连续空行。"""
        with self._lock:
            lines = [line.rstrip() for line in self._screen.display]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    def classify(self) -> str:
        """据状态栏特征判定 busy/idle/asking。

        优先级 asking > busy > idle；都不命中 -> busy（保守）。
        """
        text = self.render()
        if any(m in text for m in self._cfg.asking_markers):
            return "asking"
        if any(m in text for m in self._cfg.busy_markers):
            return "busy"
        if any(m in text for m in self._cfg.idle_markers):
            return "idle"
        return "busy"
