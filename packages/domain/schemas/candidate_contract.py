"""结构化候选契约（MQ-201）。

定义 MemoryCandidateContract 及各记忆类型的最低完整性要求。
契约由 Agent 提炼或补全，服务端验证格式与必填项。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MemoryType = Literal[
    "fact",
    "decision",
    "lesson",
    "issue",
    "convention",
    "pattern",
    "procedure",
    "feedback",
    "reference",
    "constraint",
    "rule",
]

ConfidenceLevel = Literal["high", "medium", "low", "unverified"]


class EvidenceRef(BaseModel):
    """单条证据引用。"""

    source_type: str = Field(..., max_length=32, description="证据来源类型")
    source_ref: str = Field("", max_length=256, description="来源引用路径或标识")
    supports: str = Field("", max_length=500, description="该证据支持的具体结论")


class Applicability(BaseModel):
    """适用范围限定。"""

    workspace: str = ""
    conditions: list[str] = Field(default_factory=list, description="成立条件")
    exceptions: list[str] = Field(default_factory=list, description="例外情况")


class ActionPlan(BaseModel):
    """操作步骤与验证方法。"""

    steps: list[str] = Field(default_factory=list, description="具体步骤")
    verification: list[str] = Field(default_factory=list, description="验证方法")


class TemporalScope(BaseModel):
    """时间有效性范围。"""

    valid_from: str | None = None
    valid_until: str | None = None
    version_scope: str | None = None


class ConfidenceAssessment(BaseModel):
    """可信度评估。"""

    level: ConfidenceLevel = "medium"
    basis: str = Field("", max_length=500, description="可信度依据")


# 各类型的最低必填字段
TYPE_REQUIRED_FIELDS: dict[str, list[str]] = {
    "fact": ["claim", "context"],
    "decision": ["claim", "context", "rationale"],
    "lesson": ["claim", "context"],
    "issue": ["claim", "context"],
    "convention": ["claim"],
    "rule": ["claim"],
    "constraint": ["claim", "context"],
    "procedure": ["claim", "action"],
    "pattern": ["claim", "context"],
    "feedback": ["claim"],
    "reference": ["claim"],
}


class MemoryCandidateContract(BaseModel):
    """结构化候选契约。

    Agent 提炼时填充，服务端验证格式与完整性。
    不强制所有字段——按类型要求最低完整性。
    """

    schema_version: str = "1.0"
    title: str = Field(..., min_length=1, max_length=80)
    type: MemoryType
    claim: str = Field("", max_length=500, description="核心结论")
    context: str = Field("", max_length=2000, description="背景与原因")
    rationale: str = Field("", max_length=1000, description="决策理由与取舍")
    applicability: Applicability | None = None
    action: ActionPlan | None = None
    temporal: TemporalScope | None = None
    confidence: ConfidenceAssessment | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_type_completeness(self) -> MemoryCandidateContract:
        """按类型检查最低必填字段。"""
        required = TYPE_REQUIRED_FIELDS.get(self.type, [])
        missing: list[str] = []
        for field in required:
            value = getattr(self, field, None)
            if (
                not value
                or (isinstance(value, str) and not value.strip())
                or isinstance(value, BaseModel)
                and not any(getattr(value, f_name, None) for f_name in value.model_fields)
            ):
                missing.append(field)
        # 不抛异常——记录缺失项供质量报告使用
        return self

    def get_missing_fields(self) -> list[str]:
        """返回当前类型要求但缺失的字段列表。"""
        required = TYPE_REQUIRED_FIELDS.get(self.type, [])
        missing: list[str] = []
        for field in required:
            value = getattr(self, field, None)
            if (
                not value
                or (isinstance(value, str) and not value.strip())
                or isinstance(value, BaseModel)
                and not any(getattr(value, f_name, None) for f_name in value.model_fields)
            ):
                missing.append(field)
        return missing

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict，用于存入数据库 JSON 字段。"""
        return self.model_dump(exclude_none=True, exclude_defaults=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryCandidateContract:
        """从 dict 反序列化。"""
        return cls.model_validate(data)
