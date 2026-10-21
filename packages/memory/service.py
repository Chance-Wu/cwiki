"""记忆服务：候选复核与记忆管理的业务逻辑。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from packages.domain.config import settings
from packages.domain.errors import AppError
from packages.domain.models import CandidateMemory, Memory, MemoryLifecycleEvent, MemoryVersion
from packages.domain.text_utils import format_memory_for_embedding, normalize_memory_content
from packages.domain.types import TYPE_DEFINITIONS, validate_memory_content, validate_memory_title
from packages.memory.content_security import validate_safe_content
from packages.memory.duplicate_detection import batch_detect_duplicates_with_embedding
from packages.memory.entity_extractor import extract_entities
from packages.memory.quality_gate import check_exclusion_list, compute_quality_gate
from packages.memory.review_service import get_review_service


def normalize_tags(tags: list[str] | None) -> list[str]:
    """规范化标签列表：去空格、转小写、去重、过滤空串，保持首次出现顺序。"""
    if not tags:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        normalized = tag.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


# 判重阈值从全局配置读取，便于按部署调整
SIMILARITY_THRESHOLD = settings.similarity_threshold


async def _maybe_extract_and_store_entities(
    db: AsyncSession,
    memory: Memory,
    title: str,
    content: str,
) -> None:
    """若启用实体抽取，抽取实体并写入记忆元数据。"""
    from packages.domain.config import parasitic_evolution_config

    if parasitic_evolution_config.entity_extraction_enabled:
        combined = f"{title} {content}"
        entities = extract_entities(combined)
        if entities:
            existing_meta = dict(memory.metadata_) if memory.metadata_ else {}
            existing_meta["entities"] = entities
            memory.metadata_ = existing_meta
            # 整体重赋值 dict，确保 SQLAlchemy 追踪到 JSON 字段的变更
            await db.flush()


class ContentFormatError(AppError, ValueError):
    """写入内容非法；同时由 API 的领域错误处理器处理。"""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_memory_content", message, status_code=422)


class MemoryVersionConflict(AppError):
    """记忆版本已变化，需重新加载后再更新。"""

    def __init__(self) -> None:
        super().__init__(
            "memory_version_conflict",
            "Memory version changed; reload the memory before updating it.",
            status_code=409,
        )


class CandidateStateError(AppError):
    """候选状态不允许该操作（如重复批准）；由 API 领域错误处理器映射为 409。"""

    def __init__(self, message: str) -> None:
        super().__init__("candidate_state_conflict", message, status_code=409)


async def snapshot_and_advance(
    db: AsyncSession,
    memory: Memory,
    *,
    change_type: str,
    changed_by_type: str,
    changed_by_id: str | None = None,
    reason: str | None = None,
    expected_version: int | None = None,
    record_version: bool = True,
) -> None:
    """原子地认领当前读版本，并保留其编辑前快照。

    旧的合并行可能已对当前版本做过快照：直接复用这些行、不重写历史；
    历史快照与当前内容冲突时需人工复核。失败时调用方须回滚事务。
    """
    old_version = memory.version
    if expected_version is not None and expected_version != old_version:
        raise MemoryVersionConflict()
    now = datetime.now(UTC)
    with db.no_autoflush:
        # 乐观锁：仅当版本仍为 old_version 时才递增，否则说明已被并发修改
        result = await db.execute(
            update(Memory)
            .where(Memory.id == memory.id, Memory.version == old_version)
            .values(version=old_version + 1, updated_at=now)
            .returning(Memory.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise MemoryVersionConflict()
        if record_version:
            existing = (
                await db.execute(
                    select(MemoryVersion).where(
                        MemoryVersion.memory_id == memory.id,
                        MemoryVersion.version == old_version,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    MemoryVersion(
                        memory_id=memory.id,
                        version=old_version,
                        title=memory.title,
                        content=memory.content,
                        change_type=change_type,
                        changed_by_type=changed_by_type,
                        changed_by_id=changed_by_id,
                        reason=reason,
                    )
                )
            elif existing.title != memory.title or existing.content != memory.content:
                raise MemoryVersionConflict()
    # 同步内存对象与 UPDATE 结果，且不触发 ORM 脏检查再次写库
    set_committed_value(memory, "version", old_version + 1)
    set_committed_value(memory, "updated_at", now)


@dataclass
class SimilarItem:
    """判重时发现的相似既有记忆或候选。"""

    id: uuid.UUID
    title: str
    content_preview: str
    similarity: float
    source: str  # "memory" 或 "candidate"


def _validate_mcp_content(content: str) -> None:
    """校验内容长度/格式与注入安全。"""
    try:
        validate_memory_content(content)
        validate_safe_content(content)
    except ValueError as exc:
        raise ContentFormatError(str(exc)) from exc


# 提交时查重用的正文截断长度：足够判重，又避免加载全量内容
_CONTENT_PREVIEW_LEN = 500


def _has_token_overlap(text_a: str, text_b: str) -> bool:
    """快速预筛：两段文本是否共享任意字符二元组？

    明显不相似的项在此直接跳过，省去昂贵的相似度计算。
    """
    a_clean = text_a.replace(" ", "")
    b_clean = text_b.replace(" ", "")
    if len(a_clean) < 2 or len(b_clean) < 2:
        return False
    set_a = {a_clean[i : i + 2] for i in range(len(a_clean) - 1)}
    set_b = {b_clean[i : i + 2] for i in range(len(b_clean) - 1)}
    return bool(set_a & set_b)


async def _find_similar_in_batch(
    rows: list[Any],
    candidate_dict: dict[str, str],
    combined_text: str,
    source: str,
) -> tuple[list[SimilarItem], float | None]:
    """按 token 重叠预筛后执行批量检测（含 embedding），返回相似项列表与最高分。"""
    filtered_dicts = []
    filtered_rows = []
    for r in rows:
        if _has_token_overlap(combined_text, format_memory_for_embedding(r.title, r.content)):
            filtered_dicts.append(
                {"title": r.title, "content": r.content, "embedding": r.embedding}
            )
            filtered_rows.append(r)

    if not filtered_dicts:
        return [], None

    # 使用 embedding 增强的重复检测
    verdicts = await batch_detect_duplicates_with_embedding(candidate_dict, filtered_dicts)

    items: list[SimilarItem] = []
    max_sim: float | None = None
    for row, verdict in zip(filtered_rows, verdicts):
        if max_sim is None or verdict.combined_score > max_sim:
            max_sim = verdict.combined_score
        if verdict.combined_score >= SIMILARITY_THRESHOLD:
            items.append(
                SimilarItem(
                    id=row.id,
                    title=row.title,
                    content_preview=row.content[:200],
                    similarity=verdict.combined_score,
                    source=source,
                )
            )
    return items, max_sim


async def _find_similar_at_submit(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    title: str,
    content: str,
    limit: int = 3,
) -> tuple[list[SimilarItem], float | None]:
    """提交时查找相似的已有记忆与待审候选。

    为避免加载全量正文的优化：
    - SUBSTR 在数据库层截断正文（500 字符）以减少 I/O
    - token 集合预筛先跳过二元组零重叠的项，再做 embedding 增强判重
    """
    similar_items: list[SimilarItem] = []
    max_similarity: float | None = None

    # 只比较最近更新的 500 条记忆 / 200 条待审候选，控制判重范围
    memory_stmt = (
        select(
            Memory.id,
            Memory.title,
            func.substr(Memory.content, 1, _CONTENT_PREVIEW_LEN).label("content"),
            Memory.embedding,
        )
        .where(
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
        )
        .order_by(Memory.updated_at.desc())
        .limit(500)
    )
    memory_result = await db.execute(memory_stmt)
    memories = memory_result.all()

    candidate_stmt = (
        select(
            CandidateMemory.id,
            CandidateMemory.title,
            func.substr(CandidateMemory.content, 1, _CONTENT_PREVIEW_LEN).label("content"),
            CandidateMemory.embedding,
        )
        .where(
            CandidateMemory.workspace_id == workspace_id,
            CandidateMemory.status == "pending_review",
        )
        .order_by(CandidateMemory.created_at.desc())
        .limit(200)
    )
    candidate_result = await db.execute(candidate_stmt)
    candidates = candidate_result.all()

    candidate_dict = {"title": title, "content": content}
    combined_text = format_memory_for_embedding(title, content)

    for rows, source in [(memories, "memory"), (candidates, "candidate")]:
        if not rows:
            continue
        items, branch_max = await _find_similar_in_batch(
            list(rows), candidate_dict, combined_text, source
        )
        similar_items.extend(items)
        if branch_max is not None and (max_similarity is None or branch_max > max_similarity):
            max_similarity = branch_max

    similar_items.sort(key=lambda x: x.similarity, reverse=True)
    return similar_items[:limit], max_similarity


async def create_candidate(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    title: str,
    content: str,
    type: str,
    source: str = "mcp",
    confidence: float = 0.5,
    importance: float = 0.5,
    project_id: uuid.UUID | None = None,
    client_write_id: str | None = None,
    tags: list[str] | None = None,
) -> tuple[CandidateMemory, list[SimilarItem], bool]:
    """创建候选记忆，等待人工复核。

    提供可选的 *client_write_id* 时操作幂等：(workspace_id, client_write_id)
    重复时返回已有行，不新建。

    Returns:
        (candidate, similar_items, created) 三元组；返回已有候选时 *created* 为 False
    """
    if client_write_id:
        existing_stmt = select(CandidateMemory).where(
            CandidateMemory.workspace_id == workspace_id,
            CandidateMemory.client_write_id == client_write_id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return existing, [], False

    if type not in TYPE_DEFINITIONS:
        raise ContentFormatError(f"不支持 type={type}。可用类型：{'、'.join(TYPE_DEFINITIONS)}")
    try:
        validate_memory_title(title)
        validate_safe_content(title)
    except ValueError as exc:
        raise ContentFormatError(str(exc)) from exc
    _validate_mcp_content(content)
    content = normalize_memory_content(content)

    exclusion = check_exclusion_list(title, content)
    if exclusion.excluded:
        raise ContentFormatError(
            f"内容被排除规则拒收（{exclusion.reason}）。"
            "记忆应存储可复用的知识，不应存储可从代码/git/配置直接推导的信息。"
        )

    similar_items, max_similarity = await _find_similar_at_submit(db, workspace_id, title, content)

    candidate = CandidateMemory(
        workspace_id=workspace_id,
        project_id=project_id,
        title=title,
        content=content,
        type=type,
        tags=normalize_tags(tags),
        source=source,
        client_write_id=client_write_id,
        confidence=confidence,
        importance=importance,
        status="pending_review",
        similar_memory_id=similar_items[0].id if similar_items else None,
        similar_memory_source=similar_items[0].source if similar_items else None,
        duplicate_probability=max_similarity,
    )

    # 质量门只决定复核优先级，不拦截写入
    qg = compute_quality_gate({"type": type, "content": content})
    candidate.quality_gate_score = qg.score
    candidate.quality_gate_reason = qg.reason
    candidate.review_priority = qg.review_priority

    db.add(candidate)
    if client_write_id:
        # 用 savepoint 包裹：唯一约束冲突只回滚本次插入，不影响外层事务
        async with db.begin_nested():
            try:
                await db.flush()
            except Exception:
                # begin_nested 上下文退出时已自动回滚 savepoint
                existing_stmt = select(CandidateMemory).where(
                    CandidateMemory.workspace_id == workspace_id,
                    CandidateMemory.client_write_id == client_write_id,
                )
                existing = (await db.execute(existing_stmt)).scalar_one_or_none()
                if existing is not None:
                    return existing, [], False
                raise
    else:
        await db.flush()
    await db.refresh(candidate)
    return candidate, similar_items, True


async def approve_candidate(
    db: AsyncSession,
    candidate: CandidateMemory,
    *,
    title: str | None = None,
    content: str | None = None,
    project_id: uuid.UUID | None = None,
) -> Memory:
    """批准候选并创建正式记忆。

    可选的 title/content/project_id 覆盖候选原值。
    仅 pending_review 可批准：approved/merged/rejected 等终态候选
    重复转正会创建重复记忆（任务队列 at-least-once 重放的主要风险面）。
    """
    if candidate.status != "pending_review":
        raise CandidateStateError(
            f"Candidate is already in '{candidate.status}' status and cannot be approved"
        )
    approved_title = validate_safe_content(title if title is not None else candidate.title)
    approved_content = validate_safe_content(content if content is not None else candidate.content)
    approved_content = normalize_memory_content(approved_content)
    # 除注入安全外，再校验长度与格式
    try:
        validate_memory_title(approved_title)
        validate_memory_content(approved_content)
    except ValueError as exc:
        raise ContentFormatError(str(exc)) from exc
    if candidate.type not in TYPE_DEFINITIONS:
        raise ContentFormatError(f"Invalid candidate type: {candidate.type}")
    # or 0.5：候选缺省（0/None）的置信度/重要度回退为中性默认值
    memory = Memory(
        workspace_id=candidate.workspace_id,
        project_id=project_id if project_id is not None else candidate.project_id,
        title=approved_title,
        content=approved_content,
        type=candidate.type,
        tags=list(candidate.tags or []),
        source=candidate.source,
        confidence=candidate.confidence or 0.5,
        importance=candidate.importance or 0.5,
        status="active",
        version=1,
    )
    db.add(memory)
    candidate.status = "approved"
    await db.flush()
    await db.refresh(memory)

    await _maybe_extract_and_store_entities(db, memory, approved_title, approved_content)

    created_event = MemoryLifecycleEvent(
        id=uuid.uuid4(),
        memory_id=memory.id,
        event_type="created",
    )
    db.add(created_event)

    review_service = get_review_service()
    await review_service.schedule_memory(db, memory.id, memory.workspace_id)

    return memory


async def _finalize_merge(
    db: AsyncSession,
    candidate: CandidateMemory,
    target_memory: Memory,
) -> Memory:
    """合并后的公共收尾：清空 embedding、标记候选、flush。"""
    # 正文已变，旧向量失效，置空待重算
    target_memory.embedding = None
    candidate.status = "merged"
    await db.flush()
    await db.refresh(target_memory)
    return target_memory


async def merge_candidate(
    db: AsyncSession,
    candidate: CandidateMemory,
    target_memory: Memory,
    merged_content: str,
) -> Memory:
    """将候选内容合并进已有正式记忆。"""
    if target_memory.workspace_id != candidate.workspace_id:
        raise ContentFormatError("Cannot merge across workspaces")
    validate_safe_content(merged_content)
    try:
        validate_memory_content(merged_content)
    except ValueError as exc:
        raise ContentFormatError(str(exc)) from exc
    await snapshot_and_advance(
        db,
        target_memory,
        change_type="merge",
        changed_by_type="human",
        reason=f"Merged from candidate {candidate.id}",
    )
    target_memory.content = normalize_memory_content(merged_content)

    await _maybe_extract_and_store_entities(
        db, target_memory, target_memory.title, target_memory.content
    )

    return await _finalize_merge(db, candidate, target_memory)


async def update_candidate_into(
    db: AsyncSession,
    candidate: CandidateMemory,
    target_memory: Memory,
) -> Memory:
    """用候选内容整体替换已有记忆。

    用于候选是某条已有记忆的修正/更新版本的场景。
    """
    if target_memory.workspace_id != candidate.workspace_id:
        raise ContentFormatError("Cannot update across workspaces")
    validate_safe_content(candidate.title)
    validate_safe_content(candidate.content)
    await snapshot_and_advance(
        db,
        target_memory,
        change_type="update",
        changed_by_type="human",
        reason=f"Updated from candidate {candidate.id}",
    )
    target_memory.title = candidate.title
    target_memory.content = candidate.content

    await _maybe_extract_and_store_entities(
        db, target_memory, target_memory.title, target_memory.content
    )

    return await _finalize_merge(db, candidate, target_memory)
