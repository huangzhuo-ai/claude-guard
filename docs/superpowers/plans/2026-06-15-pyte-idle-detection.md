# pyte Idle 检测重写 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 pyte 终端模拟重写 idle 检测，让 claude-guard 能可靠判定真 claude TUI 的「忙/闲/提问」三态，打通全自动续跑。

**Architecture:** 新增 `ScreenModel`（pyte 虚拟屏幕，负责渲染 + 三态判定）夹在 PtyHost 与 IdleDetector/GUI 之间。IdleDetector 退化为「读 ScreenModel 状态 + 计时」的薄逻辑。Supervisor 消费 busy/idle/asking/stuck 四态。GUI 改为定时轮询 `render()` 整屏刷新。状态栏特征字符串由新增的 `GuardConfig` 提供，可经 `~/.claude-guard/config.json` 覆盖。

**Tech Stack:** Python 3.9（项目 `.venv`）、pyte 0.8.2、pywinpty、PySide6、pytest。

> **运行环境提醒：** 所有命令必须用项目 `.venv` 的解释器：`D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe`。anaconda 的 python PySide6 DLL 损坏，不可用。测试以 `PYTHONPATH` 指向仓库根。

> **工作树前提：** 当前分支 `feat/pyte-idle-detection`。工作树已有若干**已验证的底层修复**（`claude_guard/pty_host.py` 的多回调 + `_safe_write`、新增 `claude_guard/terminal.py`、`gui/` 与 `claude_guard/idle_detector.py`/`supervisor.py` 的中间改动、`tests/test_gui_output_flow.py`）。Task 1 先固化 PtyHost 加固；后续任务用整文件 Write 覆盖被重写的模块，因此不依赖这些中间改动的具体行号。

---

## 文件结构

- **新增** `claude_guard/config.py` — `GuardConfig`：运行参数 + 状态栏特征，带默认值，可从 json 覆盖。单一职责：配置。
- **新增** `claude_guard/screen_model.py` — `ScreenModel`：pyte 渲染 + `classify()` 三态。单一职责：把字节变成「画面 + 客观状态」，不含计时。
- **重写** `claude_guard/idle_detector.py` — `IdleDetector`：读 `ScreenModel` + 计时，产出 busy/idle/asking/stuck。单一职责：时间维度判定。
- **重写** `claude_guard/supervisor.py` — 消费四态，skip 模式对 asking 发回车，存 screen 供 GUI 取用。
- **重写** `tests/fake_claude.py` — 输出带状态栏的类真 claude 画面。
- **改** `gui/app.py`、`gui/workers.py` — 显示改 `render()` 轮询，去掉逐块回调路径。
- **改** `cli.py` — 适配 Supervisor 新签名。
- **改** `requirements.txt` — 加 pyte。
- **保留不动** `claude_guard/terminal.py`（spec §8：留作日志等非屏幕场景）、`session_registry.py`、`snapshotter.py`、`pty_host.py`（Task 1 后）。

---

## Task 1: 固化 PtyHost 加固并加依赖

**Files:**
- Modify: `requirements.txt`
- Verify: `claude_guard/pty_host.py`（工作树已含多回调 + `_safe_write`，本任务只确认并提交）
- Test: `tests/test_pty_host.py`（已存在，跑通即可）

- [ ] **Step 1: 把 pyte 写入 requirements.txt**

把文件内容设为：

```
pywinpty>=2.0
pytest>=7.0
PySide6>=6.6
pyte>=0.8
```

- [ ] **Step 2: 确认 pyte 已装在 .venv**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -c "import pyte; print(pyte.__version__)"`
Expected: 打印 `0.8.2`（已装）。若未装：`.venv\Scripts\python.exe -m pip install "pyte>=0.8"`

- [ ] **Step 3: 跑 PtyHost 测试确认加固没破坏**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_pty_host.py -v`
Expected: 4 passed（`test_start_shows_ready`、`test_write_triggers_working_and_done`、`test_is_alive_then_terminate`、`test_exit_returns_zero`）

- [ ] **Step 4: 提交**

```bash
git add requirements.txt claude_guard/pty_host.py
git commit -m "build: add pyte dependency; lock in PtyHost multi-callback + safe-write hardening"
```

---

## Task 2: GuardConfig 配置模块

**Files:**
- Create: `claude_guard/config.py`
- Test: `tests/test_config.py`

