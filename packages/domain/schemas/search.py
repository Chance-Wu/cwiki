"""Search、Context、ProactivePush 与检索调试相关 schema。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """搜索记忆。"""

    workspace_id: str | None = Field(
        default=None,
        description="Workspace name or UUID; omit to search across all workspaces",
    )
    keyword: str = Field(description="Search keyword text")
    project_id: UUID | None = None
    memory_type: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = Field(
        default=None,
        description="Filter by tags; only memories containing all specified tags are returned",
    )
    status: str | None = Field(default=None, max_length=32)
    filters: dict[str, Any] | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # 最低向量相似度门槛：低于该值的候选被剔除（无 embedding 的候选视同 0），
    # 用于拦截乱码/无关查询的凑数结果；不传则不过滤
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    # 关联的 Agent 会话；用于把召回命中归因到会话（可选）
    session_id: UUID | None = None
    # 自动召回等隐私敏感场景可关闭 trace；默认记录，保持现有诊断能力
    record_trace: bool = Field(default=True, description="是否记录检索 trace")
    # hybrid：BM25 + 向量双路（默认）；semantic：仅向量路，共享同一套过滤与重排
    mode: str = Field(
        default="hybrid",
        pattern="^(hybrid|semantic)$",
        description="hybrid=双路召回；semantic=仅语义向量路（过滤/重排仍生效）",
    )


class SearchResult(BaseModel):
    """单条搜索结果。"""

    id: UUID
    title: str
    content: str
    type: str
    tags: list[str] = Field(default_factory=list)
    version: int = 1
    score: float | None = Field(default=None, description="Similarity score")
    confidence: float | None = Field(default=None, description="Memory confidence (0-1)")
    valid_to: str | None = Field(default=None, description="Expiry timestamp (ISO 8601)")
    is_stale: bool = Field(default=False, description="Whether the memory has expired")


class SearchResponse(BaseModel):
    """搜索结果集。"""

    results: list[SearchResult] = Field(default_factory=list)
    total: int
    keyword: str
    insufficient: bool = Field(
        default=False,
        description="True 表示无相关性候选，results 为按重要度返回的兜底列表（score 恒为 0）",
    )
    insufficient_reason: str | None = Field(
        default=None,
        description="insufficient 为 true 时的原因说明",
    )
    degraded: list[str] = Field(
        default_factory=list,
        description="检索降级标记：embedding_fallback（语义向量不可用）等",
    )


class ContextRequest(BaseModel):
    """为 Agent 会话拉取相关上下文的请求。"""

    workspace_id: str
    agent_id: UUID
    session_id: UUID
    project_id: UUID | None = None
    keyword: str | None = Field(default=None, description="Natural language keyword")
    max_items: int = Field(default=10, ge=1, le=50)
    max_tokens: int = Field(default=5000, ge=100, le=20000)
    event_types: list[str] | None = Field(default=None, description="Filter by event types")
    limit: int = Field(default=50, ge=1, le=500)
    include_memories: bool = True
    include_entities: bool = True
    mode: str = Field(default="semantic", description="Retrieval mode: semantic, episodic, hybrid")


class ContextItem(BaseModel):
    """返回的单条上下文条目。"""

    memory_id: UUID | None = None
    type: str = Field(description="Item type: memory, entity, event")
    id: UUID
    title: str
    content: str
    version: int | None = None
    score: float | None = Field(default=None, description="Relevance score")
    source: str = "memory"
    metadata: dict[str, Any] | None = None


class ContextResponse(BaseModel):
    """上下文检索响应。"""

    context: str = ""
    items: list[ContextItem] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    total: int = 0
    keyword: str | None = None
    latency_ms: int = 0
    degraded: list[str] = Field(
        default_factory=list,
        description="检索降级标记：embedding_fallback / vector_search_failed",
    )


class ProactivePushRequest(BaseModel):
    """主动记忆推送请求。"""

    workspace_id: str
    session_id: UUID
    keywords: list[str] = Field(default_factory=list, max_length=10)
    max_items: int = Field(default=3, ge=1, le=10)


class ProactivePushItem(BaseModel):
    """单条被主动推送的记忆。"""

    memory_id: UUID
    title: str
    snippet: str
    relevance: float
    push_reason: str


class ProactivePushResponse(BaseModel):
    """主动记忆推送响应。"""

    items: list[ProactivePushItem] = Field(default_factory=list)
    total: int = 0
