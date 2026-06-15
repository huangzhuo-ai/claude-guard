# claude-guard idle 检测重写设计（pyte 终端模拟）

日期：2026-06-15
状态：已确认，待实现

## 1. 背景与问题

真实环境验证（claude 2.1.177）发现 claude-guard 的核心机制对真 claude 不工作：

- **idle 检测失效**：原 `IdleDetector` 靠「输出末尾匹配提示符 `❯\s*$`」判定一轮完成。但 claude 是全屏 TUI，空闲时屏幕末尾是边框 `╰───╯`、状态栏 `? for shortcuts`，`❯` 输入符在屏幕**中间**而非末尾。提示符正则永远匹配不到 → 永远判不出 idle → Supervisor 永不发下一条续接指令 → 全自动续跑卡死。
- 实测：用真 claude 跑 90 秒任务，状态始终 `running`，指令未执行。
- 根因：原机制建立在「行式程序、提示符在行尾」的假设上，对 TUI 不成立。

附带发现（**本设计不处理**）：用户 claude 装的插件 hook（superpowers/claude-mem 等）在 PTY 里因找不到非标准路径的 Git Bash 而报错刷屏。这是用户 claude 配置层面的问题，不阻止 claude 工作；改用屏幕状态栏判定后，hook 报错只是画面里的无害文本，不影响判定。

## 2. 已确认的关键决策

- **判定「一轮完成」**：状态栏转闲 + 画面静止 N 秒 + 识别提问（三态划分）。
- **GUI 显示**：pyte 渲染的整屏快照实时刷新（像真终端一样就地刷新）。
- **向后兼容**：全面改 pyte，改造「假 Claude」测试程序，不保留旧的行式检测。
- **识别规则**：状态栏特征字符串写进 config.json 可配，不写死代码（应对 claude 版本升级改文案）。
- **架构**：新增 `ScreenModel` 模块夹在 PtyHost 与 IdleDetector/GUI 之间，渲染与判定分离。
- **skip 模式应答 asking**：发回车（claude 的确认是箭头菜单，默认选中第一项，回车确认比发 `y` 可靠）。

## 3. 架构与数据流

```
                  原始字节流
   PtyHost ──────────────────────► ScreenModel (pyte 虚拟屏幕 24×80)
   (只碰进程)                          │
                                      ├── render() ──────► GUI 整屏快照刷新
                                      │
                                      └── classify() ───► IdleDetector
                                                          (状态栏特征 + 计时)
                                                              │
                                                              ▼
                                                          Supervisor
                                                       (忙→闲+静止→发下一条)
```

### 模块职责

- **PtyHost**（基本不变）：字节进出。保留已加固的 `_safe_write`（PTY 关闭返回 False 不抛异常）、多回调隔离（单回调异常不影响其他）。
- **ScreenModel**（新增）：持有 pyte `Screen` + `Stream`，吃 PtyHost 原始字节喂屏幕。对外两个能力：
  - `render() -> str`：当前整屏文本（每行去尾部空白）——给 GUI。
  - `classify() -> "busy" | "idle" | "asking"`：扫描屏幕底部状态栏，对照 config 特征字符串判定——给 IdleDetector。
- **IdleDetector**（重写为薄逻辑）：不再剥 ANSI、扫提示符。轮询 `ScreenModel.classify()` 叠加时间维度。
- **Supervisor**（小改）：主循环消费三态。
- **GUI**：`_on_output` 不再 append，改定时调用 `render()` 整屏刷新。

## 4. 状态判定逻辑（核心）

### ScreenModel.classify()

依据屏幕底部状态栏特征（实测锚点，全部 config 可配）：

| 状态 | 屏幕特征 | 含义 |
|------|---------|------|
| `busy` | 底部出现 `esc to interrupt`，或思考动画 `✻/✢ ...ing…` | claude 正在干活 |
| `asking` | 选项菜单（`❯ 1.` + `Enter to confirm`）或 `(y/n)` 类询问 | 停下来等用户拍板 |
| `idle` | 底部是 `? for shortcuts`，且非上述两种 | 干完了，等输入 |

判定优先级：`asking` > `busy` > `idle`。三者都不匹配 → 归 `busy`（保守，宁可多等不乱发指令）。

### IdleDetector 叠加时间维度

```
classify() 返回          IdleDetector 对外 state
──────────────          ──────────────────────
asking              →   asking（立即透传，不等静止）
busy                →   busy，并记录「最后一次忙」时刻
idle 但距上次忙 <N秒   →   busy（静止观察期，防误判）
idle 且距上次忙 ≥N秒   →   idle（确认真干完了）
```

兜底：画面持续静止超过 settle 秒数的若干倍（如 5×）却始终判不出 idle（例如 claude 升级改了文案导致匹配不到），标 `stuck` 通知用户，避免无限挂起。

