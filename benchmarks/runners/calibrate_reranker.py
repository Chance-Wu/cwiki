"""重排权重离线标定。

在固定种子的 eval-fixture 上缓存每条查询的候选池，网格搜索相关性组权重
与 band，按 full_pipeline（含多样性）指标评估。默认把 20% 查询留出作
过拟合检查，只在留出不明显劣化时推荐配置。

该脚本只读数据库、只写报告，不修改 config.yaml。

用法：
    python -m benchmarks.runners.calibrate_reranker \
        --db-url sqlite+aiosqlite:///benchmarks/fixtures/eval_fixture.db \
        --workspace-name eval-fixture \
        --output benchmarks/reports/calibration.json
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select

from benchmarks.evaluators.retrieval import (
    QueryJudgment,
    QueryMetrics,
    RetrievalResult,
    aggregate_report,
    evaluate_query,
)
from benchmarks.runners.retrieval_runner import (
    DATASETS_DIR,
    load_gold_dataset,
    make_session_maker,
    prepare_query_candidates,
)
from packages.domain.models import Workspace
from packages.retrieval.bm25 import BM25Index
from packages.retrieval.ranking.diversity import apply_diversity
from packages.retrieval.ranking.reranker import RerankerWeights, RerankInput, rerank

logger = logging.getLogger(__name__)

TOP_K = 20
MAX_PER_TYPE = 3
HOLDOUT_EVERY = 5
HOLDOUT_MAX_NDCG_DROP = 0.005

RRF_VALUES = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
SEMANTIC_VALUES = [0.10, 0.20, 0.30, 0.40, 0.50]
BM25_VALUES = [0.00, 0.10, 0.20, 0.30, 0.40]
INTENT_VALUES = [0.05, 0.10, 0.15]
BAND_VALUES = [0.00, 0.02, 0.05, 0.08]


@dataclass
class CachedQuery:
    judgment: QueryJudgment
    intent: str
    intent_confidence: float
    negations: list[str]
    key_terms: list[str]
    inputs: list[RerankInput]
    types: dict[str, str]


def _metrics(
    cache: list[CachedQuery],
    indices: list[int],
    ranking_fn,
    pipeline: str,
) -> dict[str, float]:
    metrics: list[QueryMetrics] = []
    for idx in indices:
        item = cache[idx]
        ranked = ranking_fn(item)
        metrics.append(
            evaluate_query(
                RetrievalResult(query_id=item.judgment.query_id, ranked_memory_ids=ranked),
                item.judgment,
            )
        )
    report = aggregate_report(pipeline, metrics)
    return {
        "recall_at_10": round(report.recall_at_10, 4),
        "mrr": round(report.mrr, 4),
        "ndcg_at_10": round(report.ndcg_at_10, 4),
        "useful_at_10": round(report.useful_at_10, 4),
        "useful_at_10_ratio": round(report.useful_at_10_ratio, 4),
    }


def _rerank_ranking(weights: RerankerWeights):
    def ranking(item: CachedQuery) -> list[str]:
        reranked = rerank(
            item.inputs,
            query_intent=item.intent,
            intent_confidence=item.intent_confidence,
            negations=item.negations,
            key_terms=item.key_terms,
            weights=weights,
            top_k=TOP_K * 2,
        )
        with_type = [
            (mem_id, score, item.types[mem_id])
            for mem_id, score in reranked
            if mem_id in item.types
        ]
        diverse = apply_diversity(with_type, top_k=TOP_K, max_per_type=MAX_PER_TYPE)
        return [mem_id for mem_id, _, _ in diverse]

    return ranking


def _rrf_ranking(item: CachedQuery) -> list[str]:
    ordered = sorted(item.inputs, key=lambda c: c.rrf_score, reverse=True)
    return [c.memory_id for c in ordered[:TOP_K]]


def _split(cache: list[CachedQuery]) -> tuple[list[int], list[int]]:
    ordered = sorted(range(len(cache)), key=lambda i: cache[i].judgment.query_id)
    holdout = [i for pos, i in enumerate(ordered) if pos % HOLDOUT_EVERY == 0]
    holdout_set = set(holdout)
    train = [i for i in ordered if i not in holdout_set]
    return train, holdout


def _weights(
    base: RerankerWeights, rrf: float, semantic: float, bm25: float, intent: float, band: float
) -> RerankerWeights:
    return RerankerWeights(
        rrf=rrf,
        semantic=semantic,
        confidence=base.confidence,
        importance=base.importance,
        freshness=base.freshness,
        usage=base.usage,
        intent=intent,
        bm25=bm25,
        band=band,
        key_term_bonus=base.key_term_bonus,
    )


async def run_calibration(workspace_name: str, db_url: str | None, dataset: Path | None) -> dict:
    dataset_path = dataset or DATASETS_DIR / "retrieval" / f"{workspace_name}.jsonl"
    judgments = load_gold_dataset(dataset_path)
    if not judgments:
        raise SystemExit(f"No judgments loaded from {dataset_path}")

    session_maker = (
        make_session_maker(db_url)
        if db_url
        else make_session_maker(
            f"sqlite+aiosqlite:///{DATASETS_DIR.parent / 'fixtures' / 'eval_fixture.db'}"
        )
    )
    async with session_maker() as db:
        ws = (
            await db.execute(select(Workspace).where(Workspace.name == workspace_name))
        ).scalar_one_or_none()
        if ws is None:
            raise SystemExit(f"Workspace not found: {workspace_name}")
        from packages.domain.models import Memory

        rows = (
            (
                await db.execute(
                    select(Memory).where(Memory.status == "active", Memory.workspace_id == ws.id)
                )
            )
            .scalars()
            .all()
        )
        memories = list(rows)
        bm25_index = BM25Index()
        for memory in memories:
            bm25_index.add(str(memory.id), memory.content, title=memory.title)
        bm25_index.build()

        cache: list[CachedQuery] = []
        for judgment in judgments:
            analyzed, inputs, _ = await prepare_query_candidates(
                judgment.query,
                ws.id,
                bm25_index,
                memories,
                db,
                max_items=TOP_K,
            )
            cache.append(
                CachedQuery(
                    judgment=judgment,
                    intent=analyzed.intent,
                    intent_confidence=analyzed.confidence,
                    negations=analyzed.negations,
                    key_terms=analyzed.key_terms,
                    inputs=inputs,
                    types={c.memory_id: c.memory_type for c in inputs},
                )
            )

    train, holdout = _split(cache)
    all_indices = list(range(len(cache)))
    base = RerankerWeights.from_settings()
    default_rerank = _weights(base, base.rrf, base.semantic, base.bm25, base.intent, base.band)

    defaults = {
        "default_rerank": {
            "weights": asdict(default_rerank),
            "train": _metrics(cache, train, _rerank_ranking(default_rerank), "default_rerank"),
            "holdout": _metrics(cache, holdout, _rerank_ranking(default_rerank), "default_rerank"),
            "full": _metrics(cache, all_indices, _rerank_ranking(default_rerank), "default_rerank"),
        },
        "hybrid_rrf": {
            "train": _metrics(cache, train, _rrf_ranking, "hybrid_rrf"),
            "holdout": _metrics(cache, holdout, _rrf_ranking, "hybrid_rrf"),
            "full": _metrics(cache, all_indices, _rrf_ranking, "hybrid_rrf"),
        },
    }

    candidates: list[dict] = []
    for rrf_w, sem_w, bm25_w, intent_w, band in itertools.product(
        RRF_VALUES, SEMANTIC_VALUES, BM25_VALUES, INTENT_VALUES, BAND_VALUES
    ):
        weights = _weights(base, rrf_w, sem_w, bm25_w, intent_w, band)
        ranking = _rerank_ranking(weights)
        train_metrics = _metrics(cache, train, ranking, "candidate")
        holdout_metrics = _metrics(cache, holdout, ranking, "candidate")
        candidates.append(
            {
                "weights": {
                    "reranker_rrf_weight": rrf_w,
                    "reranker_semantic_weight": sem_w,
                    "reranker_bm25_weight": bm25_w,
                    "reranker_intent_weight": intent_w,
                    "reranker_relevance_band": band,
                },
                "train": train_metrics,
                "holdout": holdout_metrics,
            }
        )

    default_holdout_ndcg = defaults["default_rerank"]["holdout"]["ndcg_at_10"]
    candidates.sort(
        key=lambda c: (
            c["train"]["ndcg_at_10"],
            c["train"]["mrr"],
            c["holdout"]["ndcg_at_10"],
        ),
        reverse=True,
    )
    stable = [
        c
        for c in candidates
        if c["holdout"]["ndcg_at_10"] >= default_holdout_ndcg - HOLDOUT_MAX_NDCG_DROP
    ]
    recommended = (stable or candidates)[0]
    recommended_weights = _weights(
        base,
        recommended["weights"]["reranker_rrf_weight"],
        recommended["weights"]["reranker_semantic_weight"],
        recommended["weights"]["reranker_bm25_weight"],
        recommended["weights"]["reranker_intent_weight"],
        recommended["weights"]["reranker_relevance_band"],
    )
    recommended["full"] = _metrics(
        cache,
        all_indices,
        _rerank_ranking(recommended_weights),
        "recommended",
    )

    return {
        "dataset": str(dataset_path),
        "workspace": workspace_name,
        "queries": len(cache),
        "train_queries": len(train),
        "holdout_queries": len(holdout),
        "search_space": {
            "rrf": RRF_VALUES,
            "semantic": SEMANTIC_VALUES,
            "bm25": BM25_VALUES,
            "intent": INTENT_VALUES,
            "band": BAND_VALUES,
        },
        "defaults": defaults,
        "recommended": recommended,
        "top": candidates[:10],
        "holdout_rule": f"holdout ndcg >= default - {HOLDOUT_MAX_NDCG_DROP}",
    }


def _yaml_snippet(weights: dict[str, float]) -> str:
    return "\n".join(f"  {key}: {value:.2f}" for key, value in weights.items())


async def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate reranker weights on eval-fixture")
    parser.add_argument("--workspace-name", default="eval-fixture")
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/reports/calibration.json"),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    result = await run_calibration(args.workspace_name, args.db_url, args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {k: result[k] for k in ("defaults", "recommended", "holdout_rule")},
            indent=2,
            ensure_ascii=False,
        )
    )
    print("\n# recommended retrieval config")
    print(_yaml_snippet(result["recommended"]["weights"]))


if __name__ == "__main__":
    asyncio.run(main())
