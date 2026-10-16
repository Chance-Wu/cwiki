"""公共 schema 定义。"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

# 应用版本号，供健康检查端点和 schema 默认值统一引用
APP_VERSION = "0.3.0"

# ── 枚举类型别名，供路由 Query 参数校验 ──────────────────────────
MemoryType = Literal[
    "fact",
    "decision",
    "issue",
    "convention",
    "pattern",
    "procedure",
    "feedback",
    "reference",
    "constraint",
    "lesson",
    "rule",
]
MemoryStatus = Literal[
    "active",       # 正常检索
    "superseded",   # 已被新版取代，保留历史
    "conflicted",   # 存在未解决的有效冲突
    "archived",     # 不再作为主要检索结果，保留记录
    "deprecated",   # 明确不再推荐使用
]
# 候选状态机（MQ-102/302 改造后）
CandidateStatus = Literal[
    "pending_review",     # 待人工审核
    "approved",           # 已批准，转为正式记忆
    "rejected",           # 已拒绝，隔离留存
    "merged",             # 并入既有记忆
    "deferred",           # 暂缓审核
    "needs_enrichment",   # 低分/缺失维度，需补全后再审
    "quarantined",        # 质量闸门隔离（历史兼容）
    "discarded",          # 历史值兼容
]


class HealthResponse(BaseModel):
    """健康检查响应体。"""

    status: str
    database: str = "ok"
    version: str = APP_VERSION


class ConsistencyReport(BaseModel):
    """三方数据一致性对账报告（只读，不做修复）。"""

    healthy: bool
    db_count: int = 0
    md_count: int = 0
    index_count: int = 0
    vector_count: int = 0
    # MD 缺失：DB 有而 MD 无；MD 孤儿：MD 有而 DB 无
    md_missing: list[str] = Field(default_factory=list)
    md_orphan: list[str] = Field(default_factory=list)
    # 索引缺失：DB 有而 index.db（active 行）无
    index_missing: list[str] = Field(default_factory=list)
    # 向量未覆盖的 active 记忆 id：截断展示，完整数量见 vectors_missing_total
    vectors_missing: list[str] = Field(default_factory=list)
    vectors_missing_total: int = 0
    # 载体读取失败原因，键为载体名（db/md/index/vectors），非空即不健康
    errors: dict[str, str] = Field(default_factory=dict)


class PaginatedResponse(BaseModel, Generic[T]):
    """通用分页响应。"""

    items: list[T]
    total: int
    offset: int
    limit: int
