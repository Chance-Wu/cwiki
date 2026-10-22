"""标签 SQL 匹配辅助函数：必须按 JSON 数组元素精确匹配，支持中文。"""

import uuid

from sqlalchemy import select

from packages.domain.models import Memory, Workspace
from packages.memory.tag_query import memory_has_tag


async def test_memory_has_tag_matches_cjk_exactly(db_session) -> None:
    workspace = Workspace(name=f"tag-query-{uuid.uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    matched = Memory(
        workspace_id=workspace.id,
        title="中文标签命中",
        content="正文",
        type="fact",
        tags=["合并", "diff"],
    )
    other = Memory(
        workspace_id=workspace.id,
        title="相似标签不应命中",
        content="正文",
        type="fact",
        tags=["合并测试"],
    )
    db_session.add_all([matched, other])
    await db_session.commit()

    result = (
        (
            await db_session.execute(
                select(Memory.id).where(Memory.status == "active", memory_has_tag("合并"))
            )
        )
        .scalars()
        .all()
    )

    assert result == [matched.id]
