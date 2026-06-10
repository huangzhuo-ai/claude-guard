"""SessionRegistry：基于 SQLite 的会话账本。

记录每个被托管 Claude 会话的元数据。所有写入经一把进程内锁串行化，
保证多线程并发时账本不损坏。打开时若检测到主库损坏，自动回退到 .bak 备份。
"""
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

# 可恢复的状态：开机后这些会话会被重新拉起
RESUMABLE_STATUSES = ("running", "paused")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT UNIQUE NOT NULL,
    work_dir        TEXT NOT NULL,
    goal            TEXT NOT NULL,
    permission_mode TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    rounds          INTEGER NOT NULL DEFAULT 0,
    max_rounds      INTEGER NOT NULL DEFAULT 20,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionRegistry:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bak_path = self.db_path.with_suffix(self.db_path.suffix + ".bak")
        self._lock = threading.Lock()
        self._conn = self._open_or_recover()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _open_or_recover(self) -> sqlite3.Connection:
        """打开主库；若损坏且存在备份，则回退备份。"""
        if self.db_path.exists() and not self._is_valid(self.db_path):
            if self.bak_path.exists() and self._is_valid(self.bak_path):
                shutil.copy2(self.bak_path, self.db_path)
            else:
                # 无可用备份，删掉损坏库重新建（账本丢失但不阻塞启动）
                self.db_path.unlink()
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _is_valid(path: Path) -> bool:
        try:
            conn = sqlite3.connect(str(path))
            try:
                conn.execute("PRAGMA integrity_check")
            finally:
                conn.close()
            return True
        except sqlite3.DatabaseError:
            return False

    def add(self, session_id, work_dir, goal, permission_mode, max_rounds=20):
        ts = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (session_id, work_dir, goal, "
                "permission_mode, status, rounds, max_rounds, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, 'running', 0, ?, ?, ?)",
                (session_id, str(work_dir), goal, permission_mode,
                 max_rounds, ts, ts),
            )
            self._conn.commit()

    def get(self, session_id):
        cur = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def update_status(self, session_id, status):
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? "
                "WHERE session_id = ?",
                (status, _now(), session_id),
            )
            self._conn.commit()

    def update_work_dir(self, session_id, work_dir):
        """更新工作目录（导入迁移处理路径差异时用）。"""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET work_dir = ?, updated_at = ? "
                "WHERE session_id = ?",
                (str(work_dir), _now(), session_id),
            )
            self._conn.commit()

    def increment_rounds(self, session_id) -> int:
        """轮次 +1，返回新值。整个读-改-写在锁内完成，并发安全。"""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET rounds = rounds + 1, updated_at = ? "
                "WHERE session_id = ?",
                (_now(), session_id),
            )
            self._conn.commit()
            cur = self._conn.execute(
                "SELECT rounds FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            return cur.fetchone()["rounds"]

    def list_resumable(self):
        placeholders = ",".join("?" for _ in RESUMABLE_STATUSES)
        cur = self._conn.execute(
            f"SELECT * FROM sessions WHERE status IN ({placeholders})",
            RESUMABLE_STATUSES,
        )
        return [dict(r) for r in cur.fetchall()]

    def backup(self):
        """把当前主库复制成 .bak 备份。重要变更后调用。"""
        with self._lock:
            self._conn.commit()
            shutil.copy2(self.db_path, self.bak_path)

    def close(self):
        with self._lock:
            self._conn.close()
