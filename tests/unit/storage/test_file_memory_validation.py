from unittest.mock import AsyncMock, Mock

import pytest
from httpx import AsyncClient

from packages.storage.file_store import MemoryFile


@pytest.fixture
def file_memory_env(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, MemoryFile]:
    from packages.domain.config import settings

    monkeypatch.setattr(settings, "memory_title_max_length", 20)
    memory = MemoryFile(id="boundary", title="旧标题", content="原" * 50)
    store = Mock()
    store.load.return_value = memory
    indexer = Mock()
    indexer.index_memory = AsyncMock()
    indexer.get_memory = AsyncMock(
        return_value={"title": "旧标题", "type": "fact", "workspace": "test"}
    )
    monkeypatch.setattr("apps.api.routes.file_memories.get_file_store", lambda: store)
    monkeypatch.setattr("apps.api.routes.file_memories.get_memory_indexer", lambda: indexer)
    monkeypatch.setattr("apps.api.routes.file_memories.git_vc.commit", AsyncMock())
    return store, memory


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", " \n\t "),
        ("title", "题" * 21),
        ("content", ""),
        ("content", "文" * 19),
        ("content", " \n" + "文" * 19 + "\t "),
    ],
)
async def test_invalid_file_memory_is_rejected_before_writes(
    client: AsyncClient,
    file_memory_env: tuple[Mock, MemoryFile],
    method: str,
    field: str,
    value: str,
) -> None:
    store, memory = file_memory_env
    path = "/v1/file-memories" + ("/boundary" if method == "PUT" else "")
    response = await client.request(
        method, path, json={"title": "合法标题", "content": "文" * 50, field: value}
    )
    assert response.status_code == 422, response.text
    store.save.assert_not_called()
    store.delete.assert_not_called()
    assert memory.title == "旧标题"
    assert memory.content == "原" * 50


@pytest.mark.parametrize("method", ["POST", "PUT"])
async def test_file_memory_boundary_preserves_submitted_fields(
    client: AsyncClient, file_memory_env: tuple[Mock, MemoryFile], method: str
) -> None:
    store, _ = file_memory_env
    title = "题" * 20
    content = " \n" + "文" * 50 + "\t "
    path = "/v1/file-memories" + ("/boundary" if method == "PUT" else "")
    response = await client.request(method, path, json={"title": title, "content": content})
    assert response.status_code == 200, response.text
    saved = store.save.call_args.args[0]
    assert saved.title == title
    assert saved.content == content
    assert response.json()["content"] == content


async def test_file_memory_metadata_update_keeps_existing_fields(
    client: AsyncClient, file_memory_env: tuple[Mock, MemoryFile]
) -> None:
    _, memory = file_memory_env
    memory.title = "旧" * 30
    memory.content = "旧短正文"
    response = await client.put("/v1/file-memories/boundary", json={"tags": ["reviewed"]})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == memory.title
    assert response.json()["content"] == memory.content
    assert response.json()["tags"] == ["reviewed"]


async def test_file_memory_uses_configured_title_limit(
    client: AsyncClient,
    file_memory_env: tuple[Mock, MemoryFile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.domain.config import settings

    monkeypatch.setattr(settings, "memory_title_max_length", 24)
    for method, path in [("POST", "/v1/file-memories"), ("PUT", "/v1/file-memories/boundary")]:
        for length, status in [(24, 200), (25, 422)]:
            response = await client.request(
                method, path, json={"title": "题" * length, "content": "文" * 50}
            )
            assert response.status_code == status, response.text
