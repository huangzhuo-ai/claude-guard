"""PtyHost 测试：用伪终端托管 fake_claude.py，验证读写交互。"""
import sys
import time
from pathlib import Path

import pytest

from claude_guard.pty_host import PtyHost

FAKE = str(Path(__file__).parent / "fake_claude.py")


def _wait_for(host, needle, timeout=5.0):
    """轮询累积输出，直到出现 needle 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in host.output_buffer():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def host():
    h = PtyHost()
    yield h
    h.terminate()


def test_start_shows_ready(host):
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "Claude ready >")


def test_write_triggers_working_and_done(host):
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "Claude ready >")
    host.write("hello\n")
    assert _wait_for(host, "working...")
    assert _wait_for(host, "done.")


def test_is_alive_then_terminate(host):
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "Claude ready >")
    assert host.is_alive() is True
    host.terminate()
    time.sleep(0.3)
    assert host.is_alive() is False


def test_exit_returns_zero():
    host = PtyHost()
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "Claude ready >")
    host.write("exit\n")
    assert host.wait(timeout=5) == 0
