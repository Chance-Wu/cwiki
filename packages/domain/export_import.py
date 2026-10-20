"""cwiki 数据导入/导出服务。

支持两种格式：
- JSON：包含全部实体的完整结构化导出
- Markdown 打包：每条记忆一个 .md 文件 + manifest.json
"""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    CandidateMemory,
    Memory,
    MemoryLifecycleEvent,
    MemoryRelation,
    ReviewSchedule,
)
from packages.domain.models.session import SessionNote
from packages.domain.paths import sanitize_filename

# 跨包依赖（domain → memory）：content_security 仅依赖 domain.errors，无环；
# 导入（外部输入边界）与常规写入路径共用同一注入检测
from packages.memory.content_security import check_injection

logger = logging.getLogger(__name__)

EXPORT_VERSION = "1.0"


def _serialize_memory(m: Memory) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "workspace_id": str(m.workspace_id),
        "title": m.title,
        "content": m.content,
        "type": m.type,
        "source": m.source,
        "status": m.status,
        "confidence": m.confidence,
        "importance": m.importance,
        "version": m.version,
        "is_permanent": m.is_permanent,
        "permanent_reason": m.permanent_reason,
        "usage_count": m.usage_count,
        "metadata": m.metadata_,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _serialize_candidate(c: CandidateMemory) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "workspace_id": str(c.workspace_id),
        "title": c.title,
        "content": c.content,
        "type": c.type,
        "source": c.source,
        "status": c.status,
        "confidence": c.confidence,
        "value_score": c.value_score,
        "duplicate_probability": c.duplicate_probability,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_session_note(n: SessionNote) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "session_id": str(n.session_id),
        "workspace_id": str(n.workspace_id),
        "content": n.content,
        "signal_type": n.signal_type,
        "formalized": n.formalized,
        "formalized_memory_id": str(n.formalized_memory_id) if n.formalized_memory_id else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _serialize_relation(r: MemoryRelation) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "source_memory_id": str(r.source_memory_id),
        "target_memory_id": str(r.target_memory_id),
        "relation_type": r.relation_type,
        "confidence": r.confidence,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _serialize_review_schedule(s: ReviewSchedule) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "workspace_id": str(s.workspace_id),
        "memory_id": str(s.memory_id),
        "ease_factor": s.ease_factor,
        "interval_days": s.interval_days,
        "repetitions": s.repetitions,
        "next_review": s.next_review.isoformat() if s.next_review else None,
        "last_review": s.last_review.isoformat() if s.last_review else None,
        "total_reviews": s.total_reviews,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


async def export_data(
    db: AsyncSession,
    workspace_id: uuid.UUID | None = None,
    entities: list[str] | None = None,
) -> dict[str, Any]:
    """将数据导出为结构化字典。

    Args:
        db: 数据库会话
        workspace_id: 可选的 workspace 过滤（None 表示全部 workspace）
        entities: 要导出的实体类型列表，None 表示全部。
            可选值：memories、candidates、notes、relations、schedules
    """
    if entities is None:
        entities = ["memories", "candidates", "notes", "relations", "schedules"]

    result: dict[str, Any] = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "workspace_id": str(workspace_id) if workspace_id else None,
    }

    if "memories" in entities:
        stmt = select(Memory)
        if workspace_id:
            stmt = stmt.where(Memory.workspace_id == workspace_id)
        rows = (await db.execute(stmt)).scalars().all()
        result["memories"] = [_serialize_memory(m) for m in rows]

    if "candidates" in entities:
        stmt = select(CandidateMemory)
        if workspace_id:
            stmt = stmt.where(CandidateMemory.workspace_id == workspace_id)
        candidate_rows = cast(
            "list[CandidateMemory]",
            list((await db.execute(stmt)).scalars().all()),
        )
        result["candidates"] = [_serialize_candidate(c) for c in candidate_rows]

    if "notes" in entities:
        stmt = select(SessionNote)
        if workspace_id:
            stmt = stmt.where(SessionNote.workspace_id == workspace_id)
        note_rows = cast(
            "list[SessionNote]",
            list((await db.execute(stmt)).scalars().all()),
        )
        result["notes"] = [_serialize_session_note(n) for n in note_rows]

    if "relations" in entities:
        stmt = select(MemoryRelation)
        if workspace_id:
            memory_ids_stmt = select(Memory.id).where(Memory.workspace_id == workspace_id)
            memory_ids_result = (await db.execute(memory_ids_stmt)).scalars().all()
            memory_id_set = set(memory_ids_result)
            stmt = stmt.where(MemoryRelation.source_memory_id.in_(memory_id_set))
        relation_rows = cast(
            "list[MemoryRelation]",
            list((await db.execute(stmt)).scalars().all()),
        )
        result["relations"] = [_serialize_relation(r) for r in relation_rows]

    if "schedules" in entities:
        stmt = select(ReviewSchedule)
        if workspace_id:
            stmt = stmt.where(ReviewSchedule.workspace_id == workspace_id)
        schedule_rows = cast(
            "list[ReviewSchedule]",
            list((await db.execute(stmt)).scalars().all()),
        )
        result["schedules"] = [_serialize_review_schedule(s) for s in schedule_rows]

    return result


