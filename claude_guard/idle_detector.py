"""IdleDetector：在 ScreenModel 的客观三态上叠加时间维度。

ScreenModel 负责「画面 + 此刻是 busy/idle/asking」（无时间概念）；
本类负责「转闲后静止够久才算真 idle」「卡太久兜底标 stuck」。

state 取值：busy / idle / asking / stuck。
- asking 立即透传（claude 停下问用户，不该等）
- busy 记录最后忙时刻
- idle 未满 settle 秒 -> 仍 busy（观察期，防输出中途误判）
- idle 满 settle 秒 -> idle
- idle 持续超 settle*multiplier 秒 -> stuck（兜底，防文案变化卡死）
"""
import time

from claude_guard.screen_model import ScreenModel


class IdleDetector:
    def __init__(self, config):
        self._cfg = config
        self._screen = ScreenModel(config)
        self.reset()

    def feed(self, text):
        self._screen.feed(text)

    def render(self) -> str:
        return self._screen.render()

    def reset(self):
        """一轮开始时重置计时，回到初始 busy。"""
        self._last_busy = time.monotonic()

    @property
    def state(self) -> str:
        cls = self._screen.classify()
        now = time.monotonic()
        if cls == "asking":
            return "asking"
        if cls == "busy":
            self._last_busy = now
            return "busy"
        # cls == "idle"
        quiet = now - self._last_busy
        settle = self._cfg.idle_settle_seconds
        if quiet < settle:
            return "busy"
        if quiet >= settle * self._cfg.idle_timeout_multiplier:
            return "stuck"
        return "idle"
