"""migrate_to_git 导出侧测试：审核队列、版本截断与复习史导出。

验证导出中枢写出的两条新数据流：
1. store 级 ``_meta/_review_queue.json``（候选全字段除 embedding + 嵌套留痕）；
2. 每记忆 _meta 的 ``versions``（按 meta_version_limit 截断保最新）与
   ``review_history`` 键。
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import (
    Base,
    CandidateMemory,
    Memory,
    MemoryVersion,
    Review,
    ReviewHistory,
    Workspace,
)
from packages.storage import config as storage_config
from packages.storage.meta_store import MetaStore
from scripts.migrate_to_git import export_all

# DB 的 DateTime 列为 naive 时间，统一经 fromisoformat 构造
_DT_BEFORE = datetime.fromisoformat("2026-01-01T00:00:00")
_DT_AFTER = datetime.fromisoformat("2026-01-04T00:00:00")
_DT_REVIEWED = datetime.fromisoformat("2026-01-01T00:00:00")
_DT_CAND = datetime.fromisoformat("2026-01-02T00:00:00")
_DT_R1 = datetime.fromisoformat("2026-01-02T01:00:00")
_DT_R2 = datetime.fromisoformat("2026-01-02T02:00:00")


async def test_export_writes_review_queue_and_new_meta_keys(tmp_path, monkeypatch):
    """候选/留痕进 _review_queue.json；版本截断、复习史全量进每记忆 _meta。"""
    db_path = tmp_path / "src.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    ws_id = uuid.uuid4()
    mem_id = uuid.uuid4()
    cand_id = uuid.uuid4()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Workspace(id=ws_id, name="cwiki"))
        session.add(
            Memory(
                id=mem_id,
                workspace_id=ws_id,
                title="记忆标题",
                content="记忆内容",
                type="fact",
            )
        )
        # 5 条版本：截断上限压到 3 时只应导出最新 3 条（v3/v4/v5）
        for i in range(1, 6):
            session.add(
                MemoryVersion(
                    id=uuid.uuid4(),
                    memory_id=mem_id,
                    version=i,
                    title=f"标题 v{i}",
                    content=f"内容 v{i}",
                    change_type="update" if i > 1 else "created",
                    changed_by_type="agent",
                )
            )
        session.add(
            ReviewHistory(
                id=uuid.uuid4(),
                workspace_id=ws_id,
                memory_id=mem_id,
                quality=4,
                ease_factor_before=2.5,
                interval_before=1,
                repetitions_before=0,
                next_review_before=_DT_BEFORE,
                mastery_level_before="new",
                ease_factor_after=2.6,
                interval_after=3,
                repetitions_after=1,
                next_review_after=_DT_AFTER,
                mastery_level_after="learning",
                reviewed_at=_DT_REVIEWED,
            )
        )
        session.add(
            CandidateMemory(
                id=cand_id,
                workspace_id=ws_id,
                title="待审候选",
                content="候选正文",
                type="fact",
                client_write_id="cw-1",
                quality_score=0.82,
                status="pending_review",
                created_at=_DT_CAND,
            )
        )
        # 两条留痕：不同 created_at，导出应按时间升序排列（git diff 稳定）
        session.add(
            Review(
                id=uuid.uuid4(),
                candidate_id=cand_id,
                reviewer_type="agent",
                reviewer_id="mcp",
                action="request_changes",
                reason="需要补充来源",
                created_at=_DT_R1,
            )
        )
        session.add(
            Review(
                id=uuid.uuid4(),
                candidate_id=cand_id,
                reviewer_type="human",
                reviewer_id="user",
                action="approve",
                reason="已补充",
                created_at=_DT_R2,
            )
        )
        await session.commit()
    await engine.dispose()

    # 截断上限压到 3，避免依赖 config.yaml 的具体取值
    monkeypatch.setattr(storage_config, "meta_version_limit", 3)

    data_dir = tmp_path / "data"
    stats = await export_all(db_url, str(data_dir))

    assert stats["errors"] == 0
    assert stats["memory_count"] == 1
    assert stats["meta_count"] == 1
    assert stats["candidate_count"] == 1
    assert stats["review_count"] == 2

    meta_store = MetaStore(data_dir / "_meta")

    # --- _review_queue.json：候选全字段（除 embedding）+ 嵌套 reviews ---
    queue = meta_store.import_review_queue()
    assert queue is not None
    assert queue["schema_version"] == 1
    assert queue["exported_at"]
    (cand,) = queue["candidates"]
    assert cand["id"] == str(cand_id)
    assert cand["workspace_id"] == str(ws_id)
    assert cand["status"] == "pending_review"
    assert cand["quality_score"] == 0.82
    assert cand["client_write_id"] == "cw-1"
    assert cand["type"] == "fact"
    assert "embedding" not in cand  # embedding 不进 Git 同步文件
    assert [r["action"] for r in cand["reviews"]] == ["request_changes", "approve"]
    assert all(r["candidate_id"] == str(cand_id) for r in cand["reviews"])
    assert cand["reviews"][0]["reason"] == "需要补充来源"

    # --- 每记忆 _meta 新键：versions 截断保最新 + review_history 全量 ---
    meta = meta_store.import_memory(str(mem_id))
    # 5 条 → 3 条最新（v3/v4/v5），文件内升序排列便于阅读
    assert [v["version"] for v in meta["versions"]] == [3, 4, 5]
    assert meta["versions"][0]["title"] == "标题 v3"
    assert meta["versions"][-1]["title"] == "标题 v5"

    (history,) = meta["review_history"]
    assert history["memory_id"] == str(mem_id)
    assert history["workspace_id"] == str(ws_id)
    assert history["quality"] == 4
    assert history["ease_factor_after"] == 2.6
    assert history["mastery_level_after"] == "learning"
