"""并发探针：对运行中的 cwiki 服务并发发起检索，量化连接层并发能力。

用法（对运行中的服务）：
    python -m benchmarks.performance.concurrency_probe --concurrency 10 --rounds 3

输出每轮 N 路并发请求的总耗时与单请求 p50/p95。连接池化前，全部请求在
StaticPool 的单一连接上串行执行；池化后并发读应显著缩短总耗时。
只做只读检索，不影响数据。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:5172"


def _percentiles(samples: list[float]) -> dict[str, float]:
    def pct(p: float) -> float:
        if not samples:
            return 0.0
        ordered = sorted(samples)
        idx = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
        return round(ordered[idx] * 1000, 2)

    return {"p50_ms": pct(50), "p95_ms": pct(95), "p99_ms": pct(99)}


async def _resolve_workspace(base_url: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base_url}/v1/workspaces")
        resp.raise_for_status()
        items = resp.json().get("items", [])
        with_memories = [w for w in items if w.get("memory_count", 0) > 3]
        return (with_memories or items)[0]["id"]


async def _probe_round(
    client: httpx.AsyncClient,
    workspace_id: str,
    concurrency: int,
    query: str,
) -> dict[str, Any]:
    async def one() -> tuple[float, int]:
        t0 = time.perf_counter()
        resp = await client.post(
            f"{client.base_url}/v1/search",
            json={
                "workspace_id": workspace_id,
                "keyword": query,
                "mode": "hybrid",
                "limit": 5,
                "record_trace": False,
            },
        )
        elapsed = time.perf_counter() - t0
        return elapsed, resp.status_code

    start = time.perf_counter()
    results = await asyncio.gather(*(one() for _ in range(concurrency)))
    wall = time.perf_counter() - start
    latencies = [r[0] for r in results]
    statuses = {r[1] for r in results}
    return {
        "wall_s": round(wall, 3),
        "statuses": sorted(statuses),
        **_percentiles(latencies),
    }


async def run(base_url: str, concurrency: int, rounds: int, workspace_id: str | None) -> dict:
    ws = workspace_id or await _resolve_workspace(base_url)
    query = "合同 权限 校验"
    async with httpx.AsyncClient(timeout=30, base_url=base_url) as client:
        # 预热一轮（缓存/索引热态后再计时）
        await _probe_round(client, ws, min(concurrency, 4), query)
        rounds_report = [await _probe_round(client, ws, concurrency, query) for _ in range(rounds)]
    walls = [r["wall_s"] for r in rounds_report]
    return {
        "benchmark": "concurrency_probe",
        "base_url": base_url,
        "concurrency": concurrency,
        "rounds": rounds,
        "workspace_id": ws,
        "rounds_report": rounds_report,
        "wall_s_median": round(statistics.median(walls), 3),
        "p50_ms_median": round(statistics.median(r["p50_ms"] for r in rounds_report), 2),
        "p95_ms_median": round(statistics.median(r["p95_ms"] for r in rounds_report), 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Concurrent retrieval probe")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--output", default=None, help="JSON 结果输出路径（可选）")
    args = parser.parse_args()

    report = asyncio.run(run(args.base_url, args.concurrency, args.rounds, args.workspace_id))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
