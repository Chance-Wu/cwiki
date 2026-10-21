"""记忆相关 schema：Memory、CandidateMemory、Evidence、Review、Feedback、Conflict。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from packages.domain.types import validate_memory_content, validate_memory_title
from packages.memory.content_security import validate_safe_content

# 写入侧统一校验入口：先做领域校验（标题/长度），再做安全内容校验
MemoryTitle = Annotated[
    str, AfterValidator(validate_memory_title), AfterValidator(validate_safe_content)
]
MemoryContent = Annotated[
    str, AfterValidator(validate_memory_content), AfterValidator(validate_safe_content)
]


class MemoryCreate(BaseModel):
    workspace_id: str
    project_id: UUID | None = None
    title: MemoryTitle
    content: MemoryContent
    type: str = Field(..., max_length=64)
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    importance: float = 0.5
    content_contract: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    title: str
    content: str
    type: str
    tags: list[str] = Field(default_factory=list)
    source: str = "mcp"
    status: str
    confidence: float
    importance: float
    version: int
    valid_from: datetime | None
    valid_to: datetime | None
    usage_count: int
    is_permanent: bool = False
    permanent_reason: str | None = None
    last_used_at: datetime | None
    # 列表端点现场批量计算的效用分；None 表示未计算（聚合降级/详情端点），
    # 与"算出为 0"区分——0 是合法效用分（先验底分约 0.145，几乎不会为 0）
    utility_score: float | None = None
    content_contract: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> list[str]:
        return v if isinstance(v, list) else []


class MemoryUpdate(BaseModel):
    """更新已确认记忆的载荷。"""

    # 乐观锁：提供时与当前 version 比对，不匹配则拒绝，防止并发更新互相覆盖
    expected_version: int | None = Field(default=None, ge=1)
    title: MemoryTitle | None = None
    content: MemoryContent | None = None
    tags: list[str] | None = None
    status: str | None = None
    confidence: float | None = None
    importance: float | None = None
    reason: str | None = None
    is_permanent: bool | None = None
    permanent_reason: str | None = None
    change_summary: str | None = None


class MemoryVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    memory_id: UUID
    version: int
    title: str
    content: str
    change_type: str
    changed_by_type: str
    changed_by_id: str | None = None
    reason: str | None = None
    created_at: datetime


class CandidateMemoryCreate(BaseModel):
    workspace_id: str
    project_id: UUID | None = None
    episode_id: UUID | None = None
    title: MemoryTitle
    content: MemoryContent
    type: str = Field(..., max_length=64)
    tags: list[str] = Field(default_factory=list)
    source: str = Field("mcp", max_length=32)
    client_write_id: str | None = Field(default=None, max_length=64)
    confidence: float | None = None
    importance: float | None = None
    novelty: float | None = None
    reusability: float | None = None
    stability: float | None = None
    future_utility: float | None = None
    actionability: float | None = None
    evidence_strength: float | None = None
    scope_confidence: float | None = None
    quality_score: float | None = None
    value_score: float | None = None
    quality_gate_score: float | None = None
    quality_gate_reason: str | None = None
    review_priority: float | None = None
    duplicate_probability: float | None = None


class CandidateMemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    workspace_name: str | None = None
    project_id: UUID | None
    episode_id: UUID | None
    title: str
    content: str
    type: str
    tags: list[str] = Field(default_factory=list)
    source: str
    client_write_id: str | None = None
    confidence: float | None
    importance: float | None
    novelty: float | None
    reusability: float | None
    stability: float | None
    future_utility: float | None
    actionability: float | None
    evidence_strength: float | None
    scope_confidence: float | None
    quality_score: float | None
    value_score: float | None
    quality_gate_score: float | None
    quality_gate_reason: str | None
    review_priority: float | None
    duplicate_probability: float | None
    similar_memory_id: UUID | None
    similar_memory_source: str | None
    similar_memory_title: str | None = None
    similar_memory_content_preview: str | None = None
    similar_memory_type: str | None = None
    similar_memory_relation: str | None = None
    status: str
    content_contract: dict[str, Any] | None = None
    quality_report: dict[str, Any] | None = None
    relation_decision: dict[str, Any] | None = None
    extraction_version: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> list[str]:
        return v if isinstance(v, list) else []


class SimilarItemRead(BaseModel):
    """提交去重检查时发现的相似既有记忆或候选。"""

    id: UUID
    title: str
    content_preview: str = Field(..., max_length=200)
    similarity: float
    source: str  # 取值："memory" 或 "candidate"


class CandidateMemoryCreateResponse(BaseModel):
    """候选创建响应，附带去重检查发现的相似项。"""

    candidate: CandidateMemoryRead
    similar_items: list[SimilarItemRead] = []
    hint: str | None = None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    memory_id: UUID | None
    candidate_id: UUID | None
    episode_id: UUID | None
    event_id: UUID | None
    source_type: str
    source_ref: str | None
    content: str | None
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    created_at: datetime


class ReviewCreate(BaseModel):
    candidate_id: UUID
    reviewer_type: str = Field(..., max_length=32)
    reviewer_id: str | None = Field(default=None, max_length=128)
    action: str = Field(..., max_length=32)
    before_content: str | None = None
    after_content: str | None = None
    reason: str | None = None
    edited_title: MemoryTitle | None = None
    edited_content: MemoryContent | None = None
    merge_target_memory_id: UUID | None = None
    merged_content: MemoryContent | None = None
    project_id: UUID | None = None


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    candidate_id: UUID
    reviewer_type: str
    reviewer_id: str | None
    action: str
    before_content: str | None
    after_content: str | None
    reason: str | None
    created_at: datetime


class MemoryFeedbackCreate(BaseModel):
    workspace_id: str
    memory_id: UUID
    feedback_type: str = Field(
        ...,
        max_length=32,
        description="useful, not_useful, outdated, wrong",
        pattern=r"^(useful|not_useful|outdated|wrong)$",
    )
    source_type: str = Field(..., max_length=32, description="human, agent, auto")
    source_id: str | None = Field(default=None, max_length=128)
    reason: str | None = None


class MemoryFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    memory_id: UUID
    feedback_type: str
    source_type: str
    source_id: str | None
    reason: str | None
    created_at: datetime


class MemoryFeedbackListResponse(BaseModel):
    """单条记忆的反馈明细列表（按时间倒序）。

    items 复用 MemoryFeedbackRead：source_type 区分 human/agent/auto，
    source_id 即反馈来源的 agent 名（人工反馈为空）。
    """

    memory_id: UUID
    total: int
    items: list[MemoryFeedbackRead]


class MemoryRetrievalHit(BaseModel):
    """该记忆在一次检索中的命中明细。

    signals / filter_reasons 取自 trace 的 metadata（W3 起落库），
    metadata 缺失（explain 关闭或旧数据）时保持空默认。
    """

    trace_id: UUID
    query: str
    # trace 创建时间，即该次检索发生的时间
    retrieved_at: datetime
    # 该记忆在当次结果中的名次；旧数据可能未记录名次
    rank: int | None = None
    score: float | None = None
    used: bool = False
    signals: dict[str, float] = Field(default_factory=dict)
    filter_reasons: list[dict[str, str]] = Field(default_factory=list)


class MemoryRetrievalHistory(BaseModel):
    """记忆详情-检索命中历史响应：最近在哪些查询中被命中、名次与过滤原因。"""

    memory_id: UUID
    # 该记忆被检索命中的总次数（items 受 limit 截断，total 用于"还有更多"提示）
    total: int
    items: list[MemoryRetrievalHit]


class MemoryConflictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    memory_id: UUID
    candidate_id: UUID | None
    conflict_type: str
    description: str | None
    evidence: dict[str, Any] | None
    status: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


class ReviewItemRead(BaseModel):
    """到期待复习的记忆条目。"""

    memory_id: UUID
    title: str
    content: str
    memory_type: str
    ease_factor: float
    interval_days: int
    repetitions: int
    next_review: datetime
    last_review: datetime | None
    days_overdue: int
    mastery_level: str
    total_reviews: int


class ReviewSubmitRequest(BaseModel):
    """提交单次复习结果。"""

    quality: int = Field(..., ge=0, le=5, description="Quality rating: 0-5")


class ReviewResultRead(BaseModel):
    """复习提交后由调度算法重算的结果。"""

    memory_id: UUID
    ease_factor: float
    interval_days: int
    repetitions: int
    next_review: datetime
    last_review: datetime
    mastery_level: str
    total_reviews: int


class ReviewStatsRead(BaseModel):
    """workspace 的复习统计。"""

    total_scheduled: int
    due_now: int
    due_today: int
    reviewed_today: int
    mastery_distribution: dict[str, int]
    review_trend: list[dict[str, str | int]] = []


class BatchReviewItem(BaseModel):
    """批量提交中的单条复习。"""

    memory_id: UUID
    quality: int = Field(..., ge=0, le=5, description="Quality rating: 0-5")


class BatchReviewRequest(BaseModel):
    """一次批量提交多条复习。"""

    reviews: list[BatchReviewItem] = Field(..., min_length=1, max_length=100)


class BatchReviewResultItem(BaseModel):
    """批量提交中单条复习的处理结果。"""

    memory_id: UUID
    success: bool
    error: str | None = None
    result: ReviewResultRead | None = None


class RelationCreate(BaseModel):
    """手动创建记忆关系。"""

    target_memory_id: UUID
    relation_type: str = Field(
        ...,
        max_length=50,
        pattern=r"^(related|supports|contradicts|supersedes|refines)$",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RelationUpdate(BaseModel):
    """更新已有关系的类型或置信度。"""

    relation_type: str | None = Field(
        default=None,
        max_length=50,
        pattern=r"^(related|supports|contradicts|supersedes|refines)$",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TagRenameRequest(BaseModel):
    """标签重命名。"""

    new_name: str = Field(..., min_length=1, max_length=64)


class TagMergeRequest(BaseModel):
    """将多个标签合并为一个。"""

    source_tags: list[str] = Field(..., min_length=2, max_length=20)
    target_tag: str = Field(..., min_length=1, max_length=64)


class BatchReviewResultRead(BaseModel):
    """批量复习提交的响应。"""

    results: list[BatchReviewResultItem]
    total: int
    succeeded: int
    failed: int
