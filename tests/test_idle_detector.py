"""IdleDetector 测试：薄计时逻辑，包一个 ScreenModel。

用真实状态栏画面字节驱动；时间维度用小阈值快速验证。
"""
import time

from claude_guard.config import GuardConfig
from claude_guard.idle_detector import IdleDetector

CLEAR = "\x1b[2J\x1b[H"
IDLE = CLEAR + "Done.\r\n? for shortcuts"
BUSY = CLEAR + "✻ Considering…\r\nesc to interrupt"
ASK = CLEAR + "❯ 1. Yes\r\nEnter to confirm"


def _det(settle=0.2, mult=5.0):
    cfg = GuardConfig(idle_settle_seconds=settle, idle_timeout_multiplier=mult)
    return IdleDetector(cfg)


def test_busy_right_after_busy_frame():
    det = _det()
    det.feed(BUSY)
    assert det.state == "busy"


def test_idle_only_after_settle():
    det = _det(settle=0.3)
    det.feed(BUSY)          # 先忙
    det.feed(IDLE)          # 转闲
    assert det.state == "busy"   # 还在观察期
    time.sleep(0.4)
    assert det.state == "idle"   # 静止够久


def test_asking_is_immediate():
    det = _det(settle=10.0)
    det.feed(ASK)
    assert det.state == "asking"   # 不等观察期


def test_new_busy_resets_settle():
    det = _det(settle=0.3)
    det.feed(BUSY)
    det.feed(IDLE)
    time.sleep(0.4)
    assert det.state == "idle"
    det.feed(BUSY)               # 又忙起来
    assert det.state == "busy"


def test_reset_returns_to_busy():
    det = _det(settle=0.2)
    det.feed(BUSY)
    det.feed(IDLE)
    time.sleep(0.3)
    assert det.state == "idle"
    det.reset()
    assert det.state == "busy"


def test_stuck_after_timeout():
    # settle=0.2, mult=3 -> 0.6s 后仍 idle 则 stuck
    det = _det(settle=0.2, mult=3.0)
    det.feed(BUSY)
    det.feed(IDLE)
    time.sleep(0.3)
    assert det.state == "idle"
    time.sleep(0.5)              # 累计 >0.6s 仍 idle
    assert det.state == "stuck"


def test_render_passthrough():
    det = _det()
    det.feed(IDLE)
    assert "Done." in det.render()
