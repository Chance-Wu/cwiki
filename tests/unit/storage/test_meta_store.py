"""MetaStore 测试 — memory-id 列举与工作区元数据。"""

import json

from packages.storage.meta_store import MetaStore

_MEMORY_ID = "03badc6a-33cc-4937-ae43-95ebc425a73d"


def test_list_memories_ignores_workspaces_json(tmp_path):
    """_workspaces.json 绝不能被当作 memory_id 列举（或导入）。"""
    store = MetaStore(tmp_path)
    store.export_memory(_MEMORY_ID, {})
    store.export_workspaces(
        [
            {
                "name": "chat",
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        ]
    )

    assert store.list_memories() == [_MEMORY_ID]


def test_list_memories_ignores_non_uuid_json_files(tmp_path):
    store = MetaStore(tmp_path)
    store.export_memory(_MEMORY_ID, {})
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    (tmp_path / "not-a-memory.json").write_text("{}", encoding="utf-8")

    assert store.list_memories() == [_MEMORY_ID]


def test_import_memory_rejects_non_memory_id(tmp_path):
    store = MetaStore(tmp_path)
    (tmp_path / "_workspaces.json").write_text("[]", encoding="utf-8")

    assert store.import_memory("_workspaces") is None


def test_workspaces_export_import_roundtrip(tmp_path):
    store = MetaStore(tmp_path)
    payload = [
        {
            "name": "cwiki",
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-02T03:04:05",
        }
    ]

    path = store.export_workspaces(payload)

    assert path == tmp_path / "_workspaces.json"
    assert store.import_workspaces() == payload


def test_import_workspaces_missing_file_returns_none(tmp_path):
    assert MetaStore(tmp_path).import_workspaces() is None


def test_import_workspaces_invalid_json_returns_none(tmp_path):
    store = MetaStore(tmp_path)
    (tmp_path / "_workspaces.json").write_text("{not json", encoding="utf-8")

    assert store.import_workspaces() is None


def test_import_workspaces_non_list_returns_none(tmp_path):
    store = MetaStore(tmp_path)
    (tmp_path / "_workspaces.json").write_text('{"name": "chat"}', encoding="utf-8")

    assert store.import_workspaces() is None


# ---------------------------------------------------------------------------
# 候选审核队列（_review_queue.json）
# ---------------------------------------------------------------------------


def test_review_queue_export_import_roundtrip(tmp_path):
    store = MetaStore(tmp_path)
    payload = {
        "schema_version": 1,
        "exported_at": "2026-01-02T03:04:05+00:00",
        "candidates": [
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "workspace_id": "11111111-2222-3333-4444-555555555555",
                "title": "待审候选",
                "content": "内容",
                "status": "pending_review",
                "reviews": [
                    {
                        "id": "99999999-8888-7777-6666-555555555555",
                        "candidate_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        "action": "approve",
                    }
                ],
            }
        ],
    }

    path = store.export_review_queue(payload)

    assert path == tmp_path / "_review_queue.json"
    # 中文内容不被转义为 \uXXXX，保证 Git 同步文件对人可读
    assert "待审候选" in path.read_text(encoding="utf-8")
    assert store.import_review_queue() == payload


def test_import_review_queue_missing_file_returns_none(tmp_path):
    assert MetaStore(tmp_path).import_review_queue() is None


def test_import_review_queue_invalid_json_returns_none(tmp_path):
    store = MetaStore(tmp_path)
    (tmp_path / "_review_queue.json").write_text("{not json", encoding="utf-8")

    assert store.import_review_queue() is None


def test_import_review_queue_non_dict_returns_none(tmp_path):
    store = MetaStore(tmp_path)
    (tmp_path / "_review_queue.json").write_text("[]", encoding="utf-8")

    assert store.import_review_queue() is None


def test_list_memories_ignores_review_queue_json(tmp_path):
    """_review_queue.json 是 store 级文件，绝不能被当作 memory_id。"""
    store = MetaStore(tmp_path)
    store.export_memory(_MEMORY_ID, {})
    store.export_review_queue({"schema_version": 1, "candidates": []})

    assert store.list_memories() == [_MEMORY_ID]


# ---------------------------------------------------------------------------
# 每记忆 _meta 新键（versions / review_history）默认值
# ---------------------------------------------------------------------------


def test_export_memory_normalises_new_relation_keys(tmp_path):
    """export_memory 缺键填默认：versions / review_history 为空列表。"""
    store = MetaStore(tmp_path)
    store.export_memory(_MEMORY_ID, {})

    data = store.import_memory(_MEMORY_ID)
    assert data["versions"] == []
    assert data["review_history"] == []


def test_import_memory_backfills_new_relation_keys(tmp_path):
    """旧格式 _meta（无 versions / review_history 键）导入时补默认值。"""
    store = MetaStore(tmp_path)
    old_format = {
        "feedback": [],
        "usage": [],
        "conflict": [],
        "review_schedule": {},
        "relation": [],
        "lifecycle_event": [],
        "evidence": [],
    }
    (tmp_path / f"{_MEMORY_ID}.json").write_text(json.dumps(old_format), encoding="utf-8")

    data = store.import_memory(_MEMORY_ID)
    assert data["versions"] == []
    assert data["review_history"] == []