`GuardConfig` 持有所有运行参数与状态栏特征。依赖注入用：ScreenModel/IdleDetector 接收 config 对象，不自己读文件。

- [ ] **Step 1: 写失败测试**

Create `tests/test_config.py`:

```python
"""GuardConfig 测试：默认值 + json 覆盖 + 文件缺失。"""
import json

from claude_guard.config import GuardConfig


def test_defaults():
    cfg = GuardConfig()
    assert cfg.screen_rows == 24
    assert cfg.screen_cols == 80
    assert cfg.idle_settle_seconds == 3.0
    assert cfg.idle_timeout_multiplier == 5.0
    assert "esc to interrupt" in cfg.busy_markers
    assert "? for shortcuts" in cfg.idle_markers
    assert any("Enter to confirm" in m for m in cfg.asking_markers)


def test_from_file_overrides(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "idle_settle_seconds": 1.5,
        "busy_markers": ["WORKING"],
    }), encoding="utf-8")
    cfg = GuardConfig.from_file(p)
    # 覆盖生效
    assert cfg.idle_settle_seconds == 1.5
    assert cfg.busy_markers == ["WORKING"]
    # 未提供的字段仍用默认
    assert cfg.screen_rows == 24
    assert "? for shortcuts" in cfg.idle_markers


def test_from_file_missing_uses_defaults(tmp_path):
    cfg = GuardConfig.from_file(tmp_path / "does-not-exist.json")
    assert cfg.idle_settle_seconds == 3.0
    assert cfg.screen_rows == 24
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_guard.config'`

- [ ] **Step 3: 实现 GuardConfig**

Create `claude_guard/config.py`:

```python
"""GuardConfig：运行参数与状态栏识别特征。

带内置默认值，可从 ~/.claude-guard/config.json 覆盖；缺失字段用默认。
ScreenModel / IdleDetector 通过依赖注入接收本对象，自身不读文件，保证可测。
识别特征做成可配置（spec：不写死，应对 claude 版本升级改文案）。
"""
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import List


@dataclass
class GuardConfig:
    screen_rows: int = 24
    screen_cols: int = 80
    idle_settle_seconds: float = 3.0
    idle_timeout_multiplier: float = 5.0
    busy_markers: List[str] = field(
        default_factory=lambda: ["esc to interrupt"])
    idle_markers: List[str] = field(
        default_factory=lambda: ["? for shortcuts"])
    asking_markers: List[str] = field(
        default_factory=lambda: ["Enter to confirm", "(y/n)", "(y/N)"])

    @classmethod
    def from_file(cls, path) -> "GuardConfig":
        """从 json 读取覆盖；文件不存在或字段缺失则用默认。"""
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add claude_guard/config.py tests/test_config.py
git commit -m "feat: add GuardConfig for tunable runtime params and TUI markers"
```

## Task 3: ScreenModel（pyte 渲染 + 三态判定）

**Files:**
- Create: `claude_guard/screen_model.py`
- Test: `tests/test_screen_model.py`

`ScreenModel` 吃原始字节喂 pyte，对外 `render()`（整屏文本）和 `classify()`（busy/idle/asking）。**不含计时**——计时是 IdleDetector 的事。判定优先级：asking > busy > idle；都不匹配 → busy（保守）。

- [ ] **Step 1: 写失败测试**

Create `tests/test_screen_model.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_screen_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_guard.screen_model'`

- [ ] **Step 3: 实现 ScreenModel**

Create `claude_guard/screen_model.py`:

```python
"""ScreenModel：用 pyte 维护一块虚拟终端屏幕。

吃 PtyHost 的原始字节（含 ANSI），渲染成真实画面；并据屏幕底部
状态栏特征判定客观三态 busy/idle/asking。不含计时——时间维度由
IdleDetector 叠加。识别特征来自 GuardConfig，可配置。
"""
import threading

import pyte


class ScreenModel:
    def __init__(self, config):
        self._cfg = config
        self._screen = pyte.Screen(config.screen_cols, config.screen_rows)
        self._stream = pyte.Stream(self._screen)
        self._lock = threading.Lock()

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
        """
        text = self.render()
        if any(m in text for m in self._cfg.asking_markers):
            return "asking"
        if any(m in text for m in self._cfg.busy_markers):
            return "busy"
        if any(m in text for m in self._cfg.idle_markers):
            return "idle"
        return "busy"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_screen_model.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add claude_guard/screen_model.py tests/test_screen_model.py
git commit -m "feat: add ScreenModel for pyte-based rendering and 3-state classification"
```

