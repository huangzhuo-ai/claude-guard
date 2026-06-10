"""Snapshotter：会话导出/导入迁移。

导出：把账本中选定会话 + 它们的 Claude 原生 .jsonl 上下文文件打包成 zip。
导入：在另一台机器解包，还原 .jsonl 和账本记录，并处理工作目录路径差异。

zip 结构：
  manifest.json        # 导出元信息（版本、会话清单及原始路径）
  sessions.json        # 账本中各会话的完整字段
  jsonl/<项目目录名>/<会话ID>.jsonl   # Claude 原生上下文文件

不解析 .jsonl 内容，只原样搬运——Claude 升级格式也不受影响。
"""
import json
import zipfile
from pathlib import Path

SNAPSHOT_VERSION = 1


def _default_claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def work_dir_to_project_name(work_dir: str) -> str:
    """把工作目录路径转成 Claude 项目目录名：分隔符与冒号都替换为 '-'。

    例：D:\\Code\\app -> D--Code-app ; C:/Users/huang -> C--Users-huang
    """
    name = work_dir.replace("\\", "-").replace("/", "-").replace(":", "-")
    return name.lstrip("-")


def export_snapshot(registry, session_ids, out_path, claude_projects_dir=None):
    """导出选定会话到 zip。

    缺少 .jsonl 的会话直接报 FileNotFoundError（不静默跳过）。
    """
    projects = Path(claude_projects_dir or _default_claude_projects_dir())
    out_path = Path(out_path)

    sessions = []
    for sid in session_ids:
        row = registry.get(sid)
        if row is None:
            raise ValueError(f"会话 {sid} 不在账本中")
        sessions.append(row)

    manifest = {
        "version": SNAPSHOT_VERSION,
        "sessions": [
            {"session_id": s["session_id"], "work_dir": s["work_dir"]}
            for s in sessions
        ],
    }

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr("sessions.json",
                   json.dumps(sessions, ensure_ascii=False, indent=2))
        for s in sessions:
            pname = work_dir_to_project_name(s["work_dir"])
            src = projects / pname / f"{s['session_id']}.jsonl"
            if not src.exists():
                raise FileNotFoundError(
                    f"会话 {s['session_id']} 的上下文文件缺失：{src}"
                )
            z.write(src, f"jsonl/{pname}/{s['session_id']}.jsonl")

    return out_path


def import_snapshot(zip_path, registry, claude_projects_dir=None,
                    resolve_path=None):
    """从 zip 导入会话到本机。

    resolve_path(session_id, old_work_dir) -> new_dir | None
      原工作目录在本机不存在时调用，让用户重新指定目录；
      返回 None 表示跳过该会话。默认行为：原样使用旧路径。

    导入后会话状态置为 paused。返回 {"imported": [...], "skipped": [...]}。
    """
    projects = Path(claude_projects_dir or _default_claude_projects_dir())
    projects.mkdir(parents=True, exist_ok=True)

    imported, skipped = [], []

    with zipfile.ZipFile(zip_path) as z:
        sessions = json.loads(z.read("sessions.json"))
        for s in sessions:
            sid = s["session_id"]
            old_dir = s["work_dir"]
            work_dir = old_dir

            # 路径差异处理：原目录在本机不存在 -> 让调用方重新指定
            if not Path(old_dir).exists():
                if resolve_path is not None:
                    new_dir = resolve_path(sid, old_dir)
                    if new_dir is None:
                        skipped.append(sid)
                        continue
                    work_dir = new_dir

            # 还原 .jsonl 到新工作目录对应的项目目录
            old_pname = work_dir_to_project_name(old_dir)
            new_pname = work_dir_to_project_name(work_dir)
            arc = f"jsonl/{old_pname}/{sid}.jsonl"
            dest_dir = projects / new_pname
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / f"{sid}.jsonl").write_bytes(z.read(arc))

            # 并入账本（状态 paused），已存在则跳过 add 仅更新路径
            if registry.get(sid) is None:
                registry.add(
                    session_id=sid,
                    work_dir=work_dir,
                    goal=s["goal"],
                    permission_mode=s["permission_mode"],
                    max_rounds=s["max_rounds"],
                )
            registry.update_work_dir(sid, work_dir)
            registry.update_status(sid, "paused")
            imported.append(sid)

    return {"imported": imported, "skipped": skipped}
