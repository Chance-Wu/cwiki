"""MetaStore：按记忆存储的关系数据，以 JSON 形式保存在 _meta/ 目录。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# relations 字典中预期存在的键。
_RELATION_KEYS = (
    "feedback",
    "usage",
    "conflict",
    "review_schedule",
    "relation",
    "lifecycle_event",
    "evidence",
    "versions",
    "review_history",
)

# store 级伴随文件，保存 workspace 元数据（名称/id/时间戳），
# 包含自身没有 MD 文件的空 workspace。由 migrate_to_git 写入，
# 重建器读取它来恢复 workspace 表。
WORKSPACES_FILENAME = "_workspaces.json"

# store 级伴随文件，保存候选审核队列（candidate_memory 全字段 + 各自的
# review 评审留痕）。候选不经 Markdown 承载，重建器读取它来恢复这两张表；
# 旧版导出无此文件时重建后队列为空（向前兼容）。
REVIEW_QUEUE_FILENAME = "_review_queue.json"

# store 级伴随文件，保存 Agent 捕获会话与待整理笔记。笔记不经 Markdown
# 承载，重建/换设备时靠这份文件恢复“未整理内容”，避免内容丢失。
CAPTURE_FILENAME = "_capture_notes.json"

# 记忆伴随文件一律命名为 ``{uuid}.json``。其他文件（如
# ``_workspaces.json``）属于 store 级文件，绝不能当作 memory_id。
_MEMORY_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class MetaStore:
    """以 _meta/ 下的独立 JSON 文件管理每条记忆的关系数据。

    每条记忆对应一个 ``{memory_id}.json``，包含其全部关系数据
    （feedback、usage、冲突、复习计划、关系、生命周期事件、证据）。
    Markdown 文件只承载记忆内容本身，而伴随 JSON 承接目前
    存放在 SQLite 中的其余数据。
    """

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _file_for(self, memory_id: str) -> Path:
        """返回指定 memory_id 对应的 JSON 路径。"""
        return self.base_path / f"{memory_id}.json"

    # ------------------------------------------------------------------
    # Workspace 元数据
    # ------------------------------------------------------------------

    def export_workspaces(self, workspaces: list[dict[str, Any]]) -> Path:
        """将 workspace 元数据列表写入 ``_meta/_workspaces.json``。

        每个条目包含 ``{name, id, created_at, updated_at}``（时间采用
        ISO 8601）。重建器读取该文件以精确恢复 workspace 表 ——
        包括没有 MD 文件的空 workspace。返回写入文件的路径。
        """
        file_path = self.base_path / WORKSPACES_FILENAME
        try:
            file_path.write_text(
                json.dumps(workspaces, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to write %s", WORKSPACES_FILENAME)
            raise

        return file_path

    def import_workspaces(self) -> list[dict[str, Any]] | None:
        """读取 ``_meta/_workspaces.json``。

        返回解析后的 workspace 条目列表；文件缺失（旧版导出）或不可读时
        返回 ``None`` —— 调用方随后退回 MD frontmatter。
        """
        file_path = self.base_path / WORKSPACES_FILENAME
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read %s", WORKSPACES_FILENAME, exc_info=True)
            return None

        if not isinstance(data, list):
            logger.warning("%s does not contain a JSON list, ignoring", WORKSPACES_FILENAME)
            return None

        return [item for item in data if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # 候选审核队列
    # ------------------------------------------------------------------

    def export_review_queue(self, payload: dict[str, Any]) -> Path:
        """将候选审核队列写入 ``_meta/_review_queue.json``。

        payload 形如 ``{"schema_version": 1, "exported_at": ...,
        "candidates": [...]}``，每个候选含全字段（除 embedding）与
        嵌套的 ``reviews`` 留痕列表。重建器读取该文件以恢复
        ``candidate_memory`` 与 ``review`` 表。返回写入文件的路径。
        """
        file_path = self.base_path / REVIEW_QUEUE_FILENAME
        try:
            file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to write %s", REVIEW_QUEUE_FILENAME)
            raise

        return file_path

    def import_review_queue(self) -> dict[str, Any] | None:
        """读取 ``_meta/_review_queue.json``。

        返回解析后的 dict；文件缺失（旧版导出）或不可读时返回
        ``None`` —— 调用方随后按"空队列"处理。
        """
        file_path = self.base_path / REVIEW_QUEUE_FILENAME
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read %s", REVIEW_QUEUE_FILENAME, exc_info=True)
            return None

        if not isinstance(data, dict):
            logger.warning("%s does not contain a JSON object, ignoring", REVIEW_QUEUE_FILENAME)
            return None

        return data

    # ------------------------------------------------------------------
    # Agent 捕获会话 / 待整理笔记
    # ------------------------------------------------------------------

    def export_capture(self, payload: dict[str, Any]) -> Path:
        """写入 ``_meta/_capture_notes.json``（会话 + 待整理笔记全文）。"""
        file_path = self.base_path / CAPTURE_FILENAME
        try:
            file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to write %s", CAPTURE_FILENAME)
            raise
        return file_path

    def import_capture(self) -> dict[str, Any] | None:
        """读取 ``_meta/_capture_notes.json``；缺失/损坏时返回 None。"""
        file_path = self.base_path / CAPTURE_FILENAME
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read %s", CAPTURE_FILENAME, exc_info=True)
            return None
        if not isinstance(data, dict):
            logger.warning("%s does not contain a JSON object, ignoring", CAPTURE_FILENAME)
            return None
        return data

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def export_memory(self, memory_id: str, relations: dict[str, Any]) -> Path:
        """将 *relations* 字典写入 ``{base_path}/{memory_id}.json``。

        字典应包含 ``_RELATION_KEYS`` 列出的键。缺失的键会填入合理默认值
        （空列表，``review_schedule`` 为空字典），保证落盘 schema 始终一致。

        返回写入文件的路径。
        """
        normalised: dict[str, Any] = {}
        for key in _RELATION_KEYS:
            if key == "review_schedule":
                normalised[key] = relations.get(key) or {}
            else:
                normalised[key] = relations.get(key) or []

        file_path = self._file_for(memory_id)
        try:
            file_path.write_text(
                json.dumps(normalised, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to write _meta for memory %s", memory_id)
            raise

        return file_path

    def import_memory(self, memory_id: str) -> dict[str, Any] | None:
        """读取 *memory_id* 的关系数据 JSON。

        返回解析后的字典；文件不存在时返回 ``None``。JSON 解析失败时记录
        警告并返回 ``None``。非记忆 id（如 ``_workspaces``）会被拒绝，
        以防把 store 级伴随文件误导入为记忆数据。
        """
        if not _MEMORY_ID_RE.fullmatch(memory_id):
            logger.warning("Ignoring non-memory _meta id %r", memory_id)
            return None

        file_path = self._file_for(memory_id)
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read _meta for memory %s", memory_id, exc_info=True)
            return None

        if not isinstance(data, dict):
            logger.warning("Ignoring non-object _meta for memory %s", memory_id)
            return None

        # 确保所有预期键存在（向前兼容旧版本文件）。
        for key in _RELATION_KEYS:
            if key not in data:
                data[key] = {} if key == "review_schedule" else []

        return data

    def list_memories(self) -> list[str]:
        """返回所有拥有 ``_meta`` JSON 文件的 memory_id。

        仅 UUID 命名的文件才算记忆；``_workspaces.json`` 等 store 级
        伴随文件会被过滤，绝不会被导入为记忆 id。
        """
        if not self.base_path.exists():
            return []
        return sorted(
            p.stem
            for p in self.base_path.iterdir()
            if p.is_file() and p.suffix == ".json" and _MEMORY_ID_RE.fullmatch(p.stem)
        )

    def delete_memory(self, memory_id: str) -> bool:
        """删除 *memory_id* 对应的 ``_meta`` 伴随文件。

        删除成功返回 True，文件不存在返回 False。非记忆 id
        （如 ``_workspaces``）会被拒绝，以防误删 store 级伴随文件。
        """
        if not _MEMORY_ID_RE.fullmatch(memory_id):
            logger.warning("Ignoring non-memory _meta id %r", memory_id)
            return False

        file_path = self._file_for(memory_id)
        if not file_path.exists():
            return False
        file_path.unlink()
        return True
