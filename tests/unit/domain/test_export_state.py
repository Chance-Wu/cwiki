"""导出时间状态：到期判断与重启追赶。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from packages.storage import export_state


def _now() -> datetime:
    return datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


def test_never_exported_is_due(tmp_path, monkeypatch):
    monkeypatch.setattr(export_state, "_STATE_PATH", tmp_path / "meta_export.json")
    assert export_state.read_last_export() is None
    assert export_state.export_due(12, now=_now())
    assert export_state.seconds_until_due(12, now=_now()) == 0.0


def test_recorded_export_waits_remaining_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(export_state, "_STATE_PATH", tmp_path / "meta_export.json")
    export_state.record_export(_now() - timedelta(hours=2))

    assert export_state.read_last_export() == _now() - timedelta(hours=2)
    assert not export_state.export_due(12, now=_now())
    assert export_state.seconds_until_due(12, now=_now()) == 10 * 3600


def test_overdue_export_is_due_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(export_state, "_STATE_PATH", tmp_path / "meta_export.json")
    export_state.record_export(_now() - timedelta(hours=13))

    assert export_state.export_due(12, now=_now())
    assert export_state.seconds_until_due(12, now=_now()) == 0.0


def test_corrupt_state_treated_as_never_exported(tmp_path, monkeypatch):
    path = tmp_path / "meta_export.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(export_state, "_STATE_PATH", path)

    assert export_state.read_last_export() is None
    assert export_state.export_due(12, now=_now())