## Task 4: 重写 IdleDetector（薄计时逻辑）

**Files:**
- Rewrite: `claude_guard/idle_detector.py`（整文件覆盖）
- Rewrite: `tests/test_idle_detector.py`（整文件覆盖）
- Delete: `tests/test_idle_tui.py`（旧的 TUI 重绘加固测试，新机制由 ScreenModel 承担，不再适用）

新 `IdleDetector` 包一个 `ScreenModel`，`feed()` 转发字节给它，`state` 在 `classify()` 之上叠加时间维度：

```
classify()           IdleDetector.state
──────────           ──────────────────
asking           →   asking（立即透传）
busy             →   busy，记录「最后一次忙」时刻
idle 距上次忙<N秒  →   busy（静止观察期）
idle 距上次忙≥N秒  →   idle
（idle 但静止超 N×M 倍仍未被消费）→ stuck（兜底）
```

兜底语义：进入 idle 观察期后，若持续 `idle_settle_seconds * idle_timeout_multiplier` 秒仍是 idle（说明上层没在推进、或文案变化导致卡住），`state` 返回 `stuck`。注意 busy 永不触发 stuck（claude 干长活合法）。

- [ ] **Step 1: 覆盖测试文件**

Overwrite `tests/test_idle_detector.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_idle_detector.py -v`
Expected: FAIL（新 API：`IdleDetector(cfg)`、`det.render()`、`stuck` 状态尚不存在）

- [ ] **Step 3: 覆盖实现**

Overwrite `claude_guard/idle_detector.py`:

```python
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
```

- [ ] **Step 4: 删除过时的 TUI 测试**

```bash
git rm tests/test_idle_tui.py
```

- [ ] **Step 5: 跑测试确认通过**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_idle_detector.py -v`
Expected: 7 passed

- [ ] **Step 6: 提交**

```bash
git add claude_guard/idle_detector.py tests/test_idle_detector.py
git commit -m "feat: rewrite IdleDetector as thin time-layer over ScreenModel (busy/idle/asking/stuck)"
```

## Task 5: 改造 fake_claude（带状态栏的类真 claude）

**Files:**
- Rewrite: `tests/fake_claude.py`（整文件覆盖）
- Modify: `tests/test_pty_host.py`（更新断言的输出特征）

新 fake 用真实清屏/光标 ANSI 渲染带底部状态栏的画面，使 pyte 渲染路径与三态判定被真正走到。同时它仍是行式读输入（读 stdin 一行），保证 PtyHost 写入测试可用。

行为：
- 启动 → 渲染 idle 画面（底部 `? for shortcuts`）
- 收到任意一行（非特殊词）→ 渲染 busy 画面（`esc to interrupt`），停 0.3s，再渲染 idle 画面
- 收到 `perm` → 渲染 asking 画面（`Enter to confirm`）；再收到任意一行 → 回 idle
- 收到 `exit` → 退出码 0
- 收到 `crash` → 退出码 3

- [ ] **Step 1: 覆盖 fake_claude.py**

Overwrite `tests/fake_claude.py`:

```python
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
```

- [ ] **Step 2: 更新 test_pty_host.py 的输出特征**

在 `tests/test_pty_host.py` 中，把依赖旧文案的断言改为新状态栏文案。

将 `test_start_shows_ready`（约 30-32 行）改为：

```python
def test_start_shows_ready(host):
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "? for shortcuts")
```

将 `test_write_triggers_working_and_done`（约 35-40 行）改为：

```python
def test_write_triggers_working_and_done(host):
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "? for shortcuts")
    host.write("hello\n")
    assert _wait_for(host, "esc to interrupt")
```

将 `test_is_alive_then_terminate`（约 43-49 行）中的 needle 改为 `"? for shortcuts"`：

```python
def test_is_alive_then_terminate(host):
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "? for shortcuts")
    assert host.is_alive() is True
    host.terminate()
    time.sleep(0.3)
    assert host.is_alive() is False
