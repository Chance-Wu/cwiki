"""embedding 服务懒加载重试行为与指标暴露测试。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import packages.retrieval.embedding as embedding_module
from packages.domain.config import settings
from packages.retrieval.embedding import EmbeddingService, get_embedding_metrics


async def test_load_failure_degrades_to_hash_then_retries_after_cooldown(monkeypatch):
    attempts: list[str] = []

    class _FakeTextEmbedding:
        def __init__(self, model_name: str, cache_dir: str) -> None:
            attempts.append(model_name)
            if len(attempts) == 1:
                raise RuntimeError("model files missing")
            self.embedding_size = 5

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.2] * self.embedding_size for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=_FakeTextEmbedding))
    service = EmbeddingService()

    first = await service.generate_embedding("首次调用触发模型加载并失败")
    assert attempts == [settings.embedding_model]
    assert service.is_fallback
    assert len(first) == settings.embedding_dimensions
    assert service._load_failures == 1
    assert service._last_load_error is not None
    assert "RuntimeError" in service._last_load_error

    # 冷却期内不再触发新的加载尝试
    await service.generate_embedding("冷却期内的第二次调用")
    assert len(attempts) == 1

    # 冷却期结束后重试成功并切换到本地模型
    service._next_load_retry_at = 0.0
    third = await service.generate_embedding("冷却期后的第三次调用")
    assert len(attempts) == 2
    assert service.provider == "local"
    assert not service.is_fallback
    assert len(third) == 5
    assert service._last_load_error is None


def test_metrics_default_to_not_initialized(monkeypatch):
    monkeypatch.setattr(embedding_module, "_embedding_service", None)
    metrics = get_embedding_metrics()
    assert metrics["provider"] == "not_initialized"
    assert metrics["model"] == settings.embedding_model
    assert metrics["dimensions"] == settings.embedding_dimensions
    assert metrics["is_fallback"] is False


def test_metrics_report_load_failure_state(monkeypatch):
    service = EmbeddingService()
    service._load_failures = 2
    service._last_load_error = "RuntimeError: model files missing"
    monkeypatch.setattr(embedding_module, "_embedding_service", service)

    metrics = get_embedding_metrics()
    assert metrics["provider"] == "hash"
    assert metrics["is_fallback"] is True
    assert metrics["load_failures"] == 2
    assert metrics["last_load_error"] == "RuntimeError: model files missing"
