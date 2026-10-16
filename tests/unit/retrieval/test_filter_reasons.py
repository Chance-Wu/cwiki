"""检索可解释性测试：逐条过滤原因（filter_reasons）与 trace 信号分项落库。

覆盖三块：
1. 上下文组装流水线（同步/异步）各阶段的 filter_reasons 记录——
   dedup（duplicate_of）、diversity（max_per_type）、merge（merged_into）、
   compress（content_trimmed）、degrade（degraded_to_summary/title）、
   格式化截断（truncated/over_budget）；
2. explain_enabled 开关语义：组装器始终在内存收集过滤原因（纯函数，
   不读配置），开关只控制 _record_trace 是否把 signals + filter_reasons
   写入 RetrievalTrace.metadata_（JSON 列，零迁移）；
3. retrieve() 完整管线把 bm25/vector/rerank 信号分项注入 final_memories。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.config import settings
from packages.domain.database import Base
from packages.domain.models import Memory, RetrievalTrace, Workspace
from packages.retrieval.context.assembler import (
    assemble_context,
    assemble_context_with_embedding,
)
from packages.retrieval.context.dedup import deduplicate_with_details
from packages.retrieval.engine import RetrievalEngine
from packages.retrieval.query.analyzer import analyze_query


def _stage_reason_map(result) -> dict[tuple[str, str], str]:
    """把 filter_reasons 转成 {(stage, memory_id): reason}，便于逐条断言。"""
    return {(r.stage, r.memory_id): r.reason for r in result.filter_reasons}


class TestFilterReasonStages:
    """组装流水线各过滤阶段的 filter_reasons 覆盖。"""

    def _stage_input(self) -> list[dict]:
        """构造一次性触发 dedup / diversity / merge 三阶段的多记忆输入。

        d1/d2 内容相同触发去重；v1/v2 同为 fact 且 max_per_type=1 触发
        多样性过滤；m1/m2/m3 内容互不重复（躲过去重）、类型互不相同
        （躲过多样性过滤）但 embedding 完全一致，长内容被 L1 裁剪到
        125 token 后三条合计仍超过 L3 触发线（0.6 × 500 = 300），触发相似合并。
        """
        return [
            {
                "id": "d1",
                "type": "lesson",
                "content": "use SQLite for persistence",
                "score": 0.9,
            },
            {
                "id": "d2",
                "type": "lesson",
                "content": "use SQLite for persistence",
                "score": 0.7,
            },
            {
                "id": "v1",
                "type": "fact",
                "content": "alpha topic about caching layers",
                "score": 0.9,
            },
            {
                "id": "v2",
                "type": "fact",
                "content": "beta topic about storage engines",
                "score": 0.8,
            },
            {
                "id": "m1",
                "type": "reference",
                "content": "alpha beta gamma " * 50,
                "score": 0.9,
                "embedding": [1.0, 0.0, 0.0],
            },
            {
                "id": "m2",
                "type": "procedure",
                "content": "delta epsilon zeta " * 50,
                "score": 0.8,
                "embedding": [1.0, 0.0, 0.0],
            },
            {
                "id": "m3",
                "type": "pattern",
                "content": "eta theta iota " * 50,
                "score": 0.7,
                "embedding": [1.0, 0.0, 0.0],
            },
        ]

    def test_sync_pipeline_covers_dedup_diversity_merge(self):
        result = assemble_context(self._stage_input(), max_tokens=500, max_per_type=1)

        reasons = _stage_reason_map(result)
        assert reasons[("dedup", "d2")] == "duplicate_of:d1"
        assert reasons[("diversity", "v2")] == "max_per_type:fact"
        # m2/m3 被并入组内得分最高的 m1
        assert reasons[("merge", "m2")] == "merged_into:m1"
        assert reasons[("merge", "m3")] == "merged_into:m1"
        # 合并后的代表条目与幸存条目不在过滤记录里
        survivor_ids = {m.memory_id for m in result.memories}
        assert not survivor_ids & {"d2", "v2", "m2", "m3"}

    async def test_async_pipeline_covers_dedup_diversity_merge(self):
        # query 传空串避免触发 embedding 重排（零模型调用），其余流水线一致
        result = await assemble_context_with_embedding(
            self._stage_input(), query="", max_tokens=500, max_per_type=1
        )

        reasons = _stage_reason_map(result)
        assert reasons[("dedup", "d2")] == "duplicate_of:d1"
        assert reasons[("diversity", "v2")] == "max_per_type:fact"
        assert reasons[("merge", "m2")] == "merged_into:m1"
        assert reasons[("merge", "m3")] == "merged_into:m1"

    def test_compress_stage_recorded(self):
        # 单条内容超 L1 上限（500×0.25=125 token）：条目保留但正文被裁，
        # 记 compress/content_trimmed；总量低于 L3 触发线，不应有 merge 记录
        memories = [
            {"id": "c1", "type": "fact", "content": "x" * 600, "score": 0.9},
        ]
        result = assemble_context(memories, max_tokens=500)

        reasons = _stage_reason_map(result)
        assert reasons[("compress", "c1")] == "content_trimmed"
        # 被压缩的条目仍在上下文里——compress 是"改写"不是"移除"
        assert "c1" in {m.memory_id for m in result.memories}
        assert not [r for r in result.filter_reasons if r.stage == "merge"]

    def test_degrade_stage_recorded(self):
        # 8 条各 ~75 token（不触发 L1 压缩），合计 600 > 500 触发 L4 降级；
        # 内容无句界分隔符，摘要档省 0 token，直接落到"仅标题"档（level 2）。
        # 无 embedding 且内容互异 → L3 按内容哈希各自成簇，不产生合并
        memories = [
            {
                "id": f"g{i}",
                "type": "fact",
                "content": f"w{i} " * 100,
                "score": round(0.95 - i * 0.05, 2),
            }
            for i in range(8)
        ]
        # max_per_type 放宽：8 条同为 fact，否则多样性阶段先滤掉大部分条目
        result = assemble_context(memories, max_tokens=500, max_per_type=8)

        reasons = _stage_reason_map(result)
        # 降级从最低优先级（低分）开始：最后两条被降为仅标题
        assert reasons[("degrade", "g7")] == "degraded_to_title"
        assert reasons[("degrade", "g6")] == "degraded_to_title"
        assert not [
            r
            for r in result.filter_reasons
            if r.stage == "degrade" and r.memory_id in {"g0", "g1", "g2", "g3"}
        ]

    def test_truncated_stage_recorded(self):
        # title 不参与 L1 cap 与 L4 降级的 token 计算，但计入格式化条目——
        # 用超长标题稳定制造"降级后仍放不下"的预算截断场景；
        # content 用零重叠词，避免先被去重吞掉
        memories = [
            {"id": "t0", "type": "fact", "title": "T" * 800, "content": "caching", "score": 0.9},
            {"id": "t1", "type": "fact", "title": "T" * 800, "content": "database", "score": 0.8},
            {"id": "t2", "type": "fact", "title": "T" * 800, "content": "network", "score": 0.7},
        ]
        result = assemble_context(memories, max_tokens=500)

        assert result.truncated is True
        assert len(result.memories) == 2
        truncated = [r for r in result.filter_reasons if r.stage == "truncated"]
        assert [(r.memory_id, r.reason) for r in truncated] == [("t2", "over_budget")]

    def test_relevance_floor_stage_recorded(self, monkeypatch):
        # 入口三档过滤（relevance_floor hard 档）：低分候选在流水线最前端
        # 被剔除并记录 relevance_floor 阶段原因，后续去重/多样性都看不到它
        monkeypatch.setattr(settings, "relevance_floor_mode", "hard")
        monkeypatch.setattr(settings, "relevance_floor", 0.6)
        memories = [
            {"id": "keep", "type": "fact", "content": "alpha", "score": 0.8},
            {"id": "low", "type": "fact", "content": "beta", "score": 0.3},
        ]

        result = assemble_context(memories, max_tokens=2000)

        reasons = _stage_reason_map(result)
        assert reasons[("relevance_floor", "low")] == "below_relevance_floor"
        assert {m.memory_id for m in result.memories} == {"keep"}

    def test_stages_without_drops_leave_no_reasons(self):
        # 无重复、类型不超限、预算充裕时不应产生任何过滤记录
        memories = [
            {"id": "a", "type": "fact", "content": "alpha", "score": 0.9},
            {"id": "b", "type": "lesson", "content": "omega", "score": 0.8},
        ]
        result = assemble_context(memories, max_tokens=2000)
        assert result.filter_reasons == []

    def test_empty_input_has_empty_filter_reasons(self):
        result = assemble_context([])
        assert result.filter_reasons == []
        assert result.to_dict()["filter_reasons"] == []

    def test_filter_reasons_in_to_dict(self):
        # asdict 递归把 FilterReason 转成 dict，保证 JSON 可序列化
        memories = [
            {"id": "k", "content": "use SQLite for persistence", "score": 0.9},
            {"id": "x", "content": "use SQLite for persistence", "score": 0.7},
        ]
        result = assemble_context(memories)
        d = result.to_dict()
        assert {"memory_id": "x", "stage": "dedup", "reason": "duplicate_of:k"} in d[
            "filter_reasons"
        ]


class TestDedupDetails:
    """deduplicate_with_details 明细变体与原函数行为一致性。"""

    def test_details_carry_dedup_target(self):
        memories = [
            {"id": "keep", "content": "use SQLite for persistence", "score": 0.9},
            {"id": "drop", "content": "use SQLite for persistence", "score": 0.7},
        ]
        kept, details = deduplicate_with_details(memories)
        assert [m["id"] for m in kept] == ["keep"]
        assert details == [("drop", "keep")]

    def test_empty_input(self):
        assert deduplicate_with_details([]) == ([], [])


class _StubEmbedding:
    """零模型调用的 embedding 桩：固定二维向量，让 retrieve() 走纯内存路径。"""

    async def generate_embedding(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
async def explain_env(tmp_path):
    """内存式 SQLite 环境：两条记忆 + 检索引擎，供 trace 落库断言。"""
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="explain")
        db.add(ws)
        await db.flush()
        a = Memory(
            workspace_id=ws.id,
            title="Probe alpha",
            content="retrieval probe alpha content",
            type="fact",
            embedding=[1.0, 0.0],
        )
        b = Memory(
            workspace_id=ws.id,
            title="Probe beta",
            content="another unrelated topic entirely",
            type="lesson",
            embedding=[0.0, 1.0],
        )
        db.add_all([a, b])
        await db.commit()
        yield SimpleNamespace(
            db=db,
            engine=RetrievalEngine(),
            workspace=ws,
            a_id=str(a.id),
            b_id=str(b.id),
        )
    await db_engine.dispose()


class TestTraceMetadata:
    """explain_enabled 开关下的 RetrievalTrace.metadata_ 落库行为。"""

    def _trace_call_args(self, env, ctx):
        return {
            "db": env.db,
            "workspace_id": env.workspace.id,
            "session_id": None,
            "query": "probe",
            "analyzed": analyze_query("probe"),
            "candidates": {
                env.a_id: {
                    "bm25_score": 1.5,
                    "vector_score": 0.8,
                    "bm25_rank": 1,
                    "vector_rank": 1,
                }
            },
            "final_memories": [
                {
                    "id": env.a_id,
                    "score": 0.9,
                    "bm25_score": 1.5,
                    "vector_score": 0.8,
                    "rrf_score": 0.016393,
                    "rerank_score": 0.9,
                    "utility_score": 0.145,
                }
            ],
            "latency_ms": 10,
            "ctx": ctx,
        }

    async def test_record_trace_writes_signals_and_filter_reasons(self, explain_env, monkeypatch):
        env = explain_env
        monkeypatch.setattr(settings, "explain_enabled", True)

        # 构造一条真实经过去重的 ctx：b 与 a 内容相同、分数更低，被记 duplicate_of
        ctx = assemble_context(
            [
                {"id": env.a_id, "type": "fact", "content": "same probe content", "score": 0.9},
                {"id": env.b_id, "type": "fact", "content": "same probe content", "score": 0.7},
            ],
            query="probe",
        )

        await env.engine._record_trace(**self._trace_call_args(env, ctx))

        trace = (await env.db.execute(select(RetrievalTrace))).scalar_one()
        metadata = trace.metadata_
        assert set(metadata) == {"signals", "filter_reasons"}
        # signals：按 memory_id 索引的五路信号分项
        assert metadata["signals"][env.a_id] == {
            "bm25": 1.5,
            "vector": 0.8,
            "rrf": 0.016393,
            "rerank": 0.9,
            "utility": 0.145,
        }
        # filter_reasons：逐条 dict（memory_id/stage/reason），细节字段完整
        assert {
            "memory_id": env.b_id,
            "stage": "dedup",
            "reason": f"duplicate_of:{env.a_id}",
        } in metadata["filter_reasons"]

    async def test_record_trace_skips_metadata_when_disabled(self, explain_env, monkeypatch):
        env = explain_env
        monkeypatch.setattr(settings, "explain_enabled", False)

        ctx = assemble_context(
            [
                {"id": env.a_id, "type": "fact", "content": "same probe content", "score": 0.9},
                {"id": env.b_id, "type": "fact", "content": "same probe content", "score": 0.7},
            ],
            query="probe",
        )

        await env.engine._record_trace(**self._trace_call_args(env, ctx))

        trace = (await env.db.execute(select(RetrievalTrace))).scalar_one()
        assert trace.metadata_ is None

    async def test_retrieve_injects_signal_fields_and_trace_metadata(
        self, explain_env, monkeypatch
    ):
        """完整检索管线：final_memories 携带信号分项，trace 落库同源分数。"""
        env = explain_env
        monkeypatch.setattr(settings, "explain_enabled", True)
        # 桩掉 engine 与 assembler 两处 embedding 服务，避免触发本地模型加载
        monkeypatch.setattr(
            "packages.retrieval.engine.get_embedding_service", lambda: _StubEmbedding()
        )
        monkeypatch.setattr(
            "packages.retrieval.context.assembler.get_embedding_service", lambda: _StubEmbedding()
        )

        result = await env.engine.retrieve(
            "retrieval probe alpha", env.workspace.id, env.db, max_items=5
        )

        by_id = {m["id"]: m for m in result["memories"]}
        assert env.a_id in by_id
        mem = by_id[env.a_id]
        assert mem["bm25_score"] > 0
        assert mem["vector_score"] > 0
        # rerank_score 即 diversity 元组里的 final score，与 score 同源
        assert mem["rerank_score"] == mem["score"]

        trace = (await env.db.execute(select(RetrievalTrace))).scalar_one()
        signals = trace.metadata_["signals"]
        assert set(signals[env.a_id]) == {"bm25", "vector", "rrf", "rerank", "utility"}
        assert signals[env.a_id]["bm25"] == pytest.approx(mem["bm25_score"])
        assert signals[env.a_id]["vector"] == pytest.approx(mem["vector_score"])
        assert signals[env.a_id]["rerank"] == pytest.approx(mem["rerank_score"])
        assert isinstance(trace.metadata_["filter_reasons"], list)
