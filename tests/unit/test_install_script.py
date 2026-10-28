"""安装脚本的关键行为回归：venv 切换与 Alembic 包装器。"""

from __future__ import annotations

from pathlib import Path

from scripts import install


def test_ensure_venv_returns_false_when_present(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(install, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(install, "info", lambda _msg: None)

    assert install.ensure_venv(dry_run=False) is False


def test_ensure_venv_returns_true_after_creation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(install, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(install, "info", lambda _msg: None)
    monkeypatch.setattr(install, "print_message", lambda _msg="": None)
    monkeypatch.setattr(install.subprocess, "call", lambda _cmd: 0)

    assert install.ensure_venv(dry_run=False) is True


def test_init_database_uses_alembic_wrapper(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(install, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(install, "info", lambda _msg: None)
    monkeypatch.setattr(install, "print_message", lambda _msg="": None)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw) -> int:
        calls.append(cmd)
        return 0

    monkeypatch.setattr(install, "run", fake_run)

    assert install.init_database(dry_run=False) is True
    assert calls
    assert calls[0][1:] == [
        str(tmp_path / "scripts" / "run_alembic.py"),
        "upgrade",
        "head",
    ]


def test_init_database_reports_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(install, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(install, "info", lambda _msg: None)
    monkeypatch.setattr(install, "warn", lambda _msg: None)
    monkeypatch.setattr(install, "print_message", lambda _msg="": None)
    monkeypatch.setattr(install, "run", lambda *_args, **_kw: 1)

    assert install.init_database(dry_run=False) is False


def test_init_database_upgrades_existing_db(tmp_path: Path, monkeypatch) -> None:
    """数据库已存在也必须执行 upgrade head，否则升级带来的新迁移永远不会应用。"""
    monkeypatch.setattr(install, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(install, "info", lambda _msg: None)
    monkeypatch.setattr(install, "print_message", lambda _msg="": None)
    db_path = tmp_path / "cwiki-data" / "cwiki.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw) -> int:
        calls.append(cmd)
        return 0

    monkeypatch.setattr(install, "run", fake_run)

    assert install.init_database(dry_run=False) is True
    assert calls and calls[0][1:] == [
        str(tmp_path / "scripts" / "run_alembic.py"),
        "upgrade",
        "head",
    ]
