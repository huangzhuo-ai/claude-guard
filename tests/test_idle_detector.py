"""IdleDetector 测试：直接 feed 字符串，不依赖真进程。

状态语义：
- busy: 刚有输出、或还在忙（未达静止阈值）
- idle: 距上次输出超过阈值秒数，且输出末尾匹配「等待输入」提示符
- permission_prompt: 输出匹配权限询问模式
"""
import time

from claude_guard.idle_detector import IdleDetector


def test_busy_right_after_output():
    """刚喂入输出、未超时 -> busy。"""
    det = IdleDetector(idle_seconds=5.0)
    det.feed("working...")
    assert det.state == "busy"


def test_idle_after_threshold_with_prompt():
    """超过阈值且末尾是提示符 -> idle。"""
    det = IdleDetector(idle_seconds=0.2)
    det.feed("Claude ready >")
    time.sleep(0.3)
    assert det.state == "idle"


def test_not_idle_before_threshold():
    """末尾是提示符但未超时 -> busy。"""
    det = IdleDetector(idle_seconds=5.0)
    det.feed("Claude ready >")
    assert det.state == "busy"


def test_not_idle_if_no_prompt_at_end():
    """超时但末尾不是提示符（仍在输出中途）-> busy，避免误判。"""
    det = IdleDetector(idle_seconds=0.2)
    det.feed("still computing the answer")
    time.sleep(0.3)
    assert det.state == "busy"


def test_permission_prompt_detected():
    """匹配权限询问模式 -> permission_prompt（优先级高于 idle/busy）。"""
    det = IdleDetector(idle_seconds=5.0)
    det.feed("Do you want to proceed? (y/n)")
    assert det.state == "permission_prompt"


def test_permission_prompt_custom_pattern():
    """权限模式可配置/可更新。"""
    det = IdleDetector(idle_seconds=5.0, permission_patterns=[r"Allow this\?"])
    det.feed("Allow this?")
    assert det.state == "permission_prompt"


def test_reset_clears_state():
    """reset() 后回到初始 busy，且重新计时。"""
    det = IdleDetector(idle_seconds=0.2)
    det.feed("Claude ready >")
    time.sleep(0.3)
    assert det.state == "idle"
    det.reset()
    assert det.state == "busy"


def test_feed_updates_idle_timer():
    """idle 后再喂新输出 -> 回到 busy（计时重置）。"""
    det = IdleDetector(idle_seconds=0.2)
    det.feed("Claude ready >")
    time.sleep(0.3)
    assert det.state == "idle"
    det.feed("working...")
    assert det.state == "busy"
