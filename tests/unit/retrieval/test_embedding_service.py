"""embedding 服务懒加载重试行为与指标暴露测试。"""

from __future__ import annotations

import sys
import threading
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


async def test_model_load_hang_is_cut_by_timeout(monkeypatch):
    """模型加载永久阻塞（网络下载无超时）时必须被加载超时切断并走哈希兜底。

    这条路径曾真实拖死调用方：TextEmbedding() 构造卡在 huggingface
    下载上，_ensure_local_model 同步调用它，整个事件循环被无限期占住。
    """
    load_timeout = 0.3

    class _HangingTextEmbedding:
        def __init__(self, model_name: str, cache_dir: str) -> None:
            threading.Event().wait()  # 永久阻塞，模拟无超时的网络下载

    monkeypatch.setitem(
        sys.modules, "fastembed", SimpleNamespace(TextEmbedding=_HangingTextEmbedding)
    )
    # 不真的等 30s：把超时与轮询步长一起压到测试可接受的量级
    monkeypatch.setattr(embedding_module, "_MODEL_LOAD_TIMEOUT_SECONDS", load_timeout)
    monkeypatch.setattr(embedding_module, "_JOIN_POLL_SECONDS", 0.1)
    service = EmbeddingService()

    vector = await service.generate_embedding("加载卡死时应走兜底而不是挂起")

    assert service.provider == "hash"
    assert service._local_model is None
    assert vector is not None
    assert len(vector) == settings.embedding_dimensions
    assert service._load_failures == 1
    assert "TimeoutError" in service._last_load_error
    assert "model load exceeded" in service._last_load_error

    # 超时后进入冷却期：不会每个请求都重新尝试加载
    await service.generate_embedding("冷却期内的第二次调用")
    assert service._load_failures == 1


async def test_model_load_timeout_does_not_leak_local_model(monkeypatch):
    """超时后 _local_model 必须保持 None：迟到的线程结果不得被当成有效模型。"""

    class _SlowTextEmbedding:
        def __init__(self, model_name: str, cache_dir: str) -> None:
            threading.Event().wait(1.5)  # 超过 0.3s 超时后完成
            self.embedding_size = 5

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.2] * self.embedding_size for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=_SlowTextEmbedding))
    monkeypatch.setattr(embedding_module, "_MODEL_LOAD_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(embedding_module, "_JOIN_POLL_SECONDS", 0.1)
    service = EmbeddingService()

    vector = await service.generate_embedding("迟到结果不得生效")

    assert service.provider == "hash"
    assert service._local_model is None
    assert len(vector) == settings.embedding_dimensions