### config.json 新增字段（带默认值）

```json
{
  "screen_rows": 24,
  "screen_cols": 80,
  "idle_settle_seconds": 3.0,
  "idle_timeout_multiplier": 5.0,
  "busy_markers": ["esc to interrupt"],
  "idle_markers": ["? for shortcuts"],
  "asking_markers": ["Enter to confirm", "(y/n)", "(y/N)"]
}
```

## 5. Supervisor 主循环（三态消费）

```
拉起进程 → 等首个真 idle（过程中遇 asking 按 permission_mode 处理）
循环:
  if 轮次 >= 上限: 标 stuck, 结束
  发续接指令, 重置静止计时
  等下一个真 idle:
    asking  → permission_mode 处理:
                skip   → 发回车, 重置静止计时, 继续等
                notify → 标 paused, 结束
    idle    → 轮次++, 继续循环
    busy    → 继续等
    进程退出 → 标 done/crashed, 结束
    兜底超时 → 标 stuck, 结束
```

skip 模式对 asking 发回车后若画面无变化（可能未消费），有限次重试后仍不动则标 stuck。

## 6. 错误处理与边界

1. **状态栏匹配不到**（claude 改文案）：classify 归 busy + IdleDetector 兜底超时标 stuck。这是防 claude 升级悄悄搞瘫机制的安全网。
2. **asking 误判保护**：notify 暂停等用户；skip 发回车后重置计时回到等 idle；发回车无效有限次重试后标 stuck。
3. **pyte 解析异常**：喂字节抛异常时吞掉（单块坏字节不影响整体），不打挂监管线程。
4. **写入竞争**：`_safe_write` 返回 False 不抛异常；发指令/回车前检查返回值与进程存活。
5. **坏 hook 噪音**：明确不处理，渲染后仅为无害画面文本。

## 7. 测试策略

延续「假 Claude 程序做基座、PTY 交互可确定性反复测」的金字塔。

1. **改造 `fake_claude.py`**：输出带状态栏的类真 claude 画面——idle 画面（底部 `? for shortcuts`）、收指令转 busy（`esc to interrupt`）后回 idle、收 `perm` 渲染 asking（`❯ 1.Yes ... Enter to confirm`）。用真实光标定位/重绘 ANSI 码，确保 pyte 渲染路径被走到。
2. **单元测试**：
   - `ScreenModel`：喂预录字节流样本（idle/busy/asking/坏文案画面），断言 `render()` 正确、`classify()` 三态正确、匹配不到归 busy。
   - `IdleDetector`：mock classify 返回序列，断言时间维度——busy→idle 未满 settle 仍 busy、满了才 idle、asking 立即透传、兜底超时标 stuck。
3. **集成测试**（Supervisor + 改造假 Claude）：完整状态机——拉起→busy→idle→发下一条→轮次++→上限 stuck；skip 遇 asking 自动回车续跑；notify 遇 asking 暂停。
4. **GUI 测试**：无头模式实例化，喂字节验证 `render()` 整屏快照进了 output_view。
5. **真 claude 冒烟**：手动端到端——临时目录用真 claude 实测「过信任框→发指令→识别干完→发下一条」全流程。

**不变量**：idle_detector、supervisor 相关测试重写；session_registry、snapshotter、pty_host 基本不动。最终全部测试绿 + 真 claude 冒烟通过才算完成。

## 8. 技术选型补充

- 新增依赖：`pyte`（已验证可用，0.8.2）——纯 Python 终端模拟，渲染真 claude TUI 画面准确（空格/布局/菜单全对）。
- 复用已抽出的 `claude_guard/terminal.py`（ANSI 清洗），但 GUI 主显示改走 pyte `render()`；`terminal.py` 仍可用于日志等非屏幕场景。

## 9. 实现影响的文件

- 新增：`claude_guard/screen_model.py`、`tests/test_screen_model.py`
- 重写：`claude_guard/idle_detector.py`、`tests/test_idle_detector.py`、`tests/test_idle_tui.py`
- 改造：`tests/fake_claude.py`、`tests/test_supervisor.py`
- 小改：`claude_guard/supervisor.py`、`gui/app.py`、`gui/workers.py`、`requirements.txt`（加 pyte）
- 配置：项目当前**尚无 config.json 与配置加载逻辑**（旧设计文档提及但从未实现，参数均为构造函数硬编码默认值）。本次新增轻量配置模块 `claude_guard/config.py`：从 `~/.claude-guard/config.json` 读取，缺失字段用内置默认值，文件不存在则全用默认。第 4 节列出的字段由它提供。新增 `tests/test_config.py` 测默认值与覆盖。ScreenModel/IdleDetector 接收配置对象（依赖注入），不自己读文件，保持可测试性。
