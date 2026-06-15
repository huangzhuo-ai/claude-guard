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
