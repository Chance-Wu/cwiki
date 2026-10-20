"""导出待标注的评测查询文件。

从 retrieval_trace 聚合真实查询（按 workspace 去重），对每条查询跑
BM25 + 向量双路召回取并集作为候选池，导出 JSONL 待标注文件：

    {"query": "...", "workspace": "cwiki", "candidates": [{"memory_id": "...",
     "title": "...", "score": 0.83, "source": "bm25|vector|both"}, ...]}

人工标注后按黄金数据集格式（query_id/query/memory_id/relevance）落盘到
benchmarks/datasets/retrieval/{workspace}.jsonl。

用法：
    python scripts/export_eval_queries.py --workspace cwiki --output /tmp/labeling.jsonl
    python scripts/export_eval_queries.py --all-workspaces
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.database import async_session_maker
from packages.domain.models import Memory, Workspace
from packages.retrieval.bm25 import BM25Index
from packages.retrieval.embedding import get_embedding_service

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MIN_QUERY_LEN = 4  # 过短查询（如单词命令）标注价值低，跳过
TOP_K = 20


def _quiet_sql() -> None:
    # settings.debug=true 时共享引擎带 echo，SQL 会直接打到日志；本工具只需结果
    for name in ("sqlalchemy.engine", "sqlalchemy.engine.Engine"):
        logging.getLogger(name).disabled = True
    # jieba 首次分词会自行打开 DEBUG 日志，与导出结果无关
    logging.getLogger("jieba").setLevel(logging.WARNING)


async def _real_queries(db: AsyncSession, workspace_id) -> list[str]:
    """聚合该 workspace 的真实检索查询（按精确文本去重，按频次排序）。"""
    from packages.domain.models.retrieval import RetrievalTrace

    rows = (
        await db.execute(
            select(RetrievalTrace.keyword, RetrievalTrace.created_at).where(
                RetrievalTrace.workspace_id == workspace_id
            )
        )
    ).all()
    counts: dict[str, int] = defaultdict(int)
    for query, _ in rows:
        q = (query or "").strip()
        if len(q) >= MIN_QUERY_LEN:
            counts[q] += 1
    return [q for q, _ in sorted(counts.items(), key=lambda x: -x[1])]


async def _candidate_pool(
    db: AsyncSession, queries: list[str], workspace_id
) -> dict[str, list[dict]]:
    """对每条查询取 BM25 与向量召回的并集（附得分与命中来源）。"""
    memories = (
        (
            await db.execute(
                select(Memory).where(Memory.status == "active", Memory.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    if not memories:
        return {}

    index = BM25Index()
    for m in memories:
        index.add(str(m.id), m.content, title=m.title)
    index.build()

    embedding_svc = get_embedding_service()

    import numpy as np

    mem_embeddings = {
        str(m.id): np.array(m.embedding, dtype=np.float32) for m in memories if m.embedding
    }
    title_by_id = {str(m.id): m.title for m in memories}

    pools: dict[str, list[dict]] = {}
    for query in queries:
        bm25_hits = dict(index.search(query, top_k=TOP_K))
        vector_hits: dict[str, float] = {}
        if mem_embeddings:
            q_vec = await embedding_svc.generate_embedding(query)
            if q_vec is not None:
                q = np.array(q_vec, dtype=np.float32)
                q_norm = np.linalg.norm(q)
                if q_norm > 0:
                    for mid, e in mem_embeddings.items():
                        e_norm = np.linalg.norm(e)
                        if e_norm > 0:
                            vector_hits[mid] = float(np.dot(q, e) / (q_norm * e_norm))
        top_vector = dict(sorted(vector_hits.items(), key=lambda x: -x[1])[:TOP_K])

        all_ids = set(bm25_hits) | set(top_vector)
        candidates = []
        for mid in all_ids:
            sources = []
            if mid in bm25_hits and mid in top_vector:
                sources = "both"
            elif mid in bm25_hits:
                sources = "bm25"
            else:
                sources = "vector"
            candidates.append(
                {
                    "memory_id": mid,
                    "title": title_by_id.get(mid, "?"),
                    "bm25_score": round(bm25_hits.get(mid, 0.0), 4),
                    "vector_score": round(top_vector.get(mid, 0.0), 4),
                    "source": sources,
                }
            )
        candidates.sort(key=lambda c: -(c["bm25_score"] + c["vector_score"]))
        pools[query] = candidates
    return pools


def _write_export(
    output: Path, queries: list[str], pools: dict[str, list[dict]], workspace_name: str
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.writelines(
            json.dumps(
                {
                    "query": query,
                    "workspace": workspace_name,
                    "candidates": pools.get(query, []),
                },
                ensure_ascii=False,
            )
            + "\n"
            for query in queries
        )


async def export_workspace(workspace_name: str, output: Path) -> int:
    async with async_session_maker() as db:
        ws = (
            await db.execute(select(Workspace).where(Workspace.name == workspace_name))
        ).scalar_one_or_none()
        if ws is None:
            logger.error("Workspace '%s' not found", workspace_name)
            return 1
        queries = await _real_queries(db, ws.id)
        if not queries:
            logger.warning("No real queries in trace for workspace '%s'", workspace_name)
            return 0
        pools = await _candidate_pool(db, queries, ws.id)

    _write_export(output, queries, pools, workspace_name)
    logger.info("Exported %d queries to %s", len(queries), output)
    return 0


async def main(workspace: str | None, output: Path | None, all_workspaces: bool) -> None:
    _quiet_sql()
    if all_workspaces:
        async with async_session_maker() as db:
            names = (await db.execute(select(Workspace.name))).scalars().all()
        # 固定落在项目内，避免结果随当前工作目录漂移
        out_dir = ROOT / "benchmarks" / "labeling"
        for name in sorted(names):
            await export_workspace(name, out_dir / f"{name}.jsonl")
        return
    if not workspace:
        raise SystemExit("--workspace 或 --all-workspaces 必须提供一个")
    await export_workspace(workspace, output or Path(f"/tmp/labeling-{workspace}.jsonl"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出待标注评测查询")
    parser.add_argument("--workspace", type=str, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--all-workspaces", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(args.workspace, args.output, args.all_workspaces))