```

将 `test_exit_returns_zero`（约 52-57 行）中的 needle 改为 `"? for shortcuts"`：

```python
def test_exit_returns_zero():
    host = PtyHost()
    host.start([sys.executable, FAKE], cwd=".")
    assert _wait_for(host, "? for shortcuts")
    host.write("exit\n")
    assert host.wait(timeout=5) == 0
```

- [ ] **Step 3: 跑 PtyHost 测试确认通过**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_pty_host.py -v`
Expected: 4 passed

- [ ] **Step 4: 提交**

```bash
git add tests/fake_claude.py tests/test_pty_host.py
git commit -m "test: rework fake_claude to render status-bar TUI frames"
```

## Task 6: 重写 Supervisor（消费四态 + asking 发回车）

**Files:**
- Rewrite: `claude_guard/supervisor.py`（整文件覆盖）
- Modify: `tests/test_supervisor.py`（更新构造签名与 fixture）
- Modify: `cli.py`（更新 Supervisor 构造）

变化点：
1. `__init__(self, registry, config=None)` — 不再收 `idle_seconds`，改收 `GuardConfig`（缺省用默认）。
2. IdleDetector 用 config 构造。
3. `_wait_idle` 消费四态：`asking`→按 permission_mode 处理；`idle`→返回 True；`stuck`→标 stuck 结束；`busy`→继续等。
4. skip 模式对 asking **发回车**（`send_line("")`，即纯 `\r`），不再发 `y`。
5. 每个 session entry 存 `det`（IdleDetector），供 GUI 取 `det.render()` 做整屏显示。

- [ ] **Step 1: 更新 test_supervisor.py 的 fixture 与构造**

在 `tests/test_supervisor.py` 顶部 import 区加：

```python
from claude_guard.config import GuardConfig
```

新增一个小 helper（放在 `LAUNCH = [...]` 之后）：

```python
def _fast_cfg():
    # 测试用小阈值：转闲 0.3s 算 idle，超 0.3*8=2.4s 才 stuck
    return GuardConfig(idle_settle_seconds=0.3, idle_timeout_multiplier=8.0)
```

把全部 6 处 `Supervisor(registry, idle_seconds=0.3)` 改为 `Supervisor(registry, config=_fast_cfg())`。

`test_skip_mode_auto_answers_permission` 的注释「skip 自动应答 y」改为「skip 自动发回车」（行为已变，断言不变——仍是最终 stuck）。

- [ ] **Step 2: 覆盖 supervisor.py**

Overwrite `claude_guard/supervisor.py`:

