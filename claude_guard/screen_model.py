"""ScreenModel：用 pyte 维护一块虚拟终端屏幕。

吃 PtyHost 的原始字节（含 ANSI），渲染成真实画面；并据屏幕底部
状态栏特征判定客观三态 busy/idle/asking。不含计时——时间维度由
IdleDetector 叠加。识别特征来自 GuardConfig，可配置。
"""
import re
import threading

import pyte


class ScreenModel:
    def __init__(self, config):
        self._cfg = config
        self._screen = pyte.Screen(config.screen_cols, config.screen_rows)
        self._stream = pyte.Stream(self._screen)
        self._lock = threading.Lock()
        # 预编译正则模式（支持 "regex:..." 前缀）
        self._asking_patterns = self._compile_markers(config.asking_markers)
        self._busy_patterns = self._compile_markers(config.busy_markers)
        self._idle_patterns = self._compile_markers(config.idle_markers)

    def _compile_markers(self, markers):
        """将标记列表编译为 (is_regex, pattern/string) 元组列表。

        支持两种格式：
        - "regex:..." → 正则模式（去掉前缀后编译）
        - 普通字符串 → 子串匹配
        """
        patterns = []
        for m in markers:
            if m.startswith("regex:"):
                patterns.append((True, re.compile(m[6:])))
            else:
                patterns.append((False, m))
        return patterns

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
        只检查最后3行（状态栏位置），避免历史输出干扰。
        支持正则与子串匹配（"regex:..." 前缀启用正则）。
        """
        lines = self.render().splitlines()
        # 只检查最后3行（真实状态栏的位置）
        footer = '\n'.join(lines[-3:]) if len(lines) >= 3 else self.render()

        if self._match_any(footer, self._asking_patterns):
            return "asking"
        if self._match_any(footer, self._busy_patterns):
            return "busy"
        if self._match_any(footer, self._idle_patterns):
            return "idle"
        return "busy"

    def _match_any(self, text, patterns):
        """检查text是否匹配patterns中任一模式（正则或子串）。"""
        for is_regex, pattern in patterns:
            if is_regex:
                if pattern.search(text):
                    return True
            else:
                if pattern in text:
                    return True
        return False
