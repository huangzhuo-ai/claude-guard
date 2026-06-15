"""假 claude：渲染带底部状态栏的 TUI 画面，确定性测试用，不依赖真 claude。

用真实 ANSI 清屏/光标定位渲染，使 pyte 渲染与三态判定被走到。
行式读 stdin，每收到一行根据内容切换画面。
状态栏特征与 GuardConfig 默认值一致：
  idle  -> "? for shortcuts"
  busy  -> "esc to interrupt"
  asking-> "Enter to confirm"
"""
import sys
import time

CLEAR = "\x1b[2J\x1b[H"


def _draw(body: str, footer: str):
    sys.stdout.write(CLEAR + body + "\r\n" + footer)
    sys.stdout.flush()


def _idle():
    _draw("Claude ready.", "? for shortcuts \xb7 \xe2\x86\x90 for agents")


def _busy():
    _draw("✻ Considering…", "esc to interrupt")


def _asking():
    _draw("❯ 1. Yes\r\n  2. No", "Enter to confirm \xb7 Esc to cancel")


def main():
    _idle()
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        cmd = line.strip()
        if cmd == "exit":
            sys.exit(0)
        if cmd == "crash":
            sys.exit(3)
        if cmd == "perm":
            _asking()
            continue
        # 普通指令：忙一下再回到 idle
        _busy()
        time.sleep(0.3)
        _idle()


if __name__ == "__main__":
    main()
