# 实现计划：核心引擎（阶段一）

日期：2026-06-10
范围：PtyHost + IdleDetector + SessionRegistry + Supervisor
目标：CLI 能跑通「拉起会话 → 检测静止 → 自动续跑 → 轮次上限暂停」完整链路
不含：Snapshotter、GUI

## 项目结构

```
claude-guard/
├── claude_guard/
│   ├── __init__.py
│   ├── pty_host.py          # PtyHost
│   ├── idle_detector.py     # IdleDetector
│   ├── session_registry.py  # SessionRegistry
│   └── supervisor.py        # Supervisor
├── tests/
│   ├── fake_claude.py       # 假 Claude 程序（测试用）
│   ├── test_pty_host.py
│   ├── test_idle_detector.py
│   ├── test_session_registry.py
│   └── test_supervisor.py
├── cli.py                   # CLI 入口（验收用）
└── requirements.txt
```

## 依赖

```
pywinpty>=2.0
pytest>=7.0
```

---

## Task 1：搭项目骨架

**做什么**
创建目录结构、`requirements.txt`、每个模块的空文件（只有 `pass` 或最小导入）。

**验收**
```
pip install -r requirements.txt
python -c "from claude_guard import pty_host, idle_detector, session_registry, supervisor"
```
无报错即通过。

---

## Task 2：SessionRegistry

**做什么**
用 `sqlite3` 实现会话账本。

数据表 `sessions`：
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| session_id | TEXT UNIQUE | Claude 会话 ID（`--resume` 用） |
| work_dir | TEXT | 工作目录绝对路径 |
| goal | TEXT | 目标任务描述 |
| permission_mode | TEXT | skip / allowlist / notify |
| status | TEXT | running / paused / done / stuck / crashed |
| rounds | INTEGER | 已完成轮次 |
| max_rounds | INTEGER | 轮次上限（默认 20） |
| created_at | TEXT | ISO8601 |
| updated_at | TEXT | ISO8601 |

核心方法：`add()` / `get()` / `update_status()` / `increment_rounds()` / `list_resumable()` / 启动时备份 db 到 `registry.db.bak`。

**验收**（`test_session_registry.py`）
- 增删改查正确
- 状态流转：running → paused → running → done
- 并发写入不损坏（两线程同时 `increment_rounds`，最终值正确）
- 主库损坏时自动回退备份

---

## Task 3：PtyHost

**做什么**
用 `pywinpty` 把一个子进程包在伪终端里，提供：
- `start(cmd, cwd)` — 启动进程
- `write(text)` — 向进程写入（模拟键盘输入）
- `read_output(callback)` — 异步读输出，每行回调
- `is_alive()` — 进程是否还在跑
- `terminate()` — 干净退出
- `wait()` — 等进程结束，返回退出码

**验收**（`test_pty_host.py`，使用 `fake_claude.py`）

`fake_claude.py` 行为：
```
启动后打印 "Claude ready >"
等待输入；收到任意输入后打印 "working..." 然后等 0.5 秒
打印 "done. Claude ready >"
循环
收到 "exit" 时退出
```

测试断言：
- `start()` 后能读到 `"Claude ready >"`
- `write("hello\n")` 后能读到 `"working..."` 和 `"done."`
- `is_alive()` 返回 True；`terminate()` 后返回 False
- `write("exit\n")` 后 `wait()` 返回 0

---

## Task 4：IdleDetector

**做什么**
消费 PtyHost 的输出流，判断状态：

- **idle**：距上次有输出超过 N 秒（可配，默认 5 秒用于测试，生产默认 60 秒），且输出末尾匹配「等待输入」模式（如 `> ` 结尾、或匹配 Claude 的真实提示符）
- **permission_prompt**：输出匹配权限询问模式（规则来自可更新的配置，默认内置几条）
- **busy**：其他情况

核心方法：
- `feed(text)` — 喂入新输出
- `state` 属性 — 返回当前状态 `"idle" | "busy" | "permission_prompt"`
- `reset()` — 一轮开始时重置

**验收**（`test_idle_detector.py`，不需要真进程，直接 `feed` 字符串）
- 喂 `"Claude ready >"` → 超过阈值后 state == `"idle"`
- 喂 `"working..."` → state == `"busy"`
- 喂 `"Do you want to proceed? (y/n)"` → state == `"permission_prompt"`
- 喂输出后立刻检查（未超时）→ state == `"busy"`

---

## Task 5：Supervisor

**做什么**
组合前三者，实现一个会话的完整生命周期：

```
start_session(session_id, work_dir, goal, permission_mode, max_rounds)
  └─ PtyHost.start("claude --resume <id>", cwd=work_dir)
  └─ 等 IdleDetector.state == idle
  └─ write(续接指令)  ← "继续之前未完成的任务：<goal>"
  └─ 循环：
       等 idle
       if state == permission_prompt:
           按 permission_mode 处理（skip→自动 y；allowlist→检查；notify→暂停）
       if rounds >= max_rounds:
           Registry.update_status(stuck); 停止
       else:
           rounds++; 继续等下一轮 idle
  └─ 进程退出时：正常→done；异常→crashed
```

`stop_session(session_id)` — 干净停止

**验收**（`test_supervisor.py`，接 `fake_claude.py`）
- 跑完 3 轮（fake_claude 每收到输入算一轮）后 rounds == 3
- max_rounds=2 时第 2 轮后状态变 `stuck`
- `stop_session()` 后进程不再存在

---

## Task 6：CLI 入口 + 端到端冒烟

**做什么**
写 `cli.py`，子命令：
```
python cli.py new --dir <path> --goal "..." [--permission skip|allowlist|notify] [--max-rounds N]
python cli.py list
python cli.py resume <session_id>
python cli.py stop <session_id>
```

**验收（手动，接真 claude）**
1. `new` 创建并托管一个真实 Claude 会话，能在终端看到实时输出
2. Ctrl+C 停止后 `list` 显示状态 paused
3. `resume` 后 Claude 接着跑（`--resume` 能恢复上下文）
4. 跑到 max_rounds 后状态变 stuck，不自动重启

---

## 执行顺序

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6

每个 Task 完成后：运行该 Task 对应测试全绿 → commit → 进下一个。
