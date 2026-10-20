"""Markdown 文件存储，支持 YAML frontmatter。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from packages.domain.paths import sanitize_filename, validate_path_component

logger = logging.getLogger(__name__)


class MemoryFile:
    """以 Markdown 文件形式存储的一条记忆。"""

    def __init__(
        self,
        id: str,
        title: str,
        content: str,
        type: str = "fact",
        tags: list[str] | None = None,
        related: list[str] | None = None,
        version: int = 1,
        status: str = "active",
        source: str = "mcp",
        workspace: str | None = None,
        created: datetime | None = None,
        updated: datetime | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        usage_count: int = 0,
        last_used_at: datetime | None = None,
        is_permanent: bool = False,
        metadata: dict[str, Any] | None = None,
    ):
        self.id = id
        self.title = title
        self.content = content
        self.type = type
        self.tags = tags or []
        self.related = related or []
        self.version = version
        self.status = status
        self.source = source
        self.workspace = workspace
        self.created = created or datetime.now(UTC)
        self.updated = updated or datetime.now(UTC)
        self.confidence = confidence
        self.importance = importance
        self.usage_count = usage_count
        self.last_used_at = last_used_at
        self.is_permanent = is_permanent
        self.metadata = metadata
        self.file_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "type": self.type,
            "tags": self.tags,
            "related": self.related,
            "version": self.version,
            "status": self.status,
            "source": self.source,
            "workspace": self.workspace,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "confidence": self.confidence,
            "importance": self.importance,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_permanent": self.is_permanent,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryFile:
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            content=data.get("content", ""),
            type=data.get("type", "fact"),
            tags=data.get("tags", []),
            related=data.get("related", []),
            version=data.get("version", 1),
            status=data.get("status", "active"),
            source=data.get("source", "mcp"),
            workspace=data.get("workspace"),
            created=datetime.fromisoformat(data["created"]) if "created" in data else None,
            updated=datetime.fromisoformat(data["updated"]) if "updated" in data else None,
            confidence=data.get("confidence"),
            importance=data.get("importance"),
            usage_count=data.get("usage_count", 0),
            last_used_at=(
                datetime.fromisoformat(data["last_used_at"]) if data.get("last_used_at") else None
            ),
            is_permanent=data.get("is_permanent", False),
            metadata=data.get("metadata"),
        )


class FileStore:
    """管理以 Markdown 文件形式存放的记忆。"""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, workspace_name: str, type: str, filename: str) -> Path:
        """获取记忆文件路径：{workspace}/{type}/{filename}.md"""
        workspace_dir = self.base_path / validate_path_component(workspace_name or "chat")
        type_dir = workspace_dir / validate_path_component(type)
        file_name = validate_path_component(f"{filename}.md")
        type_dir.mkdir(parents=True, exist_ok=True)
        return type_dir / file_name

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """解析 Markdown 内容中的 YAML frontmatter。"""
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        try:
            metadata = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return metadata, body
        except yaml.YAMLError:
            return {}, content

    def _serialize(self, memory: MemoryFile) -> str:
        """将记忆序列化为带 frontmatter 的 Markdown。"""
        frontmatter = {
            "id": memory.id,
            "title": memory.title,
            "type": memory.type,
            "tags": memory.tags,
            "related": memory.related,
            "version": memory.version,
            "status": memory.status,
            "source": memory.source,
            "workspace": memory.workspace,
            "created": memory.created.isoformat(),
            "updated": memory.updated.isoformat(),
            "confidence": memory.confidence,
            "importance": memory.importance,
            "usage_count": memory.usage_count,
            "last_used_at": memory.last_used_at.isoformat() if memory.last_used_at else None,
            "is_permanent": memory.is_permanent,
            "metadata": memory.metadata,
        }

        yaml_content = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
        return f"---\n{yaml_content}---\n\n{memory.content}\n"

    @staticmethod
    def _sanitize_filename(name: str, max_bytes: int = 200) -> str:
        """将字符串清理为可安全用作文件名的形式。"""
        return sanitize_filename(name, max_bytes)

    def _make_filename(self, memory_id: str, title: str, max_title_bytes: int = 200) -> str:
        """构建文件名：{short_id}_{sanitized_title}"""
        short_id = sanitize_filename(memory_id.split("-", 1)[0][:8])
        return f"{short_id}_{self._sanitize_filename(title, max_title_bytes)}"

    def _find_file_by_id(self, workspace_name: str, type: str, memory_id: str) -> Path | None:
        """在类型目录内按 frontmatter 中的 ID 查找记忆文件。"""
        type_dir = (
            self.base_path
            / validate_path_component(workspace_name or "chat")
            / validate_path_component(type)
        )
        if not type_dir.exists():
            return None
        for file_path in type_dir.iterdir():
            if not file_path.is_file() or file_path.suffix.lower() != ".md":
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                metadata, _ = self._parse_frontmatter(content)
                if metadata.get("id") == memory_id:
                    return file_path
            except Exception:
                logger.debug("Failed to parse frontmatter from %s", file_path, exc_info=True)
                continue
        return None

    def save(self, memory: MemoryFile, workspace_name: str | None = None) -> Path:
        """将记忆保存为 Markdown 文件。

        路径结构：{workspace_name}/{type}/{id}_{title}.md
        """
        ws = workspace_name or "chat"
        max_title_bytes = self._title_byte_budget(ws, memory.type)
        filename = self._make_filename(memory.id, memory.title, max_title_bytes)
        file_path = self._get_file_path(ws, memory.type, filename)

        content = self._serialize(memory)
        file_path.write_text(content, encoding="utf-8")

        return file_path

    # Windows MAX_PATH 上限（短路径，不带 \\?\ 前缀）。
    _WINDOWS_MAX_PATH = 260

    def _title_byte_budget(self, workspace_name: str, memory_type: str) -> int:
        """返回标题允许的最大 UTF-8 字节数，保证完整路径不超过 MAX_PATH。

        Windows 上总路径长度必须小于 260 个 UTF-16 码元。这里先把固定开销
        换算成 UTF-16 码元数并从 260 中扣除，再把剩余的码元预算保守地
        换算回文件名中*标题*部分的 UTF-8 字节预算。
        """
        import sys

        if sys.platform != "win32":
            return 200

        ws_dir = validate_path_component(workspace_name)
        type_dir = validate_path_component(memory_type)
        # 用完整路径模板测量固定开销。
        full = self.base_path / ws_dir / type_dir / "x.md"
        overhead_cu = len(str(full).encode("utf-16-le")) // 2
        # 占位符 "x" 占 1 个码元；扣除后得到真实开销。
        overhead_cu -= 1

        available_cu = self._WINDOWS_MAX_PATH - overhead_cu
        if available_cu < 20:
            return 20  # 绝对下限，保证文件仍能创建。

        # 将码元预算换算为标题的 UTF-8 字节预算。
        # 文件名形如 "{short_id}_{title}.md"：short_id ≤ 8 个 ASCII 字符
        # = 8 字节，".md" = 3 字节，"_" = 1 字节 → 文件名固定开销 12 字节。
        # 对 ASCII 而言 1 码元 ≈ 1 UTF-8 字节；但 CJK 字符占 3 个 UTF-8 字节
        # 却只算 1 个码元。按码元与字节 1:1 映射对 ASCII 偏保守、对 CJK 足够，
        # 因为 validate_path_component 的 255 字节单组件上限才是更紧的约束。
        filename_cu_budget = available_cu  # 文件名可用的码元数
        # 以 255 字节（单组件上限）封顶，再扣除 id 与扩展名开销。
        max_filename_bytes = min(filename_cu_budget, 255)
        title_budget = max_filename_bytes - 12  # short_id(8) + _(1) + .md(3)
        return max(title_budget, 20)

    def load(
        self, workspace_name: str, type: str, title: str, memory_id: str | None = None
    ) -> MemoryFile | None:
        """从 Markdown 文件加载记忆。

        提供 memory_id 时按 frontmatter 中的 ID 查找（可靠）；
        否则退回按标题文件名查找（旧版方式）。
        """
        if memory_id:
            file_path = self._find_file_by_id(workspace_name, type, memory_id)
            if not file_path:
                return None
        else:
            filename = self._sanitize_filename(title)
            file_path = self._get_file_path(workspace_name, type, filename)
            if not file_path.exists():
                return None

        content = file_path.read_text(encoding="utf-8")
        metadata, body = self._parse_frontmatter(content)

        if not metadata or "id" not in metadata:
            return None

        ws = metadata.get("workspace") or workspace_name
        memory = MemoryFile.from_dict({**metadata, "workspace": ws, "content": body})
        memory.file_path = file_path
        return memory

    def load_from_path(self, file_path: str | Path) -> MemoryFile | None:
        """直接从文件路径加载记忆（供 watchdog 使用）。"""
        path = Path(file_path)
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        metadata, body = self._parse_frontmatter(content)
        if not metadata or "id" not in metadata:
            return None
        ws = metadata.get("workspace") or path.parent.parent.name
        memory = MemoryFile.from_dict({**metadata, "workspace": ws, "content": body})
        memory.file_path = path
        return memory

    def delete(
        self, workspace_name: str, type: str, title: str, memory_id: str | None = None
    ) -> bool:
        """删除记忆文件。

        提供 memory_id 时按 frontmatter 中的 ID 查找（可靠）；
        否则退回按标题文件名查找（旧版方式）。
        """
        if memory_id:
            file_path = self._find_file_by_id(workspace_name, type, memory_id)
            if not file_path:
                return False
            file_path.unlink()
            return True

        filename = self._sanitize_filename(title)
        file_path = self._get_file_path(workspace_name, type, filename)

        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def list_with_skipped(
        self, workspace_name: str | None = None
    ) -> tuple[list[MemoryFile], list[tuple[str, str]]]:
        """列出全部记忆，同时返回无法解析而被跳过的文件。

        返回 ``(memories, skipped)``，skipped 每项为 ``(文件路径, 原因)``。
        这些文件（空文件 / frontmatter 缺 id / YAML 损坏 / 读取失败）无法
        还原出记忆；DB 重建时若不显式暴露就会静默丢数据，因此除返回
        外还以 error 级别记日志。
        """
        memories: list[MemoryFile] = []
        skipped: list[tuple[str, str]] = []
        base = self.base_path

        if workspace_name:
            workspaces = [validate_path_component(workspace_name)]
        else:
            workspaces = [d.name for d in base.iterdir() if d.is_dir()]

        for ws in workspaces:
            ws_dir = base / ws
            if not ws_dir.exists():
                continue
            for type_dir in ws_dir.iterdir():
                if not type_dir.is_dir():
                    continue
                for file_path in type_dir.iterdir():
                    if not file_path.is_file() or file_path.suffix.lower() != ".md":
                        continue
                    try:
                        content = file_path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as exc:
                        logger.error("Memory file unreadable, skipping: %s (%s)", file_path, exc)
                        skipped.append((str(file_path), f"read_error: {exc}"))
                        continue
                    metadata, body = self._parse_frontmatter(content)
                    if metadata and "id" in metadata:
                        metadata["workspace"] = ws
                        memory = MemoryFile.from_dict({**metadata, "content": body})
                        memory.file_path = file_path
                        memories.append(memory)
                    else:
                        logger.error(
                            "Memory file has no parsable frontmatter (missing id), skipping: %s",
                            file_path,
                        )
                        skipped.append((str(file_path), "no_frontmatter_id"))

        return memories, skipped

    def list(self, workspace_name: str | None = None) -> list[MemoryFile]:
        """列出全部记忆，可按 workspace 过滤。"""
        memories, _ = self.list_with_skipped(workspace_name)
        return memories

    def search_by_content(self, query: str, workspace_name: str | None = None) -> list[MemoryFile]:  # type: ignore[valid-type]
        """在记忆内容与标题中做简单文本搜索。"""
        memories = self.list(workspace_name)
        query_lower = query.lower()

        return [
            m
            for m in memories
            if query_lower in m.content.lower() or query_lower in m.title.lower()
        ]
