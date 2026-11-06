"""正文 [[标题]] 双链到记忆关系的同步测试。"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from packages.domain.models import Memory, MemoryRelation, Workspace
from packages.memory.wikilink import (
    MAX_LINKS_PER_MEMORY,
    extract_link_targets,
    sync_all_wikilinks,
    sync_wikilink_relations,
)


class TestExtractLinkTargets:
    def test_plain_links_in_order(self):
        assert extract_link_targets("先看 [[连接池配置]]，再看 [[死信队列]]") == [
            "连接池配置",
            "死信队列",
        ]

    def test_anchor_and_alias_are_dropped(self):
        assert extract_link_targets("[[连接池配置#最大连接数]] 与 [[死信队列|DLQ]]") == [
            "连接池配置",
            "死信队列",
        ]

    def test_dedup_is_case_insensitive(self):
        assert extract_link_targets("[[Redis]] then [[redis]] again [[REDIS]]") == ["Redis"]

    def test_ignores_unclosed_and_empty(self):
        assert extract_link_targets("[[未闭合 和 [[]] 和 [单括号]") == []

    def test_caps_number_of_links(self):
        content = " ".join(f"[[标题{i}]]" for i in range(MAX_LINKS_PER_MEMORY + 10))
        assert len(extract_link_targets(content)) == MAX_LINKS_PER_MEMORY


async def _workspace(db_session, name: str = "wikilink") -> Workspace:
    workspace = Workspace(name=name)
    db_session.add(workspace)
    await db_session.flush()
    return workspace


def _memory(workspace: Workspace, title: str, content: str = "") -> Memory:
    return Memory(
        workspace_id=workspace.id,
        title=title,
        content=content or f"{title} 的正文",
        type="fact",
        status="active",
    )


async def _edges(db_session, source_id: uuid.UUID) -> list[MemoryRelation]:
    rows = await db_session.execute(
        select(MemoryRelation).where(MemoryRelation.source_memory_id == source_id)
    )
    return list(rows.scalars().all())


class TestSyncWikilinkRelations:
    async def test_creates_edge_for_referenced_title(self, db_session):
        workspace = await _workspace(db_session)
        target = _memory(workspace, "连接池配置")
        source = _memory(workspace, "排查手册", "先读 [[连接池配置]] 再动手")
        db_session.add_all([target, source])
        await db_session.flush()

        assert await sync_wikilink_relations(db_session, source) == 1
        edges = await _edges(db_session, source.id)
        assert len(edges) == 1
        assert edges[0].target_memory_id == target.id
        assert edges[0].relation_type == "related"
        assert edges[0].created_by == "wikilink"

    async def test_resync_drops_removed_links(self, db_session):
        workspace = await _workspace(db_session)
        target = _memory(workspace, "连接池配置")
        source = _memory(workspace, "排查手册", "先读 [[连接池配置]]")
        db_session.add_all([target, source])
        await db_session.flush()
        assert await sync_wikilink_relations(db_session, source) == 1

        source.content = "不再引用任何记忆"
        assert await sync_wikilink_relations(db_session, source) == 0
        assert await _edges(db_session, source.id) == []

    async def test_keeps_foreign_edges_and_skips_duplicates(self, db_session):
        workspace = await _workspace(db_session)
        target = _memory(workspace, "连接池配置")
        source = _memory(workspace, "排查手册", "先读 [[连接池配置]]")
        db_session.add_all([target, source])
        await db_session.flush()
        db_session.add(
            MemoryRelation(
                source_memory_id=source.id,
                target_memory_id=target.id,
                relation_type="related",
                created_by="manual",
            )
        )
        await db_session.flush()

        assert await sync_wikilink_relations(db_session, source) == 0
        edges = await _edges(db_session, source.id)
        assert [edge.created_by for edge in edges] == ["manual"]

    async def test_same_title_links_all_matches(self, db_session):
        workspace = await _workspace(db_session)
        first = _memory(workspace, "同名记忆")
        second = _memory(workspace, "同名记忆")
        source = _memory(workspace, "引用者", "见 [[同名记忆]]")
        db_session.add_all([first, second, source])
        await db_session.flush()

        assert await sync_wikilink_relations(db_session, source) == 2
        assert {edge.target_memory_id for edge in await _edges(db_session, source.id)} == {
            first.id,
            second.id,
        }

    async def test_self_link_and_inactive_target_are_ignored(self, db_session):
        workspace = await _workspace(db_session)
        archived = _memory(workspace, "归档记忆")
        archived.status = "deprecated"
        source = _memory(workspace, "自己", "[[自己]] 与 [[归档记忆]]")
        db_session.add_all([archived, source])
        await db_session.flush()

        assert await sync_wikilink_relations(db_session, source) == 0
        assert await _edges(db_session, source.id) == []

    async def test_other_workspace_is_not_linked(self, db_session):
        mine = await _workspace(db_session, "mine")
        other = await _workspace(db_session, "other")
        foreign = _memory(other, "外部记忆")
        source = _memory(mine, "引用者", "见 [[外部记忆]]")
        db_session.add_all([foreign, source])
        await db_session.flush()

        assert await sync_wikilink_relations(db_session, source) == 0

    async def test_sync_all_rebuilds_every_memory(self, db_session):
        workspace = await _workspace(db_session)
        target = _memory(workspace, "连接池配置")
        source = _memory(workspace, "排查手册", "先读 [[连接池配置]]")
        db_session.add_all([target, source])
        await db_session.flush()

        assert await sync_all_wikilinks(db_session) == 1
        assert len(await _edges(db_session, source.id)) == 1
