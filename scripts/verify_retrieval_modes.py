"""验证文本、语义、混合三种检索模式的有效性。

测试矩阵:
  1. /api/v1/search           — 文本检索（BM25 + 向量 RRF 融合）
  2. /api/v1/file-memories/search/semantic — 语义检索（纯向量余弦）
  3. /api/v1/context mode=semantic  — 语义上下文管线（BM25 + 向量 + 重排 + 压缩）
  4. /api/v1/context mode=hybrid    — 混合管线（语义 + 情景合并）

验证维度:
  - 精确关键词匹配（文本应优）
  - 语义近义查询（语义应优）
  - 混合查询（两者互补）
  - 延迟与返回结构
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import httpx

BASE = "http://127.0.0.1:5172"
API = f"{BASE}/v1"
WORKSPACE_ID = "c458fc96-3133-4c6e-8bf0-6a9c975cae01"  # cwiki
AGENT_ID = "00000000-0000-0000-0000-000000000000"
SESSION_ID = str(uuid.uuid4())

# ── 测试用例 ──────────────────────────────────────────────


@dataclass
class TestCase:
    name: str
    keyword: str
    expected_titles: list[str]  # 期望命中的记忆标题（部分匹配即可）
    category: str  # "keyword" | "semantic" | "mixed"


TEST_CASES = [
    # 精确关键词：BM25 应占优
    TestCase(
        "精确关键词: BM25", "BM25 算法 公式", ["BM25 算法详解", "自定义 BM25 替换"], "keyword"
    ),
    TestCase("精确关键词: SQLite WAL", "SQLite WAL 模式", ["SQLite WAL 模式详解"], "keyword"),
    TestCase(
        "精确关键词: embedding 双写", "embedding 双写架构", ["cwiki embedding 双写架构"], "keyword"
    ),
    # 语义近义：向量应占优
    TestCase(
        "语义近义: 数据库并发控制", "数据库并发读写怎么处理", ["SQLite WAL 模式详解"], "semantic"
    ),
    TestCase(
        "语义近义: 搜索排序算法",
        "文档检索和排序用什么算法好",
        ["BM25 算法详解", "自定义 BM25 替换"],
        "semantic",
    ),
    TestCase(
        "语义近义: 远程调用失败重试", "网络请求超时了怎么自动重试", ["异步任务重试"], "semantic"
    ),
    # 混合：两者互补
    TestCase(
        "混合: embedding 可用性",
        "embedding 模型加载失败怎么办",
        ["cwiki 本地 embedding 模型可用性验证", "cwiki embedding 双写架构"],
        "mixed",
    ),
    TestCase(
        "混合: 搜索改进决策",
        "为什么要自己实现搜索算法",
        ["自定义 BM25 替换", "BM25 算法详解"],
        "mixed",
    ),
]


# ── API 调用 ──────────────────────────────────────────────

client = httpx.Client(timeout=30)


def search_hybrid(keyword: str, limit: int = 10) -> dict:
    """文本检索（BM25 + 向量 RRF 融合）"""
    r = client.post(
        f"{API}/search",
        json={
            "keyword": keyword,
            "workspace_id": WORKSPACE_ID,
            "limit": limit,
        },
    )
    r.raise_for_status()
    return r.json()


def search_semantic(keyword: str, limit: int = 10) -> dict:
    """语义检索（纯向量余弦）"""
    r = client.post(
        f"{API}/file-memories/search/semantic",
        json={
            "keyword": keyword,
            "workspace_id": WORKSPACE_ID,
            "limit": limit,
        },
    )
    r.raise_for_status()
    return r.json()


def context_retrieve(keyword: str, mode: str = "semantic", max_items: int = 10) -> dict:
    """上下文管线检索"""
    r = client.post(
        f"{API}/context",
        json={
            "keyword": keyword,
            "workspace_id": WORKSPACE_ID,
            "agent_id": AGENT_ID,
            "session_id": SESSION_ID,
            "mode": mode,
            "max_items": max_items,
        },
    )
    r.raise_for_status()
    return r.json()


# ── 评估 ──────────────────────────────────────────────────


@dataclass
class ModeResult:
    mode: str
    hits: int = 0
    total: int = 0
    latency_ms: float = 0
    details: list[dict] = field(default_factory=list)


def check_hits(results: list[dict], expected: list[str]) -> int:
    """检查结果中命中了多少期望标题（子串匹配）"""
    hit = 0
    for exp in expected:
        for r in results:
            title = r.get("title", "")
            if exp in title or title in exp:
                hit += 1
                break
    return hit


def run_all() -> dict[str, ModeResult]:
    modes = {
        "hybrid_search": ModeResult("hybrid_search"),  # /search
        "semantic_file": ModeResult("semantic_file"),  # /file-memories/search/semantic
        "context_semantic": ModeResult("context_semantic"),  # /context mode=semantic
        "context_hybrid": ModeResult("context_hybrid"),  # /context mode=hybrid
    }

    for tc in TEST_CASES:
        print(f"\n{'=' * 60}")
        print(f"测试: {tc.name}  [{tc.category}]")
        print(f"查询: '{tc.keyword}'")
        print(f"期望: {tc.expected_titles}")

        # 1. /search（混合：BM25 + 向量 RRF）
        t0 = time.perf_counter()
        try:
            r1 = search_hybrid(tc.keyword)
            lat1 = (time.perf_counter() - t0) * 1000
            items1 = r1.get("results", [])
            hits1 = check_hits(items1, tc.expected_titles)
            modes["hybrid_search"].hits += hits1
            modes["hybrid_search"].total += len(tc.expected_titles)
            modes["hybrid_search"].latency_ms += lat1
            top_titles1 = [
                f"  {i['title'][:40]}  score={i.get('score', 'N/A')}" for i in items1[:5]
            ]
            modes["hybrid_search"].details.append(
                {
                    "test": tc.name,
                    "hits": hits1,
                    "expected": len(tc.expected_titles),
                    "latency_ms": round(lat1, 1),
                    "top": top_titles1,
                }
            )
        except Exception as e:
            lat1 = (time.perf_counter() - t0) * 1000
            modes["hybrid_search"].details.append({"test": tc.name, "error": str(e)})
            items1, hits1 = [], 0

        # 2. /file-memories/search/semantic（纯向量）
        t0 = time.perf_counter()
        try:
            r2 = search_semantic(tc.keyword)
            lat2 = (time.perf_counter() - t0) * 1000
            items2 = r2.get("results", [])
            hits2 = check_hits(items2, tc.expected_titles)
            modes["semantic_file"].hits += hits2
            modes["semantic_file"].total += len(tc.expected_titles)
            modes["semantic_file"].latency_ms += lat2
            top_titles2 = [
                f"  {i['title'][:40]}  score={i.get('score', 'N/A')}" for i in items2[:5]
            ]
            modes["semantic_file"].details.append(
                {
                    "test": tc.name,
                    "hits": hits2,
                    "expected": len(tc.expected_titles),
                    "latency_ms": round(lat2, 1),
                    "top": top_titles2,
                }
            )
        except Exception as e:
            lat2 = (time.perf_counter() - t0) * 1000
            modes["semantic_file"].details.append({"test": tc.name, "error": str(e)})
            items2, hits2 = [], 0

        # 3. /context mode=semantic
        t0 = time.perf_counter()
        try:
            r3 = context_retrieve(tc.keyword, mode="semantic")
            lat3 = (time.perf_counter() - t0) * 1000
            items3 = r3.get("items", [])
            hits3 = check_hits(items3, tc.expected_titles)
            modes["context_semantic"].hits += hits3
            modes["context_semantic"].total += len(tc.expected_titles)
            modes["context_semantic"].latency_ms += lat3
            top_titles3 = [
                f"  {i['title'][:40]}  score={i.get('score', 'N/A')}" for i in items3[:5]
            ]
            modes["context_semantic"].details.append(
                {
                    "test": tc.name,
                    "hits": hits3,
                    "expected": len(tc.expected_titles),
                    "latency_ms": round(lat3, 1),
                    "top": top_titles3,
                    "context_len": len(r3.get("context", "")),
                }
            )
        except Exception as e:
            lat3 = (time.perf_counter() - t0) * 1000
            modes["context_semantic"].details.append({"test": tc.name, "error": str(e)})
            items3, hits3 = [], 0

        # 4. /context mode=hybrid
        t0 = time.perf_counter()
        try:
            r4 = context_retrieve(tc.keyword, mode="hybrid")
            lat4 = (time.perf_counter() - t0) * 1000
            items4 = r4.get("items", [])
            hits4 = check_hits(items4, tc.expected_titles)
            modes["context_hybrid"].hits += hits4
            modes["context_hybrid"].total += len(tc.expected_titles)
            modes["context_hybrid"].latency_ms += lat4
            top_titles4 = [
                f"  {i['title'][:40]}  score={i.get('score', 'N/A')}" for i in items4[:5]
            ]
            modes["context_hybrid"].details.append(
                {
                    "test": tc.name,
                    "hits": hits4,
                    "expected": len(tc.expected_titles),
                    "latency_ms": round(lat4, 1),
                    "top": top_titles4,
                }
            )
        except Exception as e:
            lat4 = (time.perf_counter() - t0) * 1000
            modes["context_hybrid"].details.append({"test": tc.name, "error": str(e)})
            items4, hits4 = [], 0

        # 打印单条结果
        for mode_key, label, hits, items in [
            ("hybrid_search", "文本检索(/search)", hits1, items1),
            ("semantic_file", "语义检索(/semantic)", hits2, items2),
            ("context_semantic", "上下文语义(/context:semantic)", hits3, items3),
            ("context_hybrid", "上下文混合(/context:hybrid)", hits4, items4),
        ]:
            exp_count = len(tc.expected_titles)
            status = "PASS" if hits == exp_count else ("PARTIAL" if hits > 0 else "MISS")
            print(
                f"  {label:35s}  hits={hits}/{exp_count}  [{status}]  top={items[0]['title'][:35] if items else 'NONE'}"
            )

    return modes


# ── 汇总报告 ──────────────────────────────────────────────


def print_report(modes: dict[str, ModeResult]) -> None:
    print("\n" + "=" * 70)
    print("检索模式验证汇总报告")
    print("=" * 70)

    total_tests = len(TEST_CASES)
    for key, m in modes.items():
        recall = m.hits / m.total * 100 if m.total > 0 else 0
        avg_lat = m.latency_ms / total_tests
        error_count = sum(1 for d in m.details if "error" in d)
        print(f"\n{'─' * 50}")
        print(f"模式: {key}")
        print(f"  召回率: {m.hits}/{m.total} ({recall:.1f}%)")
        print(f"  平均延迟: {avg_lat:.1f} ms")
        print(f"  错误数: {error_count}/{total_tests}")

        # 按类别统计
        for cat in ["keyword", "semantic", "mixed"]:
            cat_details = [
                d
                for d in m.details
                if any(tc.name == d.get("test") for tc in TEST_CASES if tc.category == cat)
            ]
            if cat_details:
                cat_hits = sum(d.get("hits", 0) for d in cat_details)
                cat_total = sum(d.get("expected", 0) for d in cat_details)
                cat_recall = cat_hits / cat_total * 100 if cat_total > 0 else 0
                print(f"  {cat:10s}: {cat_hits}/{cat_total} ({cat_recall:.0f}%)")

    # 最终判定
    print(f"\n{'=' * 70}")
    print("判定标准:")
    print("  - 每种模式召回率 > 50% → 有效")
    print("  - 关键词查询文本检索应优于纯语义")
    print("  - 语义查询向量检索应优于纯文本")
    print("  - 混合查询两者互补")
    print("=" * 70)


if __name__ == "__main__":
    modes = run_all()
    print_report(modes)
