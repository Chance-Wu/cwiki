"""Context benchmark input integrity and process isolation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from benchmarks.runners import context_runner as runner


def test_delivery_snapshot_keeps_events_separate_from_delivery():
    result = SimpleNamespace(
        memories=[SimpleNamespace(memory_id="demoted-but-delivered")],
        text="中文正文",
        token_count=9,
        truncated=False,
        filter_reasons=[
            SimpleNamespace(memory_id="demoted-but-delivered", stage="entry", reason="demoted")
        ],
    )
    snapshot = runner.delivery_snapshot(result)
    assert snapshot["selected_memory_ids"] == ["demoted-but-delivered"]
    assert snapshot["filter_events"][0]["reason"] == "demoted"
    assert snapshot["context"] == "中文正文"
    assert snapshot["rendered_token_estimate"] > 0


def test_missing_pool_memory_fails_instead_of_improving_exclusion():
    with pytest.raises(ValueError, match="q1: pool memory missing"):
        runner._build_pool({"query_id": "q1", "pool": [{"memory_id": "missing", "score": 0.1}]}, {})


def test_pool_copies_fixture_and_supports_inline_content():
    fixture = {"m1": {"id": "m1", "content": "原文", "score": 0.0}}
    pool = runner._build_pool(
        {
            "query_id": "q1",
            "pool": [
                {"memory_id": "m1", "score": 0.9},
                {"memory_id": "inline", "score": 0.8, "content": "合成中文"},
            ],
        },
        fixture,
    )
    assert pool[0]["score"] == 0.9
    assert fixture["m1"]["score"] == 0.0
    assert pool[1]["content"] == "合成中文"


@pytest.mark.parametrize("failure", [False, True])
async def test_settings_restored_on_success_and_failure(monkeypatch, failure):
    settings = SimpleNamespace(relevance_floor_mode="none", relevance_floor=0.23)
    monkeypatch.setattr(runner, "settings", settings)

    async def run():
        assert settings.relevance_floor_mode == "hard"
        assert settings.relevance_floor == 0.5
        if failure:
            raise ValueError("invalid fixture")
        return "report"

    monkeypatch.setattr(runner, "_run_context_benchmark", run)
    if failure:
        with pytest.raises(ValueError, match="invalid fixture"):
            await runner.run_context_benchmark()
    else:
        assert await runner.run_context_benchmark() == "report"
    assert settings.relevance_floor_mode == "none"
    assert settings.relevance_floor == 0.23


async def test_missing_database_does_not_create_file(monkeypatch, tmp_path):
    path = tmp_path / "missing.db"
    monkeypatch.setattr(runner, "FIXTURE_DB", path)
    with pytest.raises(FileNotFoundError, match="Context fixture database not found"):
        await runner._load_fixture_memories()
    assert not path.exists()


async def test_engine_disposed_on_query_failure(monkeypatch, tmp_path):
    path = tmp_path / "fixture.db"
    path.touch()
    monkeypatch.setattr(runner, "FIXTURE_DB", path)
    engine = SimpleNamespace(dispose=AsyncMock())

    def create(url, **kwargs):
        assert url.query == {"mode": "ro", "uri": "true"}
        return engine

    class Session:
        async def __aenter__(self):
            raise RuntimeError("bad schema")

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(runner, "create_async_engine", create)
    monkeypatch.setattr(runner, "async_sessionmaker", lambda *a, **k: Session)
    with pytest.raises(RuntimeError, match="bad schema"):
        await runner._load_fixture_memories()
    engine.dispose.assert_awaited_once()


async def test_empty_gold_is_not_a_valid_report(monkeypatch, tmp_path):
    path = tmp_path / "gold.jsonl"
    path.write_text("\n", encoding="utf-8")
    monkeypatch.setattr(runner, "GOLD_PATH", path)
    monkeypatch.setattr(runner, "_load_fixture_memories", AsyncMock(return_value={}))
    with pytest.raises(ValueError, match="Context gold dataset is empty"):
        await runner._run_context_benchmark()
