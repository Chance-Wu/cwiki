"""写入路径增量导出 _meta：保存记忆后无需等待周期导出。"""

from __future__ import annotations

import json

from apps.api.file_sync import sync_memory_to_file
from packages.domain.models import Memory, Workspace
from packages.storage.file_store import FileStore
from packages.storage.indexer import MemoryIndexer

_REQUIRED_KEYS = {
    "feedback",
    "usage",
    "conflict",
    "review_schedule",
    "relation",
    "lifecycle_event",
    "evidence",
    "versions",
    "review_history",
}


async def test_sync_memory_writes_meta_sidecar(db_session, tmp_path, monkeypatch):
    store = FileStore(tmp_path / "mirrors")
    indexer = MemoryIndexer(
        str(tmp_path / "index.db"),
        store,
        vector_index_path=str(tmp_path / "vectors"),
        embedding_dimensions=3,
    )
    await indexer.init_db()
    monkeypatch.setattr("apps.api.file_sync.get_file_store", lambda: store)
    monkeypatch.setattr("apps.api.file_sync.get_memory_indexer", lambda: indexer)

    workspace = Workspace(name="meta-on-sync")
    db_session.add(workspace)
    await db_session.flush()
    memory = Memory(
        workspace_id=workspace.id,
        title="增量导出",
        content="知识内容" * 20,
        type="fact",
    )
    db_session.add(memory)
    await db_session.commit()

    assert await sync_memory_to_file(memory, db_session, skip_vector_index=True) is True

    meta_path = store.base_path / "_meta" / f"{memory.id}.json"
    assert meta_path.is_file()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert set(payload) >= _REQUIRED_KEYS
    assert payload["review_schedule"] == {}
