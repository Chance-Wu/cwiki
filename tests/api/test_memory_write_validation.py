"""
从 tests/api/test_p2_modules.py 按主题拆出的测试：TestMemoryUpdate、TestMemoryTitleConfig、TestMemoryContentValidation、TestSharedMemoryWriteValidation、TestMemoryLifecycle。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestMemoryUpdate:
    async def test_update_confidence_only(self):
        from unittest.mock import AsyncMock

        from adapters.mcp.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value={"id": "test-id", "confidence": 0.9})

        result = await client.update_memory(
            memory_id="test-id",
            confidence=0.9,
        )

        client._request.assert_called_once()
        call_args = client._request.call_args
        assert call_args[0][0] == "PATCH"
        assert call_args[0][1] == "/v1/memories/test-id"
        assert call_args[1]["json_body"] == {"confidence": 0.9}
        assert result["confidence"] == 0.9

    async def test_update_multiple_fields(self):
        from unittest.mock import AsyncMock

        from adapters.mcp.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value={"id": "test-id"})

        await client.update_memory(
            memory_id="test-id",
            title="新标题",
            content="新内容",
            confidence=0.8,
            importance=0.9,
        )

        call_args = client._request.call_args
        assert call_args[1]["json_body"] == {
            "title": "新标题",
            "content": "新内容",
            "confidence": 0.8,
            "importance": 0.9,
        }

    async def test_update_with_none_fields_excluded(self):
        from unittest.mock import AsyncMock

        from adapters.mcp.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value={"id": "test-id"})

        await client.update_memory(
            memory_id="test-id",
            confidence=0.7,
            title=None,
            content=None,
        )

        call_args = client._request.call_args
        assert "title" not in call_args[1]["json_body"]
        assert "content" not in call_args[1]["json_body"]
        assert call_args[1]["json_body"] == {"confidence": 0.7}


class TestMemoryTitleConfig:
    @pytest.mark.parametrize("config", [{}, {"memory": {}}], ids=["no-section", "no-key"])
    def test_default_title_limit_is_eighty(self, monkeypatch, config):
        import packages.domain.config as config_module

        monkeypatch.setattr(config_module, "_yaml_config", config)
        assert config_module.Settings().memory_title_max_length == 80

    @pytest.mark.parametrize("max_length", [12, 32])
    def test_settings_reads_title_limit_from_memory_section(self, monkeypatch, max_length):
        import packages.domain.config as config_module

        monkeypatch.setattr(
            config_module, "_yaml_config", {"memory": {"title_max_length": max_length}}
        )
        assert config_module.Settings().memory_title_max_length == max_length

    @pytest.mark.parametrize(
        "config, expected",
        [
            ({"memory": {"title_max_length": 12}}, 12),
            ({"memory": {"title_max_length": 32}}, 32),
            ({"memory": {}}, 80),
            ({}, 80),
        ],
        ids=["lower-limit", "higher-limit", "removed-key", "removed-section"],
    )
    def test_reload_refreshes_title_limit_without_replacing_settings(
        self, monkeypatch, config, expected
    ):
        import packages.domain.config as config_module

        monkeypatch.setattr(config_module, "_yaml_config", {"memory": {"title_max_length": 27}})
        settings = config_module.Settings()
        assert settings.memory_title_max_length == 27
        # 只 mock 磁盘加载；实际执行缓存与 Settings 的 reload 方法。
        monkeypatch.setattr(config_module, "_load_yaml_config", lambda: config)
        config_module.reload_yaml_config()
        settings.reload()
        assert settings.memory_title_max_length == expected


class TestMemoryContentValidation:
    @pytest.mark.parametrize(
        "content",
        [
            (
                "先验证再提交：离线导出保留正文和附件的对应关系，恢复时应核对文件数量、"
                "编码和原始时间戳。本轮只验证当前工作区，其他工作区尚未确认。"
            ),
            (
                "## 排查证据\n连接超时仍未定位，不编造根因。已保留完整错误响应和请求时间，"
                "下一步核对连接池设置与服务日志，当前没有可验证的修复结论。"
            ),
            (
                "### 适用边界\n仅隔离环境需要离线依赖包。部署前应准备对应平台的依赖版本和"
                "校验值，安装后核对包清单；联网环境暂不采用这套离线分发流程。"
            ),
            (
                "- 导出时保存完整正文、附件路径和原始时间戳。\n"
                "- 恢复时核对文件数量与校验值，确认来源完整后重建索引，不使用摘要替代原文。"
            ),
            (
                "| 方案 | 取舍 |\n| --- | --- |\n| 离线安装 | 需要准备依赖包 |\n"
                "| 联网安装 | 依赖下载服务可用 |\n\n当前环境网络受限，选择预先准备离线依赖包。"
            ),
            (
                "```markdown\n## 这是示例中的标题，不应被删除\n"
                "代码块中的标题和缩进都属于原始材料。\n```\n"
                "接收端只校验长度，不因分类变化而修改围栏或重排示例。"
            ),
            (
                "## 场景\n原来的结构仍然可用，已有记录由人工核实。\n"
                "## 知识\n保留已有内容及其原始证据和适用条件。\n"
                "## 原因\n正文结构不影响分类，无需迁移或强制转换为其他格式。"
            ),
        ],
    )
    def test_free_content_is_valid(self, content):
        from packages.domain.types import validate_memory_content
        from packages.memory.service import _validate_mcp_content

        assert len(content.strip()) >= 50
        _validate_mcp_content(content)
        assert validate_memory_content(content) == content

    @pytest.mark.parametrize(
        "content",
        [
            "",
            " \n\t ",
            "短",
            "1234",
            "  1234  ",
            "Too short content!",
            " \t\nToo short content!  \n",
        ],
    )
    def test_empty_or_too_short_content_is_rejected(self, content):
        from packages.memory.service import ContentFormatError, _validate_mcp_content

        with pytest.raises(ContentFormatError, match="至少 20 个字符"):
            _validate_mcp_content(content)

    def test_types_provide_type_definitions(self):
        from packages.domain.types import TYPE_DEFINITIONS

        assert len(TYPE_DEFINITIONS) == 11
        for t in TYPE_DEFINITIONS.values():
            assert t["name"]
            assert t["description"]


class TestSharedMemoryWriteValidation:
    @pytest.fixture(autouse=True)
    def default_title_limit(self, monkeypatch):
        from packages.domain.config import settings

        monkeypatch.setattr(settings, "memory_title_max_length", 20)

    @pytest.fixture(params=["memory", "candidate", "patch", "file-create", "file-update", "review"])
    def schema_payload(self, request):
        from apps.api.routes.file_memories import MemoryCreateRequest, MemoryUpdateRequest
        from packages.domain.schemas.memory import (
            CandidateMemoryCreate,
            MemoryCreate,
            MemoryUpdate,
            ReviewCreate,
        )

        schemas = {
            "memory": MemoryCreate,
            "candidate": CandidateMemoryCreate,
            "patch": MemoryUpdate,
            "file-create": MemoryCreateRequest,
            "file-update": MemoryUpdateRequest,
            "review": ReviewCreate,
        }
        if request.param == "review":
            payload = {"candidate_id": uuid.uuid4(), "reviewer_type": "human", "action": "edit"}
            title_field, content_field = "edited_title", "edited_content"
        else:
            payload = (
                {"workspace_id": str(uuid.uuid4()), "type": "fact"}
                if request.param in ("memory", "candidate")
                else {}
            )
            title_field, content_field = "title", "content"
        payload[title_field] = "Offline export notes"
        payload[content_field] = "Offline export keeps source text for later review."
        return schemas[request.param], payload, title_field, content_field

    @pytest.mark.parametrize(
        "field, value",
        [
            ("title", ""),
            ("title", " \n\t "),
            ("title", "Offline export notes!"),
            ("title", " Offline export notes"),
            ("content", "Too short content!"),
            ("content", " \t\nToo short content!  \n"),
        ],
        ids=[
            "empty-title",
            "blank-title",
            "title-21",
            "padded-title-21",
            "content-18",
            "padded-18",
        ],
    )
    def test_schemas_share_title_and_stripped_content_validation(
        self, schema_payload, field, value
    ):
        from pydantic import ValidationError

        schema, payload, title_field, content_field = schema_payload
        target = title_field if field == "title" else content_field
        with pytest.raises(ValidationError) as exc:
            schema.model_validate({**payload, target: value})
        assert any(error["loc"] == (target,) for error in exc.value.errors())

    @pytest.mark.parametrize("padded", [False, True])
    def test_schema_accepts_exact_boundary_without_normalizing(self, schema_payload, padded):
        schema, payload, title_field, content_field = schema_payload
        assert len(payload[title_field]) == 20
        assert len(payload[content_field]) == 50
        if padded:
            payload[title_field] = "  离线导出标题  "
            payload[content_field] = " \t\n" + payload[content_field] + "  \n"
        result = schema.model_validate(payload)
        assert getattr(result, title_field) == payload[title_field]
        assert getattr(result, content_field) == payload[content_field]

    def test_schema_uses_runtime_title_limit_after_settings_reload(
        self, schema_payload, monkeypatch
    ):
        from pydantic import ValidationError

        import packages.domain.config as config_module

        schema, payload, title_field, _ = schema_payload
        runtime_settings = config_module.Settings()
        monkeypatch.setattr("packages.domain.types.settings", runtime_settings)
        # 模型已导入完毕；校验不得沿用导入时刻冻结的上限。
        for max_length in (12, 32):
            monkeypatch.setattr(
                config_module, "_yaml_config", {"memory": {"title_max_length": max_length}}
            )
            runtime_settings.reload()
            title = "标" * max_length
            result = schema.model_validate({**payload, title_field: title})
            assert getattr(result, title_field) == title
            with pytest.raises(ValidationError) as exc:
                schema.model_validate({**payload, title_field: title + "题"})
            assert any(error["loc"] == (title_field,) for error in exc.value.errors())

    @pytest.mark.parametrize("with_nulls", [False, True])
    def test_update_schemas_allow_omitted_or_null_text(self, with_nulls):
        from apps.api.routes.file_memories import MemoryUpdateRequest
        from packages.domain.schemas.memory import MemoryUpdate

        payload = {"title": None, "content": None} if with_nulls else {}
        for schema in (MemoryUpdate, MemoryUpdateRequest):
            result = schema.model_validate(payload)
            assert result.title is None
            assert result.content is None
            assert result.model_dump(exclude_unset=True) == payload

    @pytest.mark.parametrize("padded", [False, True])
    def test_review_merged_content_uses_same_boundary(self, padded):
        from pydantic import ValidationError

        from packages.domain.schemas.memory import ReviewCreate

        payload = {"candidate_id": uuid.uuid4(), "reviewer_type": "human", "action": "merge"}
        valid = "A" * 20
        invalid = "A" * 19
        if padded:
            valid, invalid = " \t\n" + valid + "  \n", " \t\n" + invalid + "  \n"
        result = ReviewCreate(**payload, merged_content=valid)
        assert result.merged_content == valid
        with pytest.raises(ValidationError) as exc:
            ReviewCreate(**payload, merged_content=invalid)
        assert any(error["loc"] == ("merged_content",) for error in exc.value.errors())
        assert ReviewCreate(**payload, merged_content=None).merged_content is None

    def test_shared_validators_return_original_strings(self):
        from packages.domain.types import (
            MIN_CONTENT_LENGTH,
            validate_memory_content,
            validate_memory_title,
        )

        assert MIN_CONTENT_LENGTH == 20
        title = "  离线导出说明  "
        content = " \t\nOffline export keeps source text for later review.  \n"
        assert validate_memory_title(title) == title
        assert validate_memory_content(content) == content
        with pytest.raises(ValueError):
            validate_memory_title(" \n\t ")
        with pytest.raises(ValueError):
            validate_memory_title("Offline export notes!")
        with pytest.raises(ValueError):
            validate_memory_content(" \t\nToo short  \n")

    @pytest.mark.parametrize(
        "updates",
        [
            {"title": ""},
            {"title": " \n\t "},
            {"title": "Offline export notes!"},
            {"content": "Too short"},
            {"content": " \t\nToo short  \n"},
        ],
    )
    async def test_service_direct_calls_raise_content_format_error_before_writing(self, updates):
        from packages.memory.service import ContentFormatError, create_candidate

        db = AsyncMock()
        payload = {
            "workspace_id": uuid.uuid4(),
            "title": "Offline export notes",
            "content": "Offline export keeps source text for later review.",
            "type": "fact",
            **updates,
        }
        with pytest.raises(ContentFormatError):
            await create_candidate(db=db, **payload)
        db.execute.assert_not_awaited()
        db.flush.assert_not_awaited()
        db.add.assert_not_called()


class TestMemoryLifecycle:
    """记忆生命周期管理测试（P4-37）。"""

    async def test_client_get_lifecycle(self):
        from adapters.mcp.client import CwikiClient

        client = CwikiClient("http://test:5172")
        expected = {
            "memory_id": "test-id",
            "current_status": "updated",
            "timeline": [
                {"event_type": "created", "timestamp": "2026-09-01T00:00:00", "metadata": None},
                {"event_type": "updated", "timestamp": "2026-09-10T00:00:00", "metadata": None},
            ],
            "age_days": 14,
            "event_count": 2,
        }
        client._request = AsyncMock(return_value=expected)

        result = await client.get_memory_lifecycle("test-id")

        client._request.assert_called_once()
        call_args = client._request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/v1/memories/test-id/lifecycle"
        assert result["current_status"] == "updated"
        assert result["event_count"] == 2
        assert len(result["timeline"]) == 2

    async def test_client_get_lifecycle_empty(self):
        from adapters.mcp.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(
            return_value={
                "memory_id": "test-id",
                "current_status": "unknown",
                "timeline": [],
                "age_days": None,
                "event_count": 0,
            }
        )

        result = await client.get_memory_lifecycle("test-id")

        assert result["current_status"] == "unknown"
        assert result["event_count"] == 0
        assert result["age_days"] is None

    def test_lifecycle_model_exists(self):
        from packages.domain.models import MemoryLifecycleEvent

        assert hasattr(MemoryLifecycleEvent, "__tablename__")
        assert MemoryLifecycleEvent.__tablename__ == "memory_lifecycle_event"
        assert hasattr(MemoryLifecycleEvent, "memory_id")
        assert hasattr(MemoryLifecycleEvent, "event_type")
        assert hasattr(MemoryLifecycleEvent, "metadata_json")
        assert hasattr(MemoryLifecycleEvent, "created_at")

    async def test_lifecycle_returns_404_for_unknown_memory(self):
        from fastapi import HTTPException

        from apps.api.routes.memories import get_memory_lifecycle

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_memory_lifecycle(memory_id=str(uuid.uuid4()), db=db)
        assert exc_info.value.status_code == 404

    async def test_relations_returns_404_for_unknown_memory(self):
        """与 get_memory_lifecycle 契约一致：不存在的记忆返回 404。"""
        from fastapi import HTTPException

        from apps.api.routes.memories import get_memory_relations

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_memory_relations(memory_id=str(uuid.uuid4()), db=db)
        assert exc_info.value.status_code == 404

    async def test_create_relation_rejects_reverse_symmetric_duplicate(self):
        """对称关系（related/supports/contradicts）反向重复也应冲突。"""
        from fastapi import HTTPException

        from apps.api.routes.memories.relations import create_memory_relation
        from packages.domain.models import Memory
        from packages.domain.schemas import RelationCreate

        source = Memory(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            title="Source",
            content="source content",
            type="fact",
            source="test",
            status="active",
            version=1,
        )
        target = Memory(
            id=uuid.uuid4(),
            workspace_id=source.workspace_id,
            title="Target",
            content="target content",
            type="fact",
            source="test",
            status="active",
            version=1,
        )

        db = AsyncMock()
        db.get = AsyncMock(side_effect=[source, target])
        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = object()
        db.execute = AsyncMock(return_value=duplicate_result)

        with pytest.raises(HTTPException) as exc:
            await create_memory_relation(
                memory_id=str(source.id),
                body=RelationCreate(
                    target_memory_id=target.id,
                    relation_type="related",
                ),
                db=db,
            )

        assert exc.value.status_code == 409