```python
"""Supervisor：会话编排大脑。

组合 PtyHost + IdleDetector(内含 ScreenModel) + SessionRegistry，
管理一个会话的完整生命周期：
  拉起 → 等真 idle → 发续接指令 → 轮次++ → 循环 → 到上限标 stuck
  遇到 asking → 按 permission_mode 处理（skip 发回车 / notify 暂停）
  IdleDetector 兜底判 stuck → 标 stuck 结束
  进程异常退出 → 标 crashed，不重启
"""
import threading
import time

from claude_guard.config import GuardConfig
from claude_guard.idle_detector import IdleDetector
from claude_guard.pty_host import PtyHost

_DEFAULT_INSTRUCTION = "继续之前未完成的任务"
_POLL = 0.1  # 主循环轮询间隔（秒）


class Supervisor:
    def __init__(self, registry, config=None):
        self._registry = registry
        self._cfg = config or GuardConfig()
        self._sessions = {}  # session_id -> {"host","done","det"}

    def start_session(self, session_id, launch_cmd=None, instruction=None):
        """在后台线程里启动并监管一个会话。"""
        row = self._registry.get(session_id)
        if row is None:
            raise ValueError(f"session {session_id} not in registry")

        cmd = launch_cmd or ["claude", "--resume", session_id]
        inst = instruction or f"{_DEFAULT_INSTRUCTION}：{row['goal']}"

        det = IdleDetector(self._cfg)
        if session_id in self._sessions:
            host = self._sessions[session_id]["host"]
            done_event = self._sessions[session_id]["done"]
        else:
            host = PtyHost()
            done_event = threading.Event()
        self._sessions[session_id] = {
            "host": host, "done": done_event, "det": det}

        t = threading.Thread(
            target=self._run,
            args=(session_id, host, det, cmd, row["work_dir"], inst,
                  done_event),
            daemon=True,
        )
        t.start()

    def _run(self, session_id, host, det, cmd, work_dir, instruction, done):
        host.read_output(det.feed)
        try:
            host.start(cmd, cwd=work_dir)
            self._registry.update_status(session_id, "running")

            if not self._wait_idle(host, det, session_id):
                return

            while True:
                row = self._registry.get(session_id)
                if row["rounds"] >= row["max_rounds"]:
                    self._registry.update_status(session_id, "stuck")
                    host.terminate()
                    return

                det.reset()
                host.send_line(instruction)

                if not self._wait_idle(host, det, session_id):
                    return

                self._registry.increment_rounds(session_id)
        finally:
            done.set()

    def _wait_idle(self, host, det, session_id) -> bool:
        """轮询直到真 idle，或进程退出/会话暂停/兜底 stuck。

        返回 True 表示到达 idle；False 表示结束循环。
        """
        while True:
            if not host.is_alive():
                exit_code = host.wait(timeout=2)
                status = "done" if exit_code == 0 else "crashed"
                self._registry.update_status(session_id, status)
                return False

            state = det.state
            if state == "asking":
                if not self._handle_asking(host, det, session_id):
                    return False
                continue
            if state == "stuck":
                self._registry.update_status(session_id, "stuck")
                host.terminate()
                return False
            if state == "idle":
                return True
            time.sleep(_POLL)

    def _handle_asking(self, host, det, session_id) -> bool:
        """按 permission_mode 处理 claude 的提问/确认。

        skip：发回车确认（claude 的确认是箭头菜单，默认选中第一项），
              重置计时后继续等真 idle。
        notify/allowlist：暂停等用户介入。
        返回 True 继续；False 结束。
        """
        mode = self._registry.get(session_id)["permission_mode"]
        if mode == "skip":
            det.reset()
            host.send_line("")   # 纯回车
            return True
        self._registry.update_status(session_id, "paused")
        host.terminate()
        return False

    def stop_session(self, session_id):
        entry = self._sessions.get(session_id)
        if entry:
            entry["host"].terminate()
            self._registry.update_status(session_id, "paused")

    def wait_session(self, session_id, timeout=None):
        entry = self._sessions.get(session_id)
        if entry:
            entry["done"].wait(timeout=timeout)

    def is_session_alive(self, session_id) -> bool:
        entry = self._sessions.get(session_id)
        return bool(entry and entry["host"].is_alive())

    def render_session(self, session_id) -> str:
        """当前整屏快照，供 GUI 显示；无会话返回空串。"""
        entry = self._sessions.get(session_id)
        return entry["det"].render() if entry else ""
```

- [ ] **Step 3: 更新 cli.py 的 Supervisor 构造**

在 `cli.py` 中，`Supervisor(reg, idle_seconds=args.idle_seconds)` 出现 2 处（`cmd_new`、`cmd_resume`），都改为：

```python
from claude_guard.config import GuardConfig
...
sup = Supervisor(reg, config=GuardConfig(idle_settle_seconds=args.idle_seconds))
```

（保留 `--idle-seconds` 参数语义：映射到 settle 秒数。在两个函数各自的局部 import 或文件顶部 import `GuardConfig` 均可，文件顶部更清晰。）

- [ ] **Step 4: 跑 supervisor 测试确认通过**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_supervisor.py -v`
Expected: 6 passed（runs_until_max_rounds、stuck_at_max_rounds_two、stop_session_kills_process、notify_mode_pauses_on_permission、skip_mode_auto_answers_permission、crash_marks_crashed）

- [ ] **Step 5: 提交**

```bash
git add claude_guard/supervisor.py tests/test_supervisor.py cli.py
git commit -m "feat: Supervisor consumes 4-state idle detection; skip answers asking with Enter"
```

## Task 7: GUI 改整屏快照轮询显示

**Files:**
- Modify: `gui/workers.py`（简化：去掉逐块 output 信号与 host 预建）
- Modify: `gui/app.py`（QTimer 轮询 `render_session` → `setPlainText`）
- Rewrite: `tests/test_gui_output_flow.py`（整文件覆盖为新轮询模型）

新显示模型：不再逐块 append。MainWindow 用一个 QTimer 每 ~200ms 调 `supervisor.render_session(选中sid)`，整屏 `setPlainText` 刷新——所见即真终端当前画面。Worker 退化为「跑会话 + 报状态」，host 由 Supervisor 自建，det 也由它管。

- [ ] **Step 1: 简化 gui/workers.py**

Overwrite `gui/workers.py`:

```python
"""SessionWorker：在 Qt 工作线程里跑 Supervisor，结束时报状态。

显示走 MainWindow 的 QTimer 轮询 supervisor.render_session()，
故此处不再注册逐块输出回调，也不预建 host（Supervisor 自建）。
"""
from PySide6.QtCore import QObject, Signal


