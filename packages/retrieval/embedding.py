"""Embedding 服务：用本地 ONNX 模型生成文本向量。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from packages.domain.config import settings
from packages.storage import config as storage_config

logger = logging.getLogger(__name__)

_embedding_service: EmbeddingService | None = None

# 加载失败后的冷却间隔：期间内跳过重试，避免每个请求都触发加载尝试
_LOAD_RETRY_INTERVAL_SECONDS = 60.0

# 模型加载超时：网络不通时 TextEmbedding() 会永久卡在模型下载上
# （huggingface 下载无超时），把调用方一起拖死。超过此时长后放弃本次加载，
# 走哈希兜底并按冷却间隔重试；加载本身放在 daemon 线程里，超时后线程
# 自生自灭，不会阻塞进程退出。
_MODEL_LOAD_TIMEOUT_SECONDS = 30.0

# 等待模型加载线程时的单次 join 时长：用小步长轮询代替单次长 join，
# 规避部分平台上 join(timeout>=20) 不返回的问题（macOS + CPython 3.12 实测）
_JOIN_POLL_SECONDS = 5.0

# embedding 性能监控指标
_embedding_metrics: dict[str, int | float] = {
    "total_calls": 0,
    "local_calls": 0,
    "fallback_calls": 0,
    "total_latency_ms": 0.0,
    "local_latency_ms": 0.0,
    "fallback_latency_ms": 0.0,
}


def get_embedding_metrics() -> dict[str, Any]:
    """获取当前 embedding 性能指标。"""
    metrics: dict[str, Any] = _embedding_metrics.copy()
    metrics["provider"] = "not_initialized"
    metrics["model"] = settings.embedding_model
    metrics["dimensions"] = settings.embedding_dimensions
    metrics["is_fallback"] = False
    if _embedding_service is not None:
        metrics["unique_texts"] = len(_embedding_service._unique_texts)
        metrics["cache_hits"] = _embedding_service._cache_hits
        metrics["cache_size"] = len(_embedding_service._cache)
        metrics["provider"] = _embedding_service.provider
        metrics["dimensions"] = _embedding_service.dimensions
        metrics["is_fallback"] = _embedding_service.is_fallback
        metrics["load_failures"] = _embedding_service._load_failures
        metrics["last_load_error"] = _embedding_service._last_load_error
        total = metrics["total_calls"]
        unique = metrics["unique_texts"]
        metrics["dedup_ratio"] = (total - unique) / total if total > 0 else 0.0
        # 缓存命中率：命中次数 / (命中次数 + 实际计算次数)
        total_requests = metrics["cache_hits"] + total
        metrics["cache_hit_rate"] = (
            metrics["cache_hits"] / total_requests if total_requests > 0 else 0.0
        )
    return metrics


def reset_embedding_metrics() -> None:
    """重置 embedding 指标计数器。"""
    for key, value in _embedding_metrics.items():
        _embedding_metrics[key] = 0 if isinstance(value, int) else 0.0
    # 同时清空服务实例上的 unique_texts 集合与缓存命中计数
    if _embedding_service is not None:
        _embedding_service._unique_texts.clear()
        _embedding_service._cache_hits = 0
        # 注意：保留缓存本体，只重置统计


class EmbeddingService:
    """生成文本向量：优先本地 ONNX 模型，失败时哈希兜底。

    提供者链路：本地 ONNX 模型（fastembed）→ 哈希兜底。
    选 fastembed：纯本地 CPU 推理、无 API 依赖、自带模型下载与缓存管理。
    模型按需加载，首次使用时才初始化，减少空闲时内存占用。
    """

    def __init__(self) -> None:
        self._local_model: Any = None
        self._provider: str = "hash"
        self._model_loading = False
        self._model_loaded = False  # 标记是否已成功加载
        self._loading_event = threading.Event()  # 用于线程间加载同步

        # 加载失败跟踪：失败后按冷却间隔重试，避免永久降级或高频重试
        self._load_failures = 0
        self._last_load_error: str | None = None
        self._next_load_retry_at = 0.0

        # 延迟加载：只在首次调用时初始化模型
        self.dimensions = settings.embedding_dimensions
        logger.info(
            "Embedding service initialized (model will load on first use, dim=%d)",
            self.dimensions,
        )

        # 度量：跟踪唯一文本数，估算缓存命中潜力
        self._unique_texts: set[str] = set()
        # LRU cache for embeddings (优化：从 1000 缩减到 500，降低内存占用)
        self._cache: OrderedDict[str, list[float] | None] = OrderedDict()
        self._cache_max_size = 500
        self._cache_hits = 0

    def _ensure_local_model(self) -> None:
        """按需加载本地 ONNX 模型（线程安全；失败后按冷却间隔重试）"""
        if self._local_model is not None:
            return
        if time.monotonic() < self._next_load_retry_at:
            # 上次加载失败且仍在冷却期，跳过重试
            return
        if self._model_loading:
            # 其他线程正在加载，等待完成（避免 busy-wait）
            self._loading_event.wait(timeout=30.0)
            return

        self._model_loading = True
        self._loading_event.clear()
        result: dict[str, Any] = {}
        try:
            self._local_model = self._load_model_with_timeout(result)
            if self._local_model is not None:
                self.dimensions = self._local_model.embedding_size
                self._provider = "local"
                self._model_loaded = True
                self._last_load_error = None
                self._next_load_retry_at = 0.0
                logger.info(
                    "Loaded local embedding model on demand: %s (dim=%d)",
                    settings.embedding_model,
                    self.dimensions,
                )
        except Exception as e:
            self._record_load_failure(e)
        finally:
            self._model_loading = False
            self._loading_event.set()

    def _load_model_with_timeout(self, result: dict[str, Any]) -> Any:
        """在 daemon 线程里加载模型并等待，超时返回 None 走兜底。

        下载/构造失败由线程内捕获后写进 *result*；主线程只负责等待，
        避免网络不通时 TextEmbedding() 永久阻塞调用方的事件循环。
        """

        def _load() -> None:
            try:
                from fastembed import TextEmbedding

                result["model"] = TextEmbedding(
                    model_name=settings.embedding_model,
                    cache_dir=storage_config.embedding_cache_dir,
                )
            except BaseException as e:  # 原样存进 result，由主线程记录
                result["error"] = e

        worker = threading.Thread(target=_load, daemon=True)
        worker.start()
        # 用短 join 轮询等待，避免单次长 join 在某些平台上不返回
        # （macOS + CPython 3.12 实测 join(timeout=20/30) 会一直阻塞）
        deadline = time.monotonic() + _MODEL_LOAD_TIMEOUT_SECONDS
        while worker.is_alive():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=min(remaining, _JOIN_POLL_SECONDS))
        if worker.is_alive():
            # 线程仍在跑（网络下载无超时）：放弃本次加载，走哈希兜底。
            # daemon 线程不会阻塞进程退出。
            self._record_load_failure(
                TimeoutError(
                    f"model load exceeded {_MODEL_LOAD_TIMEOUT_SECONDS:.0f}s "
                    "(network download has no timeout); using hash fallback"
                )
            )
            return None
        if "error" in result:
            raise result["error"]
        return result.get("model")

    def _record_load_failure(self, e: BaseException) -> None:
        """记录加载失败并进入冷却期。"""
        self._load_failures += 1
        self._last_load_error = f"{type(e).__name__}: {e}"
        self._next_load_retry_at = time.monotonic() + _LOAD_RETRY_INTERVAL_SECONDS
        logger.warning(
            "Failed to load local embedding model '%s' (attempt %d): %s. "
            "Using hash fallback; will retry in %.0fs.",
            settings.embedding_model,
            self._load_failures,
            e,
            _LOAD_RETRY_INTERVAL_SECONDS,
        )

    @property
    def is_fallback(self) -> bool:
        """为 True 表示正在使用哈希兜底（向量无语义含义）。"""
        return self._provider == "hash"

    @property
    def provider(self) -> str:
        """当前 embedding 提供者：'local' 或 'hash'。"""
        return self._provider

    async def warm_up(self) -> bool:
        """预加载本地模型；返回 True 表示本地模型可用（False 表示哈希兜底）。"""
        await asyncio.to_thread(self._ensure_local_model)
        return not self.is_fallback

    async def generate_embedding(self, text: str) -> list[float] | None:
        """为给定文本生成向量。"""
        results = await self.generate_embeddings_batch([text])
        return results[0] if results else None

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int = 256
    ) -> list[list[float] | None]:
        """批量生成多段文本的向量。

        返回列表与 *texts* 等长，失败或空文本对应位置为 ``None``。
        LRU 缓存已有的文本直接命中返回，不重复计算。
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        # 仍需计算的索引（缓存未命中 / 空文本）
        pending_indices: list[int] = []
        pending_texts: list[str] = []

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                continue
            cached = self._cache.get(text)
            if cached is not None:
                self._cache_hits += 1
                self._cache.move_to_end(text)
                results[idx] = cached
            else:
                pending_indices.append(idx)
                pending_texts.append(text)

        if not pending_texts:
            return results

        start = time.perf_counter()
        _embedding_metrics["total_calls"] += len(pending_texts)
        # 优化：限制 unique_texts 集合大小，避免无限增长
        for t in pending_texts:
            if len(self._unique_texts) < 10000:
                self._unique_texts.add(t)

        # 每次调用尝试确保模型可用（成功后为快速路径；失败后按冷却间隔重试）
        # 首次加载可能要等 30s，必须放到线程池，不能阻塞事件循环
        await asyncio.to_thread(self._ensure_local_model)

        if self._local_model is not None:
            # 本地 ONNX 推理——同步 embed() 放入线程池，避免阻塞事件循环
            try:
                vectors = await asyncio.to_thread(self._embed_local, pending_texts, batch_size)
                for local_idx, vec in enumerate(vectors):
                    global_idx = pending_indices[local_idx]
                    vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                    results[global_idx] = vec_list
                    orig_text = texts[global_idx]
                    self._cache[orig_text] = vec_list
                    if len(self._cache) > self._cache_max_size:
                        self._cache.popitem(last=False)
                latency = (time.perf_counter() - start) * 1000
                _embedding_metrics["local_calls"] += 1
                _embedding_metrics["local_latency_ms"] += latency
                _embedding_metrics["total_latency_ms"] += latency
            except Exception as e:
                logger.error("Local embedding failed, falling back to hash: %s", e)
                # 本批回退到哈希兜底
                self._embed_hash_batch(pending_indices, pending_texts, texts, results, start)
        else:
            # 哈希兜底
            self._embed_hash_batch(pending_indices, pending_texts, texts, results, start)

        return results

    def _embed_local(self, texts: list[str], batch_size: int) -> list[Any]:
        """分批执行本地 ONNX embedding（在线程池中调用）。"""
        all_vectors: list[Any] = []
        for chunk_start in range(0, len(texts), batch_size):
            chunk = texts[chunk_start : chunk_start + batch_size]
            vectors = list(self._local_model.embed(chunk))
            all_vectors.extend(vectors)
        return all_vectors

    def _embed_hash_batch(
        self,
        pending_indices: list[int],
        pending_texts: list[str],
        texts: list[str],
        results: list[list[float] | None],
        start: float,
    ) -> None:
        """用哈希向量填充待计算文本的结果。"""
        for idx, text in zip(pending_indices, pending_texts):
            vec = self._fallback_embedding(text)
            results[idx] = vec
            self._cache[text] = vec
            if len(self._cache) > self._cache_max_size:
                self._cache.popitem(last=False)
        latency = (time.perf_counter() - start) * 1000
        _embedding_metrics["fallback_calls"] += 1
        _embedding_metrics["fallback_latency_ms"] += latency
        _embedding_metrics["total_latency_ms"] += latency

    def _fallback_embedding(self, text: str) -> list[float] | None:
        """生成确定性的哈希兜底向量。

        循环复用 SHA-256 摘要字节填充所有维度，避免旧方案
        （零填充）产生的近零向量问题。
        """
        import hashlib

        h = hashlib.sha256(text.encode()).digest()
        vec: list[float] = []
        for i in range(self.dimensions):
            byte_idx = i % len(h)
            vec.append((h[byte_idx] - 128) / 128.0)
        return vec


def get_embedding_service() -> EmbeddingService:
    """获取或创建单例 embedding 服务。"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
