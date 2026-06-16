"""ScreenModel 测试：喂字节，断言渲染与三态判定。

不依赖真进程：直接 feed 预录字节样本。
状态栏特征来自 GuardConfig（可配置）。
"""
from claude_guard.config import GuardConfig
from claude_guard.screen_model import ScreenModel

CFG = GuardConfig()

# 用真实光标定位/清屏 ANSI，确保走 pyte 渲染路径
CLEAR = "\x1b[2J\x1b[H"


def _idle_frame():
    # 顶部对话 + 底部 idle 状态栏
    return CLEAR + "Done.\r\n" + "? for shortcuts \xb7 ← for agents"


def _busy_frame():
    return CLEAR + "✻ Considering…\r\n" + "esc to interrupt"


def _asking_frame():
    return (CLEAR + "Quick safety check\r\n"
            + "❯ 1. Yes, I trust this folder\r\n"
            + "  2. No, exit\r\n"
            + "Enter to confirm \xb7 Esc to cancel")


def test_render_strips_trailing_blank_and_shows_text():
    sm = ScreenModel(CFG)
    sm.feed(_idle_frame())
    out = sm.render()
    assert "Done." in out
    assert "? for shortcuts" in out
    # 不应有海量空行尾巴（render 去尾部空白行）
    assert not out.endswith("\n\n\n")


def test_classify_idle():
    sm = ScreenModel(CFG)
    sm.feed(_idle_frame())
    assert sm.classify() == "idle"


def test_classify_busy():
    sm = ScreenModel(CFG)
    sm.feed(_busy_frame())
    assert sm.classify() == "busy"


def test_classify_asking():
    sm = ScreenModel(CFG)
    sm.feed(_asking_frame())
    assert sm.classify() == "asking"


def test_asking_beats_idle_when_both_present():
    # 屏幕里同时有 idle 与 asking 标记时，asking 优先
    sm = ScreenModel(CFG)
    sm.feed(CLEAR + "? for shortcuts\r\nEnter to confirm")
    assert sm.classify() == "asking"


def test_unknown_screen_defaults_busy():
    # claude 改了文案，三种特征都没命中 -> 保守归 busy
    sm = ScreenModel(CFG)
    sm.feed(CLEAR + "some totally different footer text")
    assert sm.classify() == "busy"


def test_feed_bad_bytes_does_not_raise():
    sm = ScreenModel(CFG)
    sm.feed("\x1b[")          # 不完整转义序列
    sm.feed(_idle_frame())    # 后续正常喂入仍工作
    assert sm.classify() == "idle"


def test_only_checks_footer_not_history():
    """验证只检查最后3行，历史输出中的标记不会干扰。"""
    sm = ScreenModel(CFG)
    # 构造一个屏幕：顶部有历史idle标记，底部是busy状态
    # 24行屏幕，前面塞满"? for shortcuts"，最后一行是busy标记
    fake_history = "\r\n".join(["? for shortcuts"] * 20)
    sm.feed(CLEAR + fake_history + "\r\n" + "esc to interrupt")
    # 应该识别为busy（只看底部），而非idle（被历史干扰）
    assert sm.classify() == "busy"


def test_regex_marker_support():
    """验证 'regex:...' 前缀启用正则匹配。"""
    cfg = GuardConfig(
        # 用正则：要求 "? for shortcuts" 在行尾
        idle_markers=["regex:\\? for shortcuts$"],
        busy_markers=["esc to interrupt"]
    )
    sm = ScreenModel(cfg)
    # "? for shortcuts" 在行尾 -> 应该匹配
    sm.feed(CLEAR + "Done.\r\n? for shortcuts")
    assert sm.classify() == "idle"

    # "? for shortcuts" 在行中 -> 不匹配（正则要求行尾）
    sm2 = ScreenModel(cfg)
    sm2.feed(CLEAR + "? for shortcuts is a feature\r\nesc to interrupt")
    assert sm2.classify() == "busy"  # idle不匹配，busy匹配
