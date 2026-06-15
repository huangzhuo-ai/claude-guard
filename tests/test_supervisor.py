"""Supervisor 集成测试：组合 PtyHost + IdleDetector + SessionRegistry，
接 fake_claude.py 跑完整生命周期，不依赖真 claude。

fake_claude 行为回顾：
- 启动打印 "Claude ready >"
- 收到任意一行 -> "working..." 停 0.5s -> "done. Claude ready >"（一轮）
- 收到 "perm" -> 打印权限询问 "Do you want to proceed? (y/n)"
- 收到 "crash" -> 退出码 3
- 收到 "exit" -> 退出码 0
"""
import sys
import time
from pathlib import Path

import pytest

from claude_guard.session_registry import SessionRegistry
from claude_guard.supervisor import Supervisor
from claude_guard.config import GuardConfig

FAKE = str(Path(__file__).parent / "fake_claude.py")
LAUNCH = [sys.executable, FAKE]


def _fast_cfg():
    # 测试用小阈值：转闲 0.3s 算 idle，超 0.3*8=2.4s 才 stuck
    return GuardConfig(idle_settle_seconds=0.3, idle_timeout_multiplier=8.0)


@pytest.fixture
def registry(tmp_path):
    r = SessionRegistry(tmp_path / "reg.db")
    yield r
    r.close()


def test_runs_until_max_rounds(registry):
    """每轮算一轮；达到 max_rounds=3 后状态变 stuck。

    用 ASCII 指令 "go" 保证 PTY 写入确定性（中文默认指令留给真 Claude 冒烟测试）。
    """
    registry.add("s1", ".", "做点事", "skip", max_rounds=3)
    sup = Supervisor(registry, config=_fast_cfg())
    sup.start_session("s1", launch_cmd=LAUNCH, instruction="go")
    sup.wait_session("s1", timeout=30)
    row = registry.get("s1")
    assert row["rounds"] == 3
    assert row["status"] == "stuck"


def test_stuck_at_max_rounds_two(registry):
    """max_rounds=2 时第 2 轮后状态变 stuck。"""
    registry.add("s2", ".", "目标", "skip", max_rounds=2)
    sup = Supervisor(registry, config=_fast_cfg())
    sup.start_session("s2", launch_cmd=LAUNCH, instruction="go")
    sup.wait_session("s2", timeout=30)
    row = registry.get("s2")
    assert row["rounds"] == 2
    assert row["status"] == "stuck"


def test_stop_session_kills_process(registry):
    """stop_session() 后进程不再存在。"""
    registry.add("s3", ".", "目标", "skip", max_rounds=100)
    sup = Supervisor(registry, config=_fast_cfg())
    sup.start_session("s3", launch_cmd=LAUNCH)
    time.sleep(1.0)  # 让它先跑一会
    sup.stop_session("s3")
    assert sup.is_session_alive("s3") is False


def test_notify_mode_pauses_on_permission(registry):
    """notify 模式遇到权限询问 -> 暂停（paused），不自动按键。"""
    registry.add("s4", ".", "目标", "notify", max_rounds=100)
    sup = Supervisor(registry, config=_fast_cfg())
    sup.start_session("s4", launch_cmd=LAUNCH, instruction="perm")
    sup.wait_session("s4", timeout=30)
    assert registry.get("s4")["status"] == "paused"


def test_skip_mode_auto_answers_permission(registry):
    """skip 模式遇到权限询问 -> 自动应答继续，能正常推进轮次。"""
    registry.add("s5", ".", "目标", "skip", max_rounds=2)
    sup = Supervisor(registry, config=_fast_cfg())
    # 先发一个权限询问，skip 自动应答 Enter 后 fake 回到 ready，继续后续轮次
    sup.start_session("s5", launch_cmd=LAUNCH, instruction="perm")
    sup.wait_session("s5", timeout=30)
    row = registry.get("s5")
    # skip 模式不会因权限而暂停，最终因 max_rounds 触发 stuck
    assert row["status"] == "stuck"


def test_crash_marks_crashed(registry):
    """子进程异常退出（非零退出码）-> 状态 crashed，不自动重启。"""
    registry.add("s6", ".", "目标", "skip", max_rounds=100)
    sup = Supervisor(registry, config=_fast_cfg())
    sup.start_session("s6", launch_cmd=LAUNCH, instruction="crash")
    sup.wait_session("s6", timeout=30)
    assert registry.get("s6")["status"] == "crashed"
