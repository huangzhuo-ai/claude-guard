"""IdleDetector TUI 加固测试：模拟全屏 TUI 反复重绘相同内容的场景。

真实 claude 是 Ink TUI，空闲等待时仍可能用 ANSI 控制码重绘屏幕。
若 feed 收到任何字节就重置静止计时，则永远判不出 idle。
加固目标：只有「剥离 ANSI 后的可见内容真正变化」才算有活动。
"""
import time

from claude_guard.idle_detector import IdleDetector

# 模拟 TUI 重绘：清屏 + 光标归位 + 重画同样的提示行
REDRAW = "\x1b[2J\x1b[H\x1b[34m claude ❯ \x1b[0m"
# 模拟思考动画帧（内容真的在变）
SPIN1 = "\x1b[2J\x1b[H⠋ thinking…"
SPIN2 = "\x1b[2J\x1b[H⠙ thinking…"


def test_identical_redraw_does_not_block_idle():
    """反复重绘相同画面 -> 仍能在阈值后判定 idle。

    关键：重绘间隔 < 阈值，若每次 feed 都重置计时，则永远判不出 idle。
    """
    det = IdleDetector(idle_seconds=0.5)
    det.feed(REDRAW)
    # 持续以 0.1s 间隔重绘相同内容，总时间 0.8s > 阈值 0.5s
    # 若计时器被每次重绘重置，则永远不会 idle
    start = time.time()
    while time.time() - start < 0.8:
        time.sleep(0.1)
        det.feed(REDRAW)   # 相同内容
    # 最后一次重绘后应已静止 > 阈值时间（0.8 - 最后一次间隔 ~ 0.1s < 0.5s）
    # 等够阈值
    time.sleep(0.6)
    assert det.state == "idle", f"got {det.state}"


def test_changing_animation_keeps_busy():
    """思考动画（内容在变）-> 保持 busy，不误判 idle。"""
    det = IdleDetector(idle_seconds=0.3)
    for _ in range(6):
        det.feed(SPIN1)
        time.sleep(0.1)
        det.feed(SPIN2)
        time.sleep(0.1)
    assert det.state == "busy"


def test_redraw_then_real_change_resets_timer():
    """相同重绘后出现真实新内容 -> 计时重置，回到 busy。"""
    det = IdleDetector(idle_seconds=0.3)
    det.feed(REDRAW)
    time.sleep(0.4)
    assert det.state == "idle"
    det.feed("\x1b[2J\x1b[H⠋ working on task…")  # 真实新内容
    assert det.state == "busy"
