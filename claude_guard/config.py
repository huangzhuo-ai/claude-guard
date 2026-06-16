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
