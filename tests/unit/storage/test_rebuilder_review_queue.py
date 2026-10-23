"""DatabaseRebuilder 四表恢复测试：候选、审核留痕、版本、复习史。

覆盖数据丢失 bug 的修复：重建必须从 store 级 ``_meta/_review_queue.json``
恢复 candidate_memory 与 review，从每记忆 _meta 的 ``versions`` /
``review_history`` 键恢复 memory_version 与 review_history，并在导入前
清空四表中的旧行 —— 上一轮残留不跨重建泄漏。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from packages.domain.models import (
    Base,
    CandidateMemory,
    Memory,
    MemoryRelation,
    MemoryVersion,
    Review,
    ReviewHistory,
    Workspace,
)
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.meta_store import MetaStore
from packages.storage.rebuilder import DatabaseRebuilder

_WS_ID = "11111111-2222-3333-4444-555555555555"
_MEMORY_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_CAND_PENDING = "99999999-8888-7777-6666-555555555555"
_CAND_REJECTED = "99999999-8888-7777-6666-444444444444"
# 悬空引用：episode 表不随重建重灌，重建时该 id 无对应行
_EPISODE_ID = "66666666-6666-6666-6666-666666666666"
_REVIEW_OF_PENDING = "01010101-0101-0101-0101-010101010101"
_REVIEW_OF_REJECTED_1 = "02020202-0202-0202-0202-020202020202"
_REVIEW_OF_REJECTED_2 = "03030303-0303-0303-0303-030303030303"

# DB 的 DateTime 列为 naive 时间，统一经 fromisoformat 构造对比值
_DT_CREATED = datetime.fromisoformat("2026-01-01T00:00:00")
_DT_UPDATED = datetime.fromisoformat("2026-01-02T00:00:00")
_DT_REVIEW = datetime.fromisoformat("2026-01-02T01:00:00")
_DT_STALE = datetime.fromisoformat("2025-01-01T00:00:00")
_DT_STALE_NEXT = datetime.fromisoformat("2025-01-03T00:00:00")


def _make_rebuilder(tmp_path) -> DatabaseRebuilder:
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    return DatabaseRebuilder(db_url=db_url, data_dir=str(tmp_path / "data"))


async def _create_schema(rebuilder: DatabaseRebuilder) -> None:
    """先建 schema，避免 rebuild 走 Alembic 子进程路径。"""
    async with rebuilder._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _prepare_export(data_dir: Path) -> None:
    """构造完整导出物：MD 记忆 + _workspaces.json + _meta/{id}.json + _review_queue.json。"""
    file_store = FileStore(str(data_dir))
    file_store.save(
        MemoryFile(
            id=_MEMORY_ID,
            title="记忆标题",
            content="记忆内容",
            workspace="cwiki",
            created=_DT_CREATED,
            updated=_DT_UPDATED,
        ),
        workspace_name="cwiki",
    )

    meta_dir = data_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    MetaStore(meta_dir).export_workspaces(
        [{"name": "cwiki", "id": _WS_ID, "created_at": None, "updated_at": None}]
    )
    (meta_dir / f"{_MEMORY_ID}.json").write_text(
        json.dumps(_memory_meta(), ensure_ascii=False), encoding="utf-8"
    )
    (meta_dir / "_review_queue.json").write_text(
        json.dumps(_review_queue(), ensure_ascii=False), encoding="utf-8"
    )


def _memory_meta() -> dict[str, Any]:
    """每记忆 _meta：版本链（2 条）+ 复习事件史（1 条）。"""
    return {
        "feedback": [],
        "usage": [],
        "conflict": [],
        "review_schedule": {},
        "relation": [],
        "lifecycle_event": [],
        "evidence": [],
        "versions": [
            {
                "id": "12121212-1212-1212-1212-121212121212",
                "memory_id": _MEMORY_ID,
                "version": 1,
                "title": "初版标题",
                "content": "初版内容",
                "change_type": "created",
                "changed_by_type": "agent",
                "changed_by_id": "mcp",
                "reason": None,
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": "13131313-1313-1313-1313-131313131313",
                "memory_id": _MEMORY_ID,
                "version": 2,
                "title": "修订标题",
                "content": "修订内容",
                "change_type": "update",
                "changed_by_type": "human",
                "changed_by_id": "user",
                "reason": "修正表述",
                "created_at": "2026-01-02T00:00:00",
            },
        ],
        "review_history": [
            {
                "id": "14141414-1414-1414-1414-141414141414",
                "workspace_id": _WS_ID,
                "memory_id": _MEMORY_ID,
                "quality": 4,
                "ease_factor_before": 2.5,
                "interval_before": 1,
                "repetitions_before": 0,
                "next_review_before": "2026-01-01T00:00:00",
                "mastery_level_before": "new",
                "ease_factor_after": 2.6,
                "interval_after": 3,
                "repetitions_after": 1,
                "next_review_after": "2026-01-04T00:00:00",
                "mastery_level_after": "learning",
                "reviewed_at": "2026-01-01T00:00:00",
                "created_at": "2026-01-01T00:00:00",
            }
        ],
    }


def _review_queue() -> dict[str, Any]:
    """store 级审核队列：两个候选（状态原样）共 3 条评审留痕。"""
    return {
        "schema_version": 1,
        "exported_at": "2026-01-03T00:00:00+00:00",
        "candidates": [
            {
                "id": _CAND_PENDING,
                "workspace_id": _WS_ID,
                "project_id": None,
                "episode_id": _EPISODE_ID,
                "title": "待审候选",
                "content": "候选正文",
                "type": "fact",
                "client_write_id": "cw-1",
                "confidence": 0.7,
                "quality_score": 0.82,
                "value_score": 0.75,
                "review_priority": 0.9,
                "duplicate_probability": 0.1,
                "similar_memory_id": _MEMORY_ID,
                "similar_memory_source": "memory",
                "dedup_relation_type": "NEW",
                "status": "pending_review",
                "source": "mcp",
                "created_at": "2026-01-02T00:00:00",
                "updated_at": "2026-01-02T00:00:00",
                "reviews": [
                    {
                        "id": _REVIEW_OF_PENDING,
                        "candidate_id": _CAND_PENDING,
                        "reviewer_type": "agent",
                        "reviewer_id": "mcp",
                        "action": "request_changes",
                        "before_content": None,
                        "after_content": None,
                        "reason": "需要补充来源",
                        "created_at": "2026-01-02T01:00:00",
                    }
                ],
            },
            {
                "id": _CAND_REJECTED,
                "workspace_id": _WS_ID,
                "title": "被拒候选",
                "content": "重复内容",
                "type": "fact",
                "status": "rejected",
                "source": "mcp",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "reviews": [
                    {
                        "id": _REVIEW_OF_REJECTED_1,
                        "candidate_id": _CAND_REJECTED,
                        "reviewer_type": "agent",
                        "reviewer_id": "mcp",
                        "action": "reject",
                        "reason": "与既有记忆重复",
                        "created_at": "2026-01-01T01:00:00",
                    },
                    {
                        "id": _REVIEW_OF_REJECTED_2,
                        "candidate_id": _CAND_REJECTED,
                        "reviewer_type": "human",
                        "reviewer_id": "user",
                        "action": "reject",
                        "reason": "确认拒绝",
                        "created_at": "2026-01-01T02:00:00",
                    },
                ],
            },
        ],
    }


def _history_row(hid: uuid.UUID, ws_id: uuid.UUID) -> ReviewHistory:
    """构造一条复习事件史行（用于塞入残留数据）。"""
    return ReviewHistory(
        id=hid,
        workspace_id=ws_id,
        memory_id=uuid.UUID(_MEMORY_ID),
        quality=3,
        ease_factor_before=2.5,
        interval_before=1,
        repetitions_before=0,
        next_review_before=_DT_STALE,
        mastery_level_before="new",
        ease_factor_after=2.5,
        interval_after=2,
        repetitions_after=1,
        next_review_after=_DT_STALE_NEXT,
        mastery_level_after="learning",
        reviewed_at=_DT_STALE,
    )


async def test_rebuild_restores_version_chain_and_review_history(tmp_path):
    """memory_version 版本链与 review_history 复习事件史完整恢复。"""
    rebuilder = _make_rebuilder(tmp_path)
    try:
        await _create_schema(rebuilder)
        _prepare_export(tmp_path / "data")

        result = await rebuilder.rebuild()

        assert result.relation_counts["versions"] == 2
        assert result.relation_counts["review_history"] == 1

        async with rebuilder._session_factory() as session:
            # 记忆本体经 _workspaces.json 精确落到导出时的 workspace
            mem = (
                await session.execute(select(Memory).where(Memory.id == uuid.UUID(_MEMORY_ID)))
            ).scalar_one()
            assert str(mem.workspace_id) == _WS_ID

            versions = (
                (await session.execute(select(MemoryVersion).order_by(MemoryVersion.version)))
                .scalars()
                .all()
            )
            assert [v.version for v in versions] == [1, 2]
            v1, v2 = versions
            assert str(v1.memory_id) == _MEMORY_ID
            assert v1.title == "初版标题"
            assert v1.content == "初版内容"
            assert v1.change_type == "created"
            assert v1.changed_by_type == "agent"
            assert v1.created_at == _DT_CREATED
            assert v2.title == "修订标题"
            assert v2.reason == "修正表述"

            histories = (await session.execute(select(ReviewHistory))).scalars().all()
            assert len(histories) == 1
            h = histories[0]
            # workspace_id 与记忆的 workspace 一致（复习归属不丢）
            assert str(h.workspace_id) == _WS_ID
            assert str(h.memory_id) == _MEMORY_ID
            assert h.quality == 4
            assert h.ease_factor_before == 2.5
            assert h.ease_factor_after == 2.6
            assert h.interval_after == 3
            assert h.repetitions_after == 1
            assert h.mastery_level_after == "learning"
            assert h.reviewed_at == _DT_CREATED
    finally:
        await rebuilder.close()


async def test_rebuild_restores_candidates_and_reviews(tmp_path):
    """candidate 全字段（含悬空 episode_id 与原样 status）与 review 留痕恢复。"""
    rebuilder = _make_rebuilder(tmp_path)
    try:
        await _create_schema(rebuilder)
        _prepare_export(tmp_path / "data")

        result = await rebuilder.rebuild()

        assert result.candidate_count == 2
        assert result.review_count == 3

        async with rebuilder._session_factory() as session:
            cands = (await session.execute(select(CandidateMemory))).scalars().all()
            by_id = {str(c.id): c for c in cands}
            assert set(by_id) == {_CAND_PENDING, _CAND_REJECTED}

            pending = by_id[_CAND_PENDING]
            assert pending.status == "pending_review"  # 状态原样，不被重置
            assert pending.title == "待审候选"
            assert pending.content == "候选正文"
            assert pending.type == "fact"
            assert pending.client_write_id == "cw-1"
            assert pending.quality_score == 0.82
            assert pending.review_priority == 0.9
            assert pending.duplicate_probability == 0.1
            assert str(pending.similar_memory_id) == _MEMORY_ID
            assert pending.similar_memory_source == "memory"
            assert pending.dedup_relation_type == "NEW"
            assert str(pending.workspace_id) == _WS_ID
            # episode 表不随重建重灌：悬空引用有意原样保留（追溯性优先）
            assert str(pending.episode_id) == _EPISODE_ID
            assert pending.created_at == _DT_UPDATED

            assert by_id[_CAND_REJECTED].status == "rejected"

            reviews = (await session.execute(select(Review))).scalars().all()
            by_cand: dict[str, list[Review]] = {}
            for r in reviews:
                by_cand.setdefault(str(r.candidate_id), []).append(r)
            # 留痕挂到正确的候选上
            assert {k: len(v) for k, v in by_cand.items()} == {
                _CAND_PENDING: 1,
                _CAND_REJECTED: 2,
            }
            only = by_cand[_CAND_PENDING][0]
            assert str(only.id) == _REVIEW_OF_PENDING
            assert only.reviewer_type == "agent"
            assert only.action == "request_changes"
            assert only.reason == "需要补充来源"
            assert only.created_at == _DT_REVIEW
    finally:
        await rebuilder.close()


async def test_rebuild_clears_stale_rows_in_four_tables(tmp_path):
    """重建先清空四表：上一轮残留的候选/留痕/版本/复习史不跨重建泄漏。"""
    rebuilder = _make_rebuilder(tmp_path)
    try:
        await _create_schema(rebuilder)

        # 预先塞入"残留"行，模拟上一轮数据（不在本次导出物中）。
        stale_ws = uuid.uuid4()
        stale_cand = uuid.uuid4()
        stale_review = uuid.uuid4()
        stale_version = uuid.uuid4()
        stale_history = uuid.uuid4()
        async with rebuilder._session_factory() as session:
            session.add(Workspace(id=stale_ws, name="stale-ws"))
            session.add(
                CandidateMemory(
                    id=stale_cand,
                    workspace_id=stale_ws,
                    title="旧候选",
                    content="x",
                    type="fact",
                )
            )
            session.add(
                Review(
                    id=stale_review,
                    candidate_id=stale_cand,
                    reviewer_type="agent",
                    action="approve",
                )
            )
            session.add(
                MemoryVersion(
                    id=stale_version,
                    memory_id=uuid.UUID(_MEMORY_ID),
                    version=99,
                    title="旧版本",
                    content="x",
                    change_type="update",
                    changed_by_type="agent",
                )
            )
            session.add(_history_row(stale_history, stale_ws))
            await session.commit()

        _prepare_export(tmp_path / "data")
        await rebuilder.rebuild()

        async with rebuilder._session_factory() as session:
            cand_ids = set((await session.execute(select(CandidateMemory.id))).scalars())
            assert {str(c) for c in cand_ids} == {_CAND_PENDING, _CAND_REJECTED}

            review_ids = {str(r) for r in (await session.execute(select(Review.id))).scalars()}
            assert str(stale_review) not in review_ids

            versions = set(
                (
                    await session.execute(
                        select(MemoryVersion.version).where(
                            MemoryVersion.memory_id == uuid.UUID(_MEMORY_ID)
                        )
                    )
                ).scalars()
            )
            assert versions == {1, 2}  # version=99 的残留行已被清空

            history_ids = {
                str(h) for h in (await session.execute(select(ReviewHistory.id))).scalars()
            }
            assert str(stale_history) not in history_ids
    finally:
        await rebuilder.close()


async def test_rebuild_dedupes_relations_exported_to_both_endpoints(tmp_path):
    """同一条关系边写进两端记忆的 _meta，重建时只应恢复一行。"""
    m1 = "aaaaaaaa-0000-0000-0000-000000000001"
    m2 = "aaaaaaaa-0000-0000-0000-000000000002"
    rel_id = "bbbbbbbb-0000-0000-0000-000000000001"
    relation = {
        "id": rel_id,
        "source_memory_id": m2,
        "target_memory_id": m1,
        "relation_type": "supersedes",
        "confidence": 1.0,
        "created_at": "2026-01-01T00:00:00",
    }

    data_dir = tmp_path / "data"
    file_store = FileStore(str(data_dir))
    for mid in (m1, m2):
        file_store.save(
            MemoryFile(
                id=mid,
                title=f"记忆 {mid[-1]}",
                content="关系去重测试正文",
                workspace="cwiki",
                created=_DT_CREATED,
                updated=_DT_UPDATED,
            ),
            workspace_name="cwiki",
        )
    meta_dir = data_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    MetaStore(meta_dir).export_workspaces(
        [{"name": "cwiki", "id": _WS_ID, "created_at": None, "updated_at": None}]
    )
    for mid in (m1, m2):
        meta = {
            "feedback": [],
            "usage": [],
            "conflict": [],
            "review_schedule": {},
            "relation": [relation],
            "lifecycle_event": [],
            "evidence": [],
            "versions": [],
            "review_history": [],
        }
        (meta_dir / f"{mid}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

    rebuilder = _make_rebuilder(tmp_path)
    try:
        await _create_schema(rebuilder)
        result = await rebuilder.rebuild()

        assert result.relation_counts["relation"] == 1
        async with rebuilder._session_factory() as session:
            rows = (await session.execute(select(MemoryRelation))).scalars().all()
            assert len(rows) == 1
            assert str(rows[0].id) == rel_id
    finally:
        await rebuilder.close()