class SessionWorker(QObject):
    status_changed = Signal(str, str)  # (session_id, new_status)
    finished = Signal(str)             # session_id

    def __init__(self, supervisor, session_id, launch_cmd=None,
                 instruction=None):
        super().__init__()
        self._sup = supervisor
        self._sid = session_id
        self._launch_cmd = launch_cmd
        self._instruction = instruction

    def run(self):
        self._sup.start_session(
            self._sid,
            launch_cmd=self._launch_cmd,
            instruction=self._instruction,
        )
        self._sup.wait_session(self._sid)
        row = self._sup._registry.get(self._sid)
        if row:
            self.status_changed.emit(self._sid, row["status"])
        self.finished.emit(self._sid)
```

- [ ] **Step 2: gui/app.py — 改 import 行**

将第 14 行 `from PySide6.QtCore import Qt, QThread` 改为：

```python
from PySide6.QtCore import Qt, QThread, QTimer
```

第 15 行 `from PySide6.QtGui import QFont, QTextCursor` 改回（不再需要 QTextCursor）：

```python
from PySide6.QtGui import QFont
```

第 25 行附近 `from claude_guard.supervisor import Supervisor` 之后，确认仍 import `GuardConfig`（Task 6 已在 Supervisor 内部默认，不强制 GUI 传）。无需新增。

- [ ] **Step 3: gui/app.py — 启一个轮询 QTimer**

在 `MainWindow.__init__` 中 `self._build_ui()` 与 `self._refresh_list()` 之间插入：

```python
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(200)  # ms
        self._poll_timer.timeout.connect(self._refresh_output)
        self._poll_timer.start()
```

- [ ] **Step 4: gui/app.py — 用 _refresh_output 取代 _on_output**

将 `_on_output` 方法（当前约 273-277 行，整段）替换为：

```python
    def _refresh_output(self):
        sid = self._selected_sid()
        if not sid:
            return
        snapshot = self.supervisor.render_session(sid)
        # 整屏快照：仅在变化时刷新，避免光标/滚动抖动
        if snapshot != self.output_view.toPlainText():
            self.output_view.setPlainText(snapshot)
```

- [ ] **Step 5: gui/app.py — 移除已失效的 output 信号连接**

在 `_launch_session` 中删除这一行（约 264 行）：

```python
        worker.output.connect(self._on_output)
```

- [ ] **Step 6: gui/app.py — 移除不再使用的 clean_for_display import**

删除第 26 行附近的：

```python
from claude_guard.terminal import clean_for_display
```

（GUI 主显示已改走 pyte `render_session()`；该函数仍保留在 `terminal.py` 供其他场景，spec §8。）

- [ ] **Step 7: 覆盖 tests/test_gui_output_flow.py（轮询模型）**

Overwrite `tests/test_gui_output_flow.py`:

```python
"""GUI 整屏快照显示链路测试（无头 offscreen）。

验证：会话跑起来后，MainWindow 的轮询能把 supervisor.render_session()
的整屏快照刷进 output_view。用改造后的 fake_claude（带状态栏画面）。
"""
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAKE = str(Path(__file__).parent / "fake_claude.py")


@pytest.fixture
def win(tmp_path, monkeypatch):
    from claude_guard.session_registry import SessionRegistry  # noqa: F401
    import gui.app as appmod
    monkeypatch.setattr(appmod, "_DB", tmp_path / "reg.db")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    w = appmod.MainWindow()
    yield w
    w.close()


