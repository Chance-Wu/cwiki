"""标签管理端点：中文标签与含斜杠标签必须可管理、可筛选。"""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from packages.domain.models import Memory, Workspace


@pytest.fixture
async def workspace(db_session):
    ws = Workspace(name=f"tags-{uuid.uuid4().hex[:8]}")
    db_session.add(ws)
    await db_session.flush()
    return ws


async def _add_memory(
    db_session, workspace, title: str, tags: list[str], status: str = "active"
) -> Memory:
    memory = Memory(
        workspace_id=workspace.id,
        title=title,
        content=f"{title} 的正文内容",
        type="fact",
        tags=tags,
        status=status,
    )
    db_session.add(memory)
    await db_session.commit()
    return memory


async def test_rename_cjk_tag(client: httpx.AsyncClient, db_session, workspace) -> None:
    memory = await _add_memory(db_session, workspace, "中文标签重命名", ["合并", "diff"])

    response = await client.put(
        "/v1/tags/合并",
        params={"workspace_id": str(workspace.id)},
        json={"new_name": "已取代"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 1
    await db_session.refresh(memory)
    assert memory.tags == ["已取代", "diff"]


async def test_rename_tag_dedupes_existing_target(
    client: httpx.AsyncClient, db_session, workspace
) -> None:
    memory = await _add_memory(db_session, workspace, "重命名去重", ["ai", "llm"])

    response = await client.put(
        "/v1/tags/ai",
        params={"workspace_id": str(workspace.id)},
        json={"new_name": "llm"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 1
    await db_session.refresh(memory)
    assert memory.tags == ["llm"]


async def test_merge_cjk_tags(client: httpx.AsyncClient, db_session, workspace) -> None:
    first = await _add_memory(db_session, workspace, "合并源一", ["合并", "a"])
    second = await _add_memory(db_session, workspace, "合并源二", ["重构", "b"])

    response = await client.post(
        "/v1/tags/merge",
        params={"workspace_id": str(workspace.id)},
        json={"source_tags": ["合并", "重构"], "target_tag": "整理"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 2
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.tags == ["a", "整理"]
    assert second.tags == ["b", "整理"]


async def test_delete_tag_with_slash(client: httpx.AsyncClient, db_session, workspace) -> None:
    memory = await _add_memory(db_session, workspace, "斜杠标签删除", ["memory/cwiki", "diff"])

    response = await client.delete(
        "/v1/tags/memory/cwiki",
        params={"workspace_id": str(workspace.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 1
    await db_session.refresh(memory)
    assert memory.tags == ["diff"]


async def test_rename_tag_with_slash(client: httpx.AsyncClient, db_session, workspace) -> None:
    memory = await _add_memory(db_session, workspace, "斜杠标签重命名", ["memory/cwiki"])

    response = await client.put(
        "/v1/tags/memory/cwiki",
        params={"workspace_id": str(workspace.id)},
        json={"new_name": "cwiki"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 1
    await db_session.refresh(memory)
    assert memory.tags == ["cwiki"]


async def test_list_memories_filters_by_cjk_tag(
    client: httpx.AsyncClient, db_session, workspace
) -> None:
    matched = await _add_memory(db_session, workspace, "带中文标签", ["合并"])
    other = await _add_memory(db_session, workspace, "不带标签", ["diff"])

    response = await client.get(
        "/v1/memories",
        params={"workspace_id": str(workspace.id), "tags": "合并"},
    )

    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["items"]]
    assert str(matched.id) in ids
    assert str(other.id) not in ids


async def test_list_tags_counts_superseded_by_default(
    client: httpx.AsyncClient, db_session, workspace
) -> None:
    await _add_memory(db_session, workspace, "生效记忆", ["shared"])
    await _add_memory(
        db_session, workspace, "已取代记忆", ["shared", "legacy"], status="superseded"
    )

    response = await client.get("/v1/tags", params={"workspace_id": str(workspace.id)})

    assert response.status_code == 200, response.text
    counts = {tag["name"]: tag["count"] for tag in response.json()["tags"]}
    assert counts["shared"] == 2
    assert counts["legacy"] == 1


async def test_list_tags_filters_by_status(
    client: httpx.AsyncClient, db_session, workspace
) -> None:
    await _add_memory(db_session, workspace, "生效记忆", ["shared"])
    await _add_memory(
        db_session, workspace, "已取代记忆", ["shared", "legacy"], status="superseded"
    )

    active_only = await client.get(
        "/v1/tags",
        params={"workspace_id": str(workspace.id), "status": "active"},
    )
    superseded_only = await client.get(
        "/v1/tags",
        params={"workspace_id": str(workspace.id), "status": "superseded"},
    )

    active_counts = {tag["name"]: tag["count"] for tag in active_only.json()["tags"]}
    superseded_counts = {tag["name"]: tag["count"] for tag in superseded_only.json()["tags"]}
    assert active_counts == {"shared": 1}
    assert superseded_counts == {"shared": 1, "legacy": 1}


async def test_rename_tag_updates_superseded_memory(
    client: httpx.AsyncClient, db_session, workspace
) -> None:
    memory = await _add_memory(
        db_session, workspace, "已取代标签改名", ["old"], status="superseded"
    )

    response = await client.put(
        "/v1/tags/old",
        params={"workspace_id": str(workspace.id)},
        json={"new_name": "new"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 1
    await db_session.refresh(memory)
    assert memory.tags == ["new"]


async def test_delete_tag_updates_superseded_memory(
    client: httpx.AsyncClient, db_session, workspace
) -> None:
    memory = await _add_memory(
        db_session, workspace, "已取代标签删除", ["legacy", "keep"], status="superseded"
    )

    response = await client.delete(
        "/v1/tags/legacy",
        params={"workspace_id": str(workspace.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 1
    await db_session.refresh(memory)
    assert memory.tags == ["keep"]


async def test_tag_mutation_syncs_every_changed_memory(
    client: httpx.AsyncClient,
    db_session,
    workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _add_memory(db_session, workspace, "生效记忆同步", ["old"])
    await _add_memory(db_session, workspace, "已取代记忆同步", ["old"], status="superseded")
    sync = AsyncMock()
    monkeypatch.setattr("apps.api.routes.memories.tags.sync_memory_to_file", sync, raising=False)

    response = await client.put(
        "/v1/tags/old",
        params={"workspace_id": str(workspace.id)},
        json={"new_name": "new"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 2
    assert sync.await_count == 2
