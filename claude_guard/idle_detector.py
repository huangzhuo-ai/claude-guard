"""IdleDetector：消费输出流，判断会话当前处于何种状态。

状态语义（优先级：permission_prompt > idle > busy）：
- permission_prompt: 输出匹配权限询问模式，需要按 permission_mode 处理
- idle: 距上次输出超过阈值秒数，且输出末尾匹配「等待输入」提示符
- busy: 其他情况（刚有输出、或还在忙、或输出停在中途）

不依赖真进程：调用方把 PtyHost 读到的每块输出 feed() 进来即可。
权限询问模式做成可配置/可更新（来自配置文件），不写死。
"""
import re
import time

# 剥离 ANSI/VT 转义序列：PTY 输出里夹杂大量光标/标题/颜色控制码，
# 它们会干扰提示符与权限询问的匹配，匹配前需先清理。
# 覆盖：CSI 序列(\x1b[...)、OSC 序列(\x1b]...\x07 或 \x1b\\)、双字符转义。
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"      # CSI: ESC [ ... final
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC: ESC ] ... BEL/ST
    r"|\x1b[@-Z\\-_]"                  # 双字符转义
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)

# 默认权限询问识别模式（保守、内置几条；生产可由配置覆盖）
DEFAULT_PERMISSION_PATTERNS = [
    r"\(y/n\)",
    r"\(y/N\)",
    r"\[y/n\]",
    r"Do you want to proceed",
    r"Do you want to continue",
    r"Allow .*\?",
]

# 「等待输入」提示符识别：行尾是 ">"（可带空格）即视为回到等待输入
DEFAULT_PROMPT_PATTERN = r">\s*$"


class IdleDetector:
    def __init__(
        self,
        idle_seconds=60.0,
        permission_patterns=None,
        prompt_pattern=DEFAULT_PROMPT_PATTERN,
    ):
        self.idle_seconds = idle_seconds
        patterns = (
            permission_patterns
            if permission_patterns is not None
            else DEFAULT_PERMISSION_PATTERNS
        )
        self._perm_res = [re.compile(p) for p in patterns]
        self._prompt_re = re.compile(prompt_pattern)
        self._tail = ""
        self._last_feed = None

    def feed(self, text):
        """喂入新输出块。重置静止计时，累积到尾部快照。"""
        if not text:
            return
        clean = _strip_ansi(text)
        self._tail = (self._tail + clean)[-4096:]
        self._last_feed = time.monotonic()

    def reset(self):
        """一轮开始时重置：清空尾部，回到初始 busy。"""
        self._tail = ""
        self._last_feed = None

    @property
    def state(self):
        # 还没有任何输出 -> busy
        if self._last_feed is None:
            return "busy"
        # 权限询问优先级最高
        if any(r.search(self._tail) for r in self._perm_res):
            return "permission_prompt"
        # 未达静止阈值 -> busy
        if time.monotonic() - self._last_feed < self.idle_seconds:
            return "busy"
        # 超时但末尾不是提示符（输出停在中途）-> busy，避免误判
        if not self._prompt_re.search(self._tail):
            return "busy"
        return "idle"