def export_to_json(data: dict[str, Any], indent: int = 2) -> str:
    """将导出数据序列化为 JSON 字符串。"""
    return json.dumps(data, ensure_ascii=False, indent=indent)


def export_to_zip(data: dict[str, Any]) -> bytes:
    """生成 Markdown 打包 ZIP。

    结构：
      manifest.json
      memories/{id}.md   （YAML frontmatter + 正文）
      notes/{id}.md
    """
    buf = io.BytesIO()
    memories = data.get("memories", [])
    notes = data.get("notes", [])

    manifest = {
        "version": data.get("version", EXPORT_VERSION),
        "exported_at": data.get("exported_at"),
        "workspace_id": data.get("workspace_id"),
        "counts": {
            "memories": len(memories),
            "candidates": len(data.get("candidates", [])),
            "notes": len(notes),
            "relations": len(data.get("relations", [])),
            "schedules": len(data.get("schedules", [])),
        },
    }

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("data.json", export_to_json(data))

        for m in memories:
            md = _memory_to_markdown(m)
            safe_title = sanitize_filename(m["title"][:50])
            zf.writestr(f"memories/{m['id'][:8]}_{safe_title}.md", md)

        for n in notes:
            md = f"---\nid: {n['id']}\nsignal_type: {n['signal_type']}\nformalized: {n['formalized']}\ncreated_at: {n['created_at']}\n---\n\n{n['content']}\n"
            zf.writestr(f"notes/{n['id'][:8]}.md", md)

    return buf.getvalue()


def _memory_to_markdown(m: dict[str, Any]) -> str:
    frontmatter = {
        "id": m["id"],
        "title": m["title"],
        "type": m["type"],
        "source": m["source"],
        "status": m["status"],
        "confidence": m["confidence"],
        "importance": m["importance"],
        "version": m["version"],
        "is_permanent": m["is_permanent"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
    }
    fm_str = "\n".join(
        f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else v}"
        for k, v in frontmatter.items()
    )
    return f"---\n{fm_str}\n---\n\n{m['content']}\n"


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------


async def _skip_if_exists(
    db: AsyncSession,
    model: type,
    item: dict[str, Any],
    lookup_field: Any,
) -> tuple[Any | None, uuid.UUID | None]:
    """按唯一字段检查实体是否已存在。

    找到时返回 ``(existing, None)``，否则返回 ``(None, new_uuid)``。
    调用方用返回的 UUID 作为新实体 ID，并借此维护旧 ID→新 ID 映射，
    供后续实体引用重写。
    """
    old_id = item.get("id")
    if old_id:
        existing = (
            await db.execute(select(model).where(lookup_field == uuid.UUID(old_id)))
        ).scalar_one_or_none()
        if existing:
            return existing, None
    return None, uuid.uuid4()


