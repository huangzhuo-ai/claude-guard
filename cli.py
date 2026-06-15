"""claude-guard CLI 入口（阶段一验收用）。

子命令：
  new    新建并托管一个会话
  list   列出所有会话及状态
  resume 恢复一个已存在的会话（--resume <id>）
  stop   停止一个运行中的会话

数据目录默认 ~/.claude-guard/registry.db，可用 --db 覆盖。
"""
import argparse
import sys
import time
from pathlib import Path

from claude_guard.session_registry import SessionRegistry
from claude_guard.supervisor import Supervisor
from claude_guard.config import GuardConfig

DEFAULT_DB = Path.home() / ".claude-guard" / "registry.db"


def _registry(args):
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    return SessionRegistry(db)


def cmd_new(args):
    reg = _registry(args)
    reg.add(
        session_id=args.session_id,
        work_dir=str(Path(args.dir).resolve()),
        goal=args.goal,
        permission_mode=args.permission,
        max_rounds=args.max_rounds,
    )
    sup = Supervisor(reg, config=GuardConfig(idle_settle_seconds=args.idle_seconds))
    launch = ["claude", "--resume", args.session_id] if args.resume_existing \
        else ["claude"]
    print(f"启动会话 {args.session_id}（目录 {args.dir}，权限 {args.permission}）")
    sup.start_session(args.session_id, launch_cmd=launch)
    _follow(sup, reg, args.session_id)


def cmd_resume(args):
    reg = _registry(args)
    row = reg.get(args.session_id)
    if row is None:
        print(f"会话 {args.session_id} 不在账本中", file=sys.stderr)
        return 1
    sup = Supervisor(reg, config=GuardConfig(idle_settle_seconds=args.idle_seconds))
    launch = ["claude", "--resume", args.session_id]
    print(f"恢复会话 {args.session_id}")
    sup.start_session(args.session_id, launch_cmd=launch)
    _follow(sup, reg, args.session_id)
    return 0


def cmd_list(args):
    reg = _registry(args)
    rows = reg.list_resumable()
    if not rows:
        print("（无可恢复会话）")
        return 0
    print(f"{'SESSION_ID':<24} {'STATUS':<10} {'ROUNDS':<8} GOAL")
    for r in rows:
        print(f"{r['session_id']:<24} {r['status']:<10} "
              f"{r['rounds']}/{r['max_rounds']:<6} {r['goal']}")
    return 0


def cmd_stop(args):
    reg = _registry(args)
    reg.update_status(args.session_id, "paused")
    print(f"已标记会话 {args.session_id} 为 paused")
    return 0


def _follow(sup, reg, session_id):
    """前台跟随会话直到结束或 Ctrl+C。"""
    try:
        while sup.is_session_alive(session_id):
            time.sleep(0.5)
        row = reg.get(session_id)
        print(f"会话结束，状态：{row['status']}，轮次 {row['rounds']}")
    except KeyboardInterrupt:
        sup.stop_session(session_id)
        print("\n已暂停会话（Ctrl+C）。下次用 resume 接着跑。")


def build_parser():
    p = argparse.ArgumentParser(prog="claude-guard")
    p.add_argument("--db", default=str(DEFAULT_DB), help="账本数据库路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="新建并托管一个会话")
    n.add_argument("--session-id", required=True, help="会话 ID（账本主键）")
    n.add_argument("--dir", required=True, help="工作目录")
    n.add_argument("--goal", required=True, help="目标任务描述")
    n.add_argument("--permission", default="skip",
                   choices=["skip", "allowlist", "notify"])
    n.add_argument("--max-rounds", type=int, default=20)
    n.add_argument("--idle-seconds", type=float, default=60.0)
    n.add_argument("--resume-existing", action="store_true",
                   help="拉起时带 --resume（接已有 Claude 会话）")
    n.set_defaults(func=cmd_new)

    r = sub.add_parser("resume", help="恢复一个已存在会话")
    r.add_argument("session_id")
    r.add_argument("--idle-seconds", type=float, default=60.0)
    r.set_defaults(func=cmd_resume)

    li = sub.add_parser("list", help="列出可恢复会话")
    li.set_defaults(func=cmd_list)

    st = sub.add_parser("stop", help="停止/暂停一个会话")
    st.add_argument("session_id")
    st.set_defaults(func=cmd_stop)

    return p


def main(argv=None):
    # Windows 控制台默认非 UTF-8，会把中文输出成乱码；统一重配为 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
