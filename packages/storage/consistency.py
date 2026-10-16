"""运行时只读一致性对账：DB / Markdown / index.db / vectors 四份载体比对。

崩溃或手动误删可能导致三份物理载体（SQLite 主库、MD 镜像、检索索引）
漂移。本模块只量化漂移、不做任何修复——修复仍由现有 sync 机制负责，
这是有意的设计决定（对账报告供人工/运维判断，避免对账路径引入写风险）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiosqlite
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory
from packages.domain.schemas import ConsistencyReport
from packages.storage import config as storage_config
from packages.storage.file_store import FileStore

logger = logging.getLogger(__name__)

# diff 列表最多展示的 id 数：超出部分只计入总数，避免大漂移时响应体膨胀
MAX_LISTED_IDS = 50


async def run_consistency_check(
    db: AsyncSession,
    *,
    memory_dir: str | Path | None = None,
    index_db_path: str | Path | None = None,
    vector_index_path: str | Path | None = None,
) -> ConsistencyReport:
    """对 DB / MD / index.db / vectors 做只读对账，返回差异报告。

    只比对 active 记忆：archived 记忆在 MD 与 index.db 中保留镜像但不参与
    检索（indexer.sync_all 的既有约定），纳入比对会把合法归档误报为漂移。

    路径参数默认取 storage 配置，可注入以便测试。单个载体读取失败不抛
    异常，在 errors 中按载体名记录原因；全程只读——不写文件、不改 DB。
    """
    memory_dir = Path(memory_dir) if memory_dir is not None else Path(storage_config.memory_dir)
    index_db_path = (
        Path(index_db_path) if index_db_path is not None else Path(storage_config.index_db_path)
    )
    vector_index_path = (
        Path(vector_index_path)
        if vector_index_path is not None
        else Path(storage_config.vector_index_path)
    )

    errors: dict[str, str] = {}

    # ── DB 侧：active 记忆 id 集（DB 是权威源）──
    db_ids: set[str] = set()
    try:
        result = await db.execute(select(Memory.id).where(Memory.status == "active"))
        db_ids = {str(mid) for mid in result.scalars().all()}
    except Exception as e:
        errors["db"] = f"failed to read memory table: {e}"

    # ── MD 侧：frontmatter 中 status 为 active 的记忆文件 ──
    md_ids: set[str] = set()
    if not memory_dir.exists():
        # FileStore 构造会 mkdir，为保持只读先判存在性，缺失直接报错
        errors["md"] = f"memory dir not found: {memory_dir}"
    else:
        try:
            # 文件 IO 放线程池，避免大目录扫描阻塞事件循环（与 sync_all 一致）
            memories = await asyncio.to_thread(FileStore(memory_dir).list)
            md_ids = {m.id for m in memories if m.status == "active"}
        except Exception as e:
            errors["md"] = f"failed to scan markdown files: {e}"

    # ── index 侧：index.db 中 status=active 的行 ──
    index_ids: set[str] = set()
    if not index_db_path.exists():
        # 先判存在性：常规 connect 会在缺失时静默建空库，违背只读约束
        errors["index"] = f"index.db not found: {index_db_path}"
    else:
        try:
            # 仅发 SELECT；不用 URI 只读模式，因为运行中的 WAL 库可能需要
            # 写 -shm 才能读，只读连接在热 WAL 场景下反而会打开失败
            async with aiosqlite.connect(index_db_path) as conn:
                cursor = await conn.execute("SELECT id, status FROM memory_index")
                rows = await cursor.fetchall()
            index_ids = {str(row[0]) for row in rows if row[1] == "active"}
        except Exception as e:
            errors["index"] = f"failed to read index.db: {e}"

    # ── vectors 侧：向量覆盖的记忆 id 集 ──
    vector_ids = _read_vector_ids(vector_index_path, errors)

    md_missing = sorted(db_ids - md_ids)
    md_orphan = sorted(md_ids - db_ids)
    index_missing = sorted(db_ids - index_ids)
    vectors_missing_all = sorted(db_ids - vector_ids)

    # 三方 id 集一致且向量全覆盖才健康；任一载体读取失败直接不健康
    healthy = not errors and db_ids == md_ids == index_ids and not vectors_missing_all

    logger.info(
        "一致性对账: healthy=%s db=%d md=%d index=%d vectors=%d",
        healthy,
        len(db_ids),
        len(md_ids),
        len(index_ids),
        len(vector_ids),
    )

    return ConsistencyReport(
        healthy=healthy,
        db_count=len(db_ids),
        md_count=len(md_ids),
        index_count=len(index_ids),
        vector_count=len(vector_ids),
        md_missing=md_missing,
        md_orphan=md_orphan,
        index_missing=index_missing,
        vectors_missing=vectors_missing_all[:MAX_LISTED_IDS],
        vectors_missing_total=len(vectors_missing_all),
        errors=errors,
    )


def _read_vector_ids(vector_index_path: Path, errors: dict[str, str]) -> set[str]:
    """读取向量索引覆盖的记忆 id 集，与 VectorIndex 的配对加载语义一致。

    npz 只存矩阵，id 与向量行的对应关系记录在伴随 JSON 中（见
    VectorIndex.save），两者必须配对存在且数量一致：数量不齐视为损坏
    （VectorIndex._load 同样按损坏丢弃）。两个文件皆缺视为尚未生成
    向量的全新索引（空集），只有一半存在才算损坏。
    """
    meta_path = vector_index_path.with_suffix(".json")
    if not vector_index_path.exists() and not meta_path.exists():
        return set()
    if not vector_index_path.exists() or not meta_path.exists():
        errors["vectors"] = "vector index broken: npz and json must exist together"
        return set()
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        ids = meta.get("ids", [])
        with np.load(vector_index_path) as data:
            row_count = len(data["vectors"])
        if len(ids) != row_count:
            errors["vectors"] = f"vector index corruption: {len(ids)} ids vs {row_count} vectors"
            return set()
        return {str(i) for i in ids}
    except Exception as e:
        errors["vectors"] = f"failed to read vector index: {e}"
        return set()