def _pump(ms=3000):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def test_snapshot_reaches_output_view(win):
    from PySide6.QtCore import Qt, QThread
    from gui.workers import SessionWorker

    sid = "gui-" + uuid.uuid4().hex[:8]
    win.registry.add(sid, ".", "verify", "skip", max_rounds=1)
    win._refresh_list()
    for i in range(win.session_list.count()):
        it = win.session_list.item(i)
        if it.data(Qt.UserRole) == sid:
            win.session_list.setCurrentItem(it)
            break

    worker = SessionWorker(win.supervisor, sid,
                           launch_cmd=[sys.executable, FAKE],
                           instruction="go")
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    win._threads[sid] = thread
    thread.start()

    _pump(4000)
    text = win.output_view.toPlainText()
    thread.quit(); thread.wait(2000)

    assert "? for shortcuts" in text or "Claude ready" in text, repr(text)
```

- [ ] **Step 8: 跑 GUI 测试确认通过**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/test_gui_output_flow.py -v`
Expected: 1 passed

- [ ] **Step 9: 提交**

```bash
git add gui/app.py gui/workers.py tests/test_gui_output_flow.py
git commit -m "feat: GUI shows live full-screen snapshot via QTimer polling render_session"
```

---

## Task 8: 全量回归 + 真 claude 冒烟

**Files:** 无新增；端到端验证。

- [ ] **Step 1: 跑全部测试（.venv）**

Run: `D:\Code\python\project\pinpianyi\git\claude-guard\.venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 全部 passed。预期测试集：test_config(3)、test_screen_model(7)、test_idle_detector(7)、test_pty_host(4)、test_session_registry(7)、test_snapshotter(6)、test_supervisor(6)、test_gui_output_flow(1)。test_idle_tui 已删除。

若有红：先看是否 marker 文案不一致（fake_claude 的状态栏须与 GuardConfig 默认 markers 完全对应）。

- [ ] **Step 2: 真 claude 冒烟（手动端到端）**

在临时目录用真 claude 跑一轮，验证「过信任框 → 发指令 → 识别干完 → 发下一条」。

Run:
```bash
rm -rf /tmp/cg-smoke && mkdir -p /tmp/cg-smoke && cd /tmp/cg-smoke && \
PYTHONPATH=D:/Code/python/project/pinpianyi/git/claude-guard \
D:/Code/python/project/pinpianyi/git/claude-guard/.venv/Scripts/python.exe -X utf8 -c "
import time, tempfile, threading
from pathlib import Path
from claude_guard.session_registry import SessionRegistry
from claude_guard.supervisor import Supervisor
from claude_guard.config import GuardConfig

db = Path(tempfile.mkdtemp())/'reg.db'
reg = SessionRegistry(db)
reg.add('smoke', '.', 'create file', 'skip', max_rounds=1)
# 真 claude 思考较慢，settle 给足
sup = Supervisor(reg, config=GuardConfig(idle_settle_seconds=4.0,
                                         idle_timeout_multiplier=20.0))
sup.start_session('smoke', launch_cmd=['claude'],
    instruction='Create a file named hello.txt with content hi, then stop')
for i in range(120):
    time.sleep(1)
    st = reg.get('smoke')['status']
    if Path('hello.txt').exists():
        print(f'hello.txt created @ {i+1}s status={st}'); break
    if not sup.is_session_alive('smoke'):
        print(f'process ended @ {i+1}s status={st}'); break
else:
    print('timeout status=', reg.get('smoke')['status'])
print('=== last screen ===')
print(sup.render_session('smoke')[-800:])
sup.stop_session('smoke')
print('hello.txt exists:', Path('hello.txt').exists())
reg.close()
"
```
Expected: 打印 `hello.txt created`（自动过信任框、执行指令、识别完成）；`hello.txt exists: True`。
注意：用户 claude 的插件 hook 在 PTY 里会刷错误（spec §1 已知，不处理）——只要 hello.txt 被创建、状态正常推进即算通过。若超时未创建，记录 last screen 供诊断（很可能是 marker 文案需按当前 claude 版本微调 GuardConfig，再重试）。

- [ ] **Step 3: 提交冒烟记录（可选）**

冒烟为手动验证，无代码变更则不提交。若过程中按真 claude 版本调整了 GuardConfig 默认 markers，提交该改动：

```bash
git add claude_guard/config.py
git commit -m "fix: tune default TUI markers to match claude <version>"
```

- [ ] **Step 4: 合并准备**

确认全绿 + 冒烟通过后，分支 `feat/pyte-idle-detection` 可发 PR。
Run: `git log --oneline main..HEAD`
Expected: 看到本计划的 8 个提交 + 之前的 spec 提交。