async def import_data(
    db: AsyncSession,
    data: dict[str, Any],
    workspace_id: uuid.UUID,
    strategy: str = "skip",
) -> tuple[dict[str, Any], list[uuid.UUID]]:
    """从结构化字典导入数据。

    Args:
        db: 数据库会话
        data: 导出数据字典（来自 JSON 或从 ZIP 解出）
        workspace_id: 目标 workspace ID
        strategy: 冲突处理策略 —— "skip"（默认）、"overwrite" 或 "rename"

    Returns:
        (导入结果汇总, 有 DB 变更的记忆 ID 列表) —— 调用方据此在提交后
        补齐 MD 镜像与索引；skip 全跳过时列表为空。
    """
    # 导入只写 DB；MD 镜像与索引由调用方在事务提交后按返回的
    # touched_memory_ids 补齐（与 memory 路由同一套 sync_memory_to_file 机制）。
    # 曾只写 DB 不双写，导致 /v1/consistency 报 db/md/index/vector 计数不一致、
    # 且从 MD 重建 DB 时导入的记忆直接丢失。
    results: dict[str, Any] = {
        "memories": {"imported": 0, "skipped": 0, "updated": 0, "rejected": 0},
        "candidates": {"imported": 0, "skipped": 0, "rejected": 0},
        "notes": {"imported": 0, "skipped": 0, "rejected": 0},
        "relations": {"imported": 0, "skipped": 0},
        "schedules": {"imported": 0, "skipped": 0},
    }

    # 旧 ID → 新 ID 映射：跳过/覆盖的实体沿用旧 ID，新建实体分配新 ID，下游引用按此重写
    id_mapping: dict[str, uuid.UUID] = {}
    # 导入/更新涉及 DB 变更的记忆：路由提交后按此列表补齐 MD 镜像与索引
    touched_memory_ids: list[uuid.UUID] = []

    def _injection_rejected(section: str, item: dict[str, Any]) -> bool:
        """导入是外部输入边界，与常规写入路径同标准做注入检测。

        命中即拒绝该条并计数，不中断整批导入（迁移场景不应被单条脏数据卡死）。
        """
        text = f"{item.get('title', '')}\n{item.get('content', '')}"
        if not check_injection(text):
            return False
        results[section]["rejected"] += 1
        logger.warning(
            "Import rejected %s item %s: prompt injection pattern matched",
            section,
            item.get("id"),
        )
        return True

    for item in data.get("memories", []):
        old_id = item.get("id")
        existing = None
        if old_id:
            existing = (
                await db.execute(select(Memory).where(Memory.id == uuid.UUID(old_id)))
            ).scalar_one_or_none()

        if existing and strategy == "skip":
            id_mapping[old_id] = existing.id
            results["memories"]["skipped"] += 1
            continue

        if existing and strategy == "overwrite":
            if _injection_rejected("memories", item):
                continue
            existing.title = item["title"]
            existing.content = item["content"]
            existing.type = item.get("type", existing.type)
            existing.source = item.get("source", existing.source)
            existing.status = item.get("status", existing.status)
            existing.confidence = item.get("confidence", existing.confidence)
            existing.importance = item.get("importance", existing.importance)
            existing.is_permanent = item.get("is_permanent", existing.is_permanent)
            existing.metadata_ = item.get("metadata")
            existing.updated_at = datetime.now(UTC)
            id_mapping[old_id] = existing.id
            touched_memory_ids.append(existing.id)
            results["memories"]["updated"] += 1
            continue

        if _injection_rejected("memories", item):
            continue
        new_id = uuid.uuid4()
        if old_id:
            id_mapping[old_id] = new_id
        memory = Memory(
            id=new_id,
            workspace_id=workspace_id,
            title=item["title"],
            content=item["content"],
            type=item.get("type", "fact"),
            source=item.get("source", "import"),
            status=item.get("status", "active"),
            confidence=item.get("confidence", 0.5),
            importance=item.get("importance", 0.5),
            version=item.get("version", 1),
            is_permanent=item.get("is_permanent", False),
            permanent_reason=item.get("permanent_reason"),
            usage_count=item.get("usage_count", 0),
            metadata_=item.get("metadata"),
        )
        db.add(memory)
        db.add(
            MemoryLifecycleEvent(
                id=uuid.uuid4(),
                memory_id=new_id,
                event_type="created",
                metadata_json=json.dumps({"source": "import"}),
            )
        )
        touched_memory_ids.append(new_id)
        results["memories"]["imported"] += 1

    for item in data.get("candidates", []):
        existing, cand_new_id = await _skip_if_exists(db, CandidateMemory, item, CandidateMemory.id)
        if existing:
            id_mapping[item["id"]] = existing.id
            results["candidates"]["skipped"] += 1
            continue

        assert cand_new_id is not None  # existing 为 None 时必然返回新 UUID
        if _injection_rejected("candidates", item):
            continue
        old_id = item.get("id")
        if old_id:
            id_mapping[old_id] = cand_new_id
        candidate = CandidateMemory(
            id=cand_new_id,
            workspace_id=workspace_id,
            title=item["title"],
            content=item["content"],
            type=item.get("type", "fact"),
            source=item.get("source", "import"),
            status=item.get("status", "pending_review"),
            confidence=item.get("confidence"),
            value_score=item.get("value_score"),
        )
        db.add(candidate)
        results["candidates"]["imported"] += 1

    for item in data.get("notes", []):
        existing, _ = await _skip_if_exists(db, SessionNote, item, SessionNote.id)
        if existing:
            results["notes"]["skipped"] += 1
            continue

        if _injection_rejected("notes", item):
            continue
        formalized_mid = item.get("formalized_memory_id")
        if formalized_mid:
            formalized_mid = id_mapping.get(formalized_mid, formalized_mid)

        note = SessionNote(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            workspace_id=workspace_id,
            content=item["content"],
            signal_type=item.get("signal_type", "other"),
            formalized=item.get("formalized", False),
            formalized_memory_id=uuid.UUID(formalized_mid) if formalized_mid else None,
        )
        db.add(note)
        results["notes"]["imported"] += 1

    for item in data.get("relations", []):
        # 用 ID 映射重写关系两端引用；映射不上的旧 ID 原样保留
        old_src = item.get("source_memory_id")
        old_tgt = item.get("target_memory_id")
        new_src = id_mapping.get(old_src, old_src)
        new_tgt = id_mapping.get(old_tgt, old_tgt)

        try:
            src_uuid = uuid.UUID(str(new_src))
            tgt_uuid = uuid.UUID(str(new_tgt))
        except (ValueError, TypeError):
            results["relations"]["skipped"] += 1
            continue

        existing_relation = (
            await db.execute(
                select(MemoryRelation).where(
                    MemoryRelation.source_memory_id == src_uuid,
                    MemoryRelation.target_memory_id == tgt_uuid,
                    MemoryRelation.relation_type == item.get("relation_type", "related"),
                )
            )
        ).scalar_one_or_none()
        if existing_relation:
            results["relations"]["skipped"] += 1
            continue

        relation = MemoryRelation(
            id=uuid.uuid4(),
            source_memory_id=src_uuid,
            target_memory_id=tgt_uuid,
            relation_type=item.get("relation_type", "related"),
            confidence=item.get("confidence", 1.0),
        )
        db.add(relation)
        results["relations"]["imported"] += 1

    for item in data.get("schedules", []):
        old_mid = item.get("memory_id")
        new_mid = id_mapping.get(old_mid, old_mid)
        try:
            mid_uuid = uuid.UUID(str(new_mid))
        except (ValueError, TypeError):
            results["schedules"]["skipped"] += 1
            continue

        existing_schedule = (
            await db.execute(select(ReviewSchedule).where(ReviewSchedule.memory_id == mid_uuid))
        ).scalar_one_or_none()
        if existing_schedule:
            results["schedules"]["skipped"] += 1
            continue

        schedule = ReviewSchedule(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            memory_id=mid_uuid,
            ease_factor=item.get("ease_factor", 2.5),
            interval_days=item.get("interval_days", 1),
            repetitions=item.get("repetitions", 0),
            next_review=datetime.fromisoformat(item["next_review"])
            if item.get("next_review")
            else datetime.now(UTC),
            last_review=datetime.fromisoformat(item["last_review"])
            if item.get("last_review")
            else None,
            total_reviews=item.get("total_reviews", 0),
        )
        db.add(schedule)
        results["schedules"]["imported"] += 1

    await db.flush()
    return results, touched_memory_ids


