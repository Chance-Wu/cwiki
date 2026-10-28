"""记忆服务：候选复核与记忆管理的业务逻辑。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from packages.domain.config import agent_policy_config, settings
from packages.domain.errors import AppError, WriteDecisionRejected
from packages.domain.models import (
    CandidateMemory,
    Evidence,
    Memory,
    MemoryLifecycleEvent,
    MemoryVersion,
    Workspace,
)
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


def union_tags(*tag_lists: list[str] | None) -> list[str]:
    """合并多组标签并规范化，保持首次出现顺序。"""
    return normalize_tags([tag for tags in tag_lists for tag in (tags or [])])


# 判重阈值从全局配置读取，便于按部署调整
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


# 提交时查重：扫描范围与是否跨工作区由 memory.* 配置控制
def _submit_dedup_scope() -> tuple[int, bool]:
    return settings.submit_dedup_scan_limit, settings.submit_dedup_cross_workspace


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
        if verdict.combined_score >= settings.similarity_threshold:
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

    扫描范围由 memory.submit_dedup_scan_limit 控制；默认同工作区，
    memory.submit_dedup_cross_workspace=true 时跨全部工作区比对。
    正文取全文（不再截断）——词面预筛已能跳过大部分无关项。
    """
    similar_items: list[SimilarItem] = []
    max_similarity: float | None = None

    scan_limit, cross_workspace = _submit_dedup_scope()
    memory_conditions = [Memory.status == "active"]
    candidate_conditions = [CandidateMemory.status == "pending_review"]
    if not cross_workspace:
        memory_conditions.append(Memory.workspace_id == workspace_id)
        candidate_conditions.append(CandidateMemory.workspace_id == workspace_id)

    memory_stmt = (
        select(
            Memory.id,
            Memory.title,
            Memory.content,
            Memory.embedding,
        )
        .where(*memory_conditions)
        .order_by(Memory.updated_at.desc())
        .limit(scan_limit)
    )
    memory_result = await db.execute(memory_stmt)
    memories = memory_result.all()

    candidate_stmt = (
        select(
            CandidateMemory.id,
            CandidateMemory.title,
            CandidateMemory.content,
            CandidateMemory.embedding,
        )
        .where(*candidate_conditions)
        .order_by(CandidateMemory.created_at.desc())
        .limit(scan_limit)
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


async def _workspace_name_for_policy(db: AsyncSession, workspace_id: uuid.UUID) -> str:
    result = await db.execute(select(Workspace.name).where(Workspace.id == workspace_id))
    return result.scalar_one_or_none() or ""


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
    episode_id: uuid.UUID | None = None,
    client_write_id: str | None = None,
    legacy_client_write_id: str | None = None,
    tags: list[str] | None = None,
    is_permanent: bool = False,
    permanent_reason: str | None = None,
) -> tuple[CandidateMemory, list[SimilarItem], bool]:
    """创建候选记忆，等待人工复核。

    提供可选的 *client_write_id* 时操作幂等：(workspace_id, client_write_id)
    重复时返回已有行，不新建。

    Returns:
        (candidate, similar_items, created) 三元组；返回已有候选时 *created* 为 False
    """
    write_ids = [wid for wid in (client_write_id, legacy_client_write_id) if wid]
    if write_ids:
        existing_stmt = (
            select(CandidateMemory)
            .where(
                CandidateMemory.workspace_id == workspace_id,
                CandidateMemory.client_write_id.in_(write_ids),
            )
            .limit(1)
        )
        existing = (await db.execute(existing_stmt)).scalars().first()
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

    normalized_tags = normalize_tags(tags)
    need_workspace_name = (
        settings.write_policy.enabled or agent_policy_config.write_decisions.enabled
    )
    workspace_name = (
        await _workspace_name_for_policy(db, workspace_id) if need_workspace_name else ""
    )

    decision_action: str | None = None
    decision_rule_id: str | None = None
    decision_reason: str | None = None
    if agent_policy_config.write_decisions.enabled:
        decision = agent_policy_config.write_decisions.decide(
            workspace_name=workspace_name,
            workspace_id=str(workspace_id),
            memory_type=type,
            tags=normalized_tags,
            title=title,
            content=content,
        )
        decision_action = decision.action
        decision_rule_id = decision.rule_id
        decision_reason = decision.reason
        if decision.action == "skip":
            if decision.rule_id:
                message = f"内容被写入决策规则拒绝（规则 {decision.rule_id}）"
            else:
                message = "未命中任何写入决策规则，默认动作 skip 拒绝写入"
            if decision.reason:
                message += f"：{decision.reason}"
            raise WriteDecisionRejected(
                action="skip",
                rule_id=decision.rule_id,
                message=message,
                reason=decision.reason,
            )

    policy_decision = None
    if settings.write_policy.enabled:
        policy_decision = settings.write_policy.decide(
            workspace_name=workspace_name,
            workspace_id=str(workspace_id),
            memory_type=type,
            tags=normalized_tags,
            title=title,
            content=content,
        )
        if policy_decision is not None and policy_decision.action == "reject":
            detail = f"内容被写入策略拒绝（规则 {policy_decision.rule_id}）"
            if policy_decision.reason:
                detail += f"：{policy_decision.reason}"
            raise ContentFormatError(detail)

    similar_items, max_similarity = await _find_similar_at_submit(db, workspace_id, title, content)

    if decision_action == "update":
        target = next(
            (
                item
                for item in similar_items
                if item.source == "memory" and item.similarity >= settings.consolidate_threshold
            ),
            None,
        )
        if target is not None:
            message = (
                f"内容命中了更新规则（规则 {decision_rule_id}），"
                f"已存在相似记忆「{target.title}」（相似度 {target.similarity:.0%}），"
                "请使用 memory_update 更新该记忆，而不是新建。"
            )
            raise WriteDecisionRejected(
                action="update",
                rule_id=decision_rule_id,
                message=message,
                reason=decision_reason,
                target_memory_id=str(target.id),
                target_title=target.title,
                similarity=target.similarity,
            )
        fallback = agent_policy_config.write_decisions.default_action
        if fallback == "skip":
            message = (
                f"写入决策规则要求更新（规则 {decision_rule_id}），但未找到可更新的相似记忆；"
                "默认动作 skip 拒绝写入。"
            )
            raise WriteDecisionRejected(
                action="skip",
                rule_id=decision_rule_id,
                message=message,
                reason=decision_reason,
            )
        decision_action = fallback
        suffix = f"（未找到可更新目标，回退默认动作 {fallback}）"
        decision_reason = (decision_reason or "") + suffix

    # 永久声明由提交方显式给出；非永久候选不保留无意义的原因文本
    permanent_reason = (permanent_reason or "").strip() or None
    if not is_permanent:
        permanent_reason = None

    candidate = CandidateMemory(
        workspace_id=workspace_id,
        project_id=project_id,
        episode_id=episode_id,
        title=title,
        content=content,
        type=type,
        tags=normalized_tags,
        is_permanent=is_permanent,
        permanent_reason=permanent_reason,
        policy_rule_id=policy_decision.rule_id if policy_decision else None,
        policy_action=policy_decision.action if policy_decision else None,
        policy_reason=policy_decision.reason if policy_decision else None,
        decision_rule_id=decision_rule_id,
        decision_action=decision_action,
        decision_reason=decision_reason,
        source=source,
        client_write_id=client_write_id,
        confidence=confidence,
        importance=importance,
        status="pending_review",
        similar_memory_id=similar_items[0].id if similar_items else None,
        similar_memory_source=similar_items[0].source if similar_items else None,
        duplicate_probability=max_similarity,
    )

    # 质量门只决定复核优先级，不拦截写入。
    # 关联了 episode 的候选带外部证据（Evidence 表），否则证据维按正文内证评估
    gate_input: dict[str, Any] = {"type": type, "content": content}
    if episode_id is not None:
        evidence_count = await db.scalar(
            select(func.count(Evidence.id)).where(Evidence.episode_id == episode_id)
        )
        if evidence_count:
            gate_input["evidence_count"] = int(evidence_count)
    qg = compute_quality_gate(gate_input)
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
        is_permanent=candidate.is_permanent,
        permanent_reason=candidate.permanent_reason if candidate.is_permanent else None,
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
    # 候选的永久声明不能因合并而丢失
    if candidate.is_permanent:
        target_memory.is_permanent = True
        if candidate.permanent_reason:
            target_memory.permanent_reason = candidate.permanent_reason

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