def parse_import_data(raw: bytes, content_type: str | None = None) -> dict[str, Any]:
    """从 JSON 字符串或 ZIP 字节解析导入数据。

    返回可直接交给 import_data() 的数据字典。
    """
    # ZIP 文件魔数：优先按二进制签名判断，而非依赖 content_type
    if raw[:4] == b"PK\x03\x04":
        return _parse_zip(raw)
    try:
        result: dict[str, Any] = json.loads(raw.decode("utf-8"))
        return result
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Unsupported import format: {e}") from e


def _parse_zip(raw: bytes) -> dict[str, Any]:
    buf = io.BytesIO(raw)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        if "data.json" in names:
            result: dict[str, Any] = json.loads(zf.read("data.json").decode("utf-8"))
            return result
        if "manifest.json" in names:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            data: dict[str, Any] = {
                "version": manifest.get("version", EXPORT_VERSION),
                "memories": [],
                "candidates": [],
                "notes": [],
                "relations": [],
                "schedules": [],
            }
            for name in names:
                if name.startswith("memories/") and name.endswith(".md"):
                    data["memories"].append(_parse_markdown_memory(zf.read(name).decode("utf-8")))
                elif name.startswith("notes/") and name.endswith(".md"):
                    data["notes"].append(_parse_markdown_note(zf.read(name).decode("utf-8")))
            return data
        raise ValueError("ZIP file missing data.json or manifest.json")


def _parse_markdown_md(text: str) -> tuple[dict[str, Any], str]:
    """解析 Markdown 的 YAML frontmatter，返回 (frontmatter 字典, 正文)。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm: dict[str, Any] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.lower() == "true":
                fm[key] = True
            elif val.lower() == "false":
                fm[key] = False
            elif val.lower() == "null" or val == "":
                fm[key] = None
            else:
                try:
                    fm[key] = int(val)
                except ValueError:
                    try:
                        fm[key] = float(val)
                    except ValueError:
                        fm[key] = val
    return fm, parts[2].strip()


def _parse_markdown_memory(text: str) -> dict[str, Any]:
    fm, body = _parse_markdown_md(text)
    return {
        "id": fm.get("id"),
        "title": fm.get("title", "Imported"),
        "content": body,
        "type": fm.get("type", "fact"),
        "source": fm.get("source", "import"),
        "status": fm.get("status", "active"),
        "confidence": fm.get("confidence", 0.5),
        "importance": fm.get("importance", 0.5),
        "version": fm.get("version", 1),
        "is_permanent": fm.get("is_permanent", False),
        "created_at": fm.get("created_at"),
        "updated_at": fm.get("updated_at"),
    }


def _parse_markdown_note(text: str) -> dict[str, Any]:
    fm, body = _parse_markdown_md(text)
    return {
        "id": fm.get("id"),
        "content": body,
        "signal_type": fm.get("signal_type", "other"),
        "formalized": fm.get("formalized", False),
        "created_at": fm.get("created_at"),
    }
