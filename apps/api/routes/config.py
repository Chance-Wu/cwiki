"""运行时配置端点。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from apps.api.auth import AgentIdentity
from apps.api.deps import require_scope
from packages.domain.config import (
    CONFIG_PATH,
    agent_policy_config,
    parasitic_evolution_config,
    reload_yaml_config,
    settings,
)
from packages.domain.write_decisions import (
    DEFAULT_MAX_HINT_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_EXAMPLE_CHARS,
    MAX_EXAMPLES,
    MAX_KEYWORD_VALUES,
    MAX_MATCH_VALUE_CHARS,
    MAX_MATCH_VALUES,
    MAX_RULES,
    build_agent_hint_details,
    parse_write_decisions,
)
from packages.domain.write_policy import parse_write_policy

WRITE_POLICY_MAX_RULES = 50

router = APIRouter(tags=["config"])


class AppConfig(BaseModel):
    debug: bool


class ParasiticEvolutionConfigModel(BaseModel):
    memory_gap_detection_enabled: bool
    proactive_push_enabled: bool
    memory_relations_enabled: bool
    agent_profile_enabled: bool
    memory_version_tracking_enabled: bool
    auto_consolidate_enabled: bool
    review_reminders_enabled: bool
    mastery_coupled_decay_enabled: bool
    entity_extraction_enabled: bool
    write_time_conflict_enabled: bool
    auto_merge_enabled: bool
    auto_merge_threshold: float = Field(ge=0.0, le=1.0)
    episodic_retrieval_enabled: bool


class MemoryConfigModel(BaseModel):
    title_max_length: int = Field(ge=1, le=500)
    consolidate_threshold: float = Field(ge=0.0, le=1.0)
    similarity_threshold: float = Field(ge=0.0, le=1.0)
    relation_merge_threshold: float = Field(ge=0.0, le=1.0)
    relation_update_threshold: float = Field(ge=0.0, le=1.0)
    relation_conflict_threshold: float = Field(ge=0.0, le=1.0)
    priority_discard_threshold: float = Field(ge=0.0, le=1.0)
    priority_low_threshold: float = Field(ge=0.0, le=1.0)
    priority_high_threshold: float = Field(ge=0.0, le=1.0)


class PerformanceConfigModel(BaseModel):
    context_cache_ttl: float = Field(ge=0.0, le=86400.0)
    context_cache_max_size: int = Field(ge=1, le=100_000)
    context_token_budget: int = Field(ge=64, le=200_000)
    dedup_top_k: int = Field(ge=1, le=1_000)
    merge_suggestions_threshold: float = Field(ge=0.0, le=1.0)
    auto_consolidate_limit: int = Field(ge=1, le=100_000)
    auto_consolidate_top_k: int = Field(ge=1, le=1_000)


class RetrievalConfigModel(BaseModel):
    bm25_weight: float = Field(ge=0.0, le=10.0)
    vector_weight: float = Field(ge=0.0, le=10.0)
    reranker_rrf_weight: float = Field(ge=0.0, le=10.0)
    reranker_semantic_weight: float = Field(ge=0.0, le=10.0)
    reranker_confidence_weight: float = Field(ge=0.0, le=10.0)
    reranker_importance_weight: float = Field(ge=0.0, le=10.0)
    reranker_freshness_weight: float = Field(ge=0.0, le=10.0)
    reranker_usage_weight: float = Field(ge=0.0, le=10.0)
    reranker_intent_weight: float = Field(ge=0.0, le=10.0)
    reranker_key_term_bonus: float = Field(ge=0.0, le=10.0)


class SystemInfoModel(BaseModel):
    embedding_model: str
    embedding_dimensions: int
    database_url: str
    api_host: str
    api_port: int
    memory_dir: str
    config_path: str


class ConfigData(BaseModel):
    app: AppConfig
    parasitic_evolution: ParasiticEvolutionConfigModel
    memory: MemoryConfigModel
    performance: PerformanceConfigModel
    retrieval: RetrievalConfigModel
    system_info: SystemInfoModel


class ConfigPatchBody(BaseModel):
    """经过校验的 PATCH 请求体，仅包含已知配置段。"""

    app: AppConfig | None = None
    parasitic_evolution: ParasiticEvolutionConfigModel | None = None
    memory: MemoryConfigModel | None = None
    performance: PerformanceConfigModel | None = None
    retrieval: RetrievalConfigModel | None = None


class ConfigPatchResult(BaseModel):
    applied: bool
    changed_fields: list[str]


class WriteRuleMatchModel(BaseModel):
    """规则匹配条件；空列表表示该维度不限制。"""

    workspace: list[str] = Field(default_factory=list, max_length=MAX_MATCH_VALUES)
    type: list[str] = Field(default_factory=list, max_length=MAX_MATCH_VALUES)
    tags: list[str] = Field(default_factory=list, max_length=MAX_MATCH_VALUES)
    keyword: list[str] = Field(default_factory=list, max_length=MAX_KEYWORD_VALUES)

    @field_validator("workspace", "type", "tags", "keyword")
    @classmethod
    def _clean_values(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > MAX_MATCH_VALUE_CHARS:
                raise ValueError(f"单个匹配值不能超过 {MAX_MATCH_VALUE_CHARS} 字符")
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(text)
        return cleaned


class WriteRuleModel(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    action: Literal["auto", "review", "reject"]
    reason: str | None = Field(default=None, max_length=500)
    match: WriteRuleMatchModel = Field(default_factory=WriteRuleMatchModel)


class WritePolicyModel(BaseModel):
    enabled: bool = False
    rules: list[WriteRuleModel] = Field(default_factory=list, max_length=WRITE_POLICY_MAX_RULES)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> WritePolicyModel:
        seen: set[str] = set()
        for rule in self.rules:
            key = rule.id.casefold()
            if key in seen:
                raise ValueError(f"规则 id 重复：{rule.id}")
            seen.add(key)
        return self


class WritePolicyLimits(BaseModel):
    """前端计数器与预校验使用的硬限制，与服务端校验同源。"""

    max_rules: int
    max_match_values: int
    max_keyword_values: int
    max_match_value_chars: int


def _write_policy_limits() -> WritePolicyLimits:
    return WritePolicyLimits(
        max_rules=WRITE_POLICY_MAX_RULES,
        max_match_values=MAX_MATCH_VALUES,
        max_keyword_values=MAX_KEYWORD_VALUES,
        max_match_value_chars=MAX_MATCH_VALUE_CHARS,
    )


class WritePolicyData(WritePolicyModel):
    storage_path: str
    limits: WritePolicyLimits


class WriteDecisionRuleModel(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    action: Literal["write", "skip", "update"]
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    examples: list[str] = Field(default_factory=list, max_length=MAX_EXAMPLES)
    match: WriteRuleMatchModel = Field(default_factory=WriteRuleMatchModel)

    @field_validator("examples")
    @classmethod
    def _clean_examples(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > MAX_EXAMPLE_CHARS:
                raise ValueError(f"单条示例不能超过 {MAX_EXAMPLE_CHARS} 字符")
            if text not in cleaned:
                cleaned.append(text)
        return cleaned


class WriteDecisionModel(BaseModel):
    enabled: bool = False
    default_action: Literal["write", "skip"] = "write"
    rules: list[WriteDecisionRuleModel] = Field(default_factory=list, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> WriteDecisionModel:
        seen: set[str] = set()
        for rule in self.rules:
            key = rule.id.casefold()
            if key in seen:
                raise ValueError(f"规则 id 重复：{rule.id}")
            seen.add(key)
        return self


class WriteDecisionLimits(BaseModel):
    """前端计数器与预校验使用的硬限制，与服务端校验同源。"""

    max_rules: int
    max_description: int
    max_examples: int
    max_example_chars: int
    max_match_values: int
    max_keyword_values: int
    max_match_value_chars: int
    max_hint_chars: int


def _write_decision_limits() -> WriteDecisionLimits:
    return WriteDecisionLimits(
        max_rules=MAX_RULES,
        max_description=MAX_DESCRIPTION_CHARS,
        max_examples=MAX_EXAMPLES,
        max_example_chars=MAX_EXAMPLE_CHARS,
        max_match_values=MAX_MATCH_VALUES,
        max_keyword_values=MAX_KEYWORD_VALUES,
        max_match_value_chars=MAX_MATCH_VALUE_CHARS,
        max_hint_chars=DEFAULT_MAX_HINT_CHARS,
    )


class WriteDecisionData(WriteDecisionModel):
    storage_path: str
    preview: str
    limits: WriteDecisionLimits


class WriteDecisionPreviewRequest(BaseModel):
    """草稿预览请求；规则按原始字典接收，允许编辑中的无效规则被跳过。"""

    enabled: bool = True
    default_action: str = "write"
    rules: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_RULES)
    workspace: str = Field(default="", max_length=100)


class WriteDecisionPreview(BaseModel):
    preview: str
    length: int
    max_chars: int
    shown_rules: int
    total_rules: int
    truncated: bool
    skipped_rules: int


# 段名 → Pydantic 模型，兼作可写字段白名单
_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "app": AppConfig,
    "parasitic_evolution": ParasiticEvolutionConfigModel,
    "performance": PerformanceConfigModel,
    "memory": MemoryConfigModel,
    "retrieval": RetrievalConfigModel,
}


def _get_memory_dir() -> str:
    """从 config.yaml 读取 storage.memory_dir。"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return str(data.get("storage", {}).get("memory_dir", "./cwiki-data"))
    return "./cwiki-data"


def _effective_write_policy() -> WritePolicyData:
    policy = settings.write_policy
    return WritePolicyData(
        enabled=policy.enabled,
        rules=[
            WriteRuleModel(
                id=rule.id,
                action=rule.action,
                reason=rule.reason,
                match=WriteRuleMatchModel(
                    workspace=list(rule.workspaces),
                    type=list(rule.types),
                    tags=list(rule.tags),
                    keyword=list(rule.keywords),
                ),
            )
            for rule in policy.rules
        ],
        storage_path=str(CONFIG_PATH),
        limits=_write_policy_limits(),
    )


def _read_config_file() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _write_write_policy(body: WritePolicyModel) -> None:
    """写入 config.yaml，保留配置中的其他段。"""
    data = _read_config_file()
    memory = data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        data["memory"] = memory

    rules: list[dict[str, Any]] = []
    for rule in body.rules:
        match = {
            "workspace": rule.match.workspace,
            "type": rule.match.type,
            "tags": rule.match.tags,
            "keyword": rule.match.keyword,
        }
        entry: dict[str, Any] = {
            "id": rule.id,
            "action": rule.action,
            "match": {key: value for key, value in match.items() if value},
        }
        if rule.reason:
            entry["reason"] = rule.reason
        rules.append(entry)

    memory["write_policy"] = {"enabled": body.enabled, "rules": rules}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _effective_write_decisions() -> WriteDecisionData:
    policy = agent_policy_config.write_decisions
    return WriteDecisionData(
        enabled=policy.enabled,
        default_action=policy.default_action,
        rules=[
            WriteDecisionRuleModel(
                id=rule.id,
                action=rule.action,
                description=rule.description,
                examples=list(rule.examples),
                match=WriteRuleMatchModel(
                    workspace=list(rule.workspaces),
                    type=list(rule.types),
                    tags=list(rule.tags),
                    keyword=list(rule.keywords),
                ),
            )
            for rule in policy.rules
        ],
        storage_path=str(CONFIG_PATH),
        preview=build_agent_hint_details(policy, "").text,
        limits=_write_decision_limits(),
    )


def _write_write_decisions(body: WriteDecisionModel) -> None:
    data = _read_config_file()
    agent_policy = data.get("agent_policy")
    if not isinstance(agent_policy, dict):
        agent_policy = {}
        data["agent_policy"] = agent_policy

    rules: list[dict[str, Any]] = []
    for rule in body.rules:
        entry: dict[str, Any] = {
            "id": rule.id,
            "action": rule.action,
            "match": {
                key: value
                for key, value in {
                    "workspace": rule.match.workspace,
                    "type": rule.match.type,
                    "tags": rule.match.tags,
                    "keyword": rule.match.keyword,
                }.items()
                if value
            },
        }
        if rule.description:
            entry["description"] = rule.description
        if rule.examples:
            entry["examples"] = list(rule.examples)
        rules.append(entry)

    agent_policy["write_decisions"] = {
        "enabled": body.enabled,
        "default_action": body.default_action,
        "rules": rules,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


@router.get("/v1/config/write-decisions", response_model=WriteDecisionData)
async def get_write_decisions() -> WriteDecisionData:
    """获取当前生效的写入决策规则与注入预览。"""
    return _effective_write_decisions()


@router.put("/v1/config/write-decisions", response_model=WriteDecisionData)
async def update_write_decisions(
    body: WriteDecisionModel,
    _identity: Annotated[AgentIdentity, Depends(require_scope("config:write"))],
) -> WriteDecisionData:
    """更新写入决策：写入 config.yaml 并即时重载。"""
    parsed = parse_write_decisions(body.model_dump())
    if (
        parsed.enabled != body.enabled
        or parsed.default_action != body.default_action
        or len(parsed.rules) != len(body.rules)
    ):
        parsed_ids = {rule.id.casefold() for rule in parsed.rules}
        failed = [rule.id for rule in body.rules if rule.id.casefold() not in parsed_ids]
        detail = "写入决策校验失败：部分规则无法解析"
        if failed:
            detail += f"（{', '.join(failed)}）"
        raise HTTPException(status_code=422, detail=detail)

    await asyncio.to_thread(_write_write_decisions, body)
    reload_yaml_config()
    settings.reload()
    agent_policy_config.reload()
    return _effective_write_decisions()


@router.post("/v1/config/write-decisions/preview", response_model=WriteDecisionPreview)
async def preview_write_decisions(body: WriteDecisionPreviewRequest) -> WriteDecisionPreview:
    """按草稿内容生成会话注入预览，支持模拟工作区过滤。"""
    raw = body.model_dump(exclude={"workspace"})
    policy = parse_write_decisions(raw, quiet=True)
    details = build_agent_hint_details(policy, body.workspace.strip())
    return WriteDecisionPreview(
        preview=details.text,
        length=details.length,
        max_chars=details.max_chars,
        shown_rules=details.shown_rules,
        total_rules=details.total_rules,
        truncated=details.truncated,
        skipped_rules=max(0, len(body.rules) - len(policy.rules)),
    )


@router.get("/v1/config/write-policy", response_model=WritePolicyData)
async def get_write_policy() -> WritePolicyData:
    """获取当前生效的写入策略。"""
    return _effective_write_policy()


@router.put("/v1/config/write-policy", response_model=WritePolicyData)
async def update_write_policy(
    body: WritePolicyModel,
    _identity: Annotated[AgentIdentity, Depends(require_scope("config:write"))],
) -> WritePolicyData:
    """更新写入策略：写入 config.yaml 并即时重载运行时配置。"""
    parsed = parse_write_policy(body.model_dump())
    if parsed.enabled != body.enabled or len(parsed.rules) != len(body.rules):
        raise HTTPException(status_code=422, detail="写入策略校验失败：部分规则无法解析")

    await asyncio.to_thread(_write_write_policy, body)
    reload_yaml_config()
    settings.reload()
    agent_policy_config.reload()
    return _effective_write_policy()


@router.get("/v1/config", response_model=ConfigData)
async def get_config() -> ConfigData:
    """获取当前运行时配置。"""
    return ConfigData(
        app=AppConfig(debug=settings.debug),
        parasitic_evolution=ParasiticEvolutionConfigModel(
            memory_gap_detection_enabled=parasitic_evolution_config.memory_gap_detection_enabled,
            proactive_push_enabled=parasitic_evolution_config.proactive_push_enabled,
            memory_relations_enabled=parasitic_evolution_config.memory_relations_enabled,
            agent_profile_enabled=parasitic_evolution_config.agent_profile_enabled,
            memory_version_tracking_enabled=parasitic_evolution_config.memory_version_tracking_enabled,
            auto_consolidate_enabled=parasitic_evolution_config.auto_consolidate_enabled,
            review_reminders_enabled=parasitic_evolution_config.review_reminders_enabled,
            mastery_coupled_decay_enabled=parasitic_evolution_config.mastery_coupled_decay_enabled,
            entity_extraction_enabled=parasitic_evolution_config.entity_extraction_enabled,
            write_time_conflict_enabled=parasitic_evolution_config.write_time_conflict_enabled,
            auto_merge_enabled=parasitic_evolution_config.auto_merge_enabled,
            auto_merge_threshold=parasitic_evolution_config.auto_merge_threshold,
            episodic_retrieval_enabled=parasitic_evolution_config.episodic_retrieval_enabled,
        ),
        memory=MemoryConfigModel(
            title_max_length=settings.memory_title_max_length,
            consolidate_threshold=settings.consolidate_threshold,
            similarity_threshold=settings.similarity_threshold,
            relation_merge_threshold=settings.relation_merge_threshold,
            relation_update_threshold=settings.relation_update_threshold,
            relation_conflict_threshold=settings.relation_conflict_threshold,
            priority_discard_threshold=settings.priority_discard_threshold,
            priority_low_threshold=settings.priority_low_threshold,
            priority_high_threshold=settings.priority_high_threshold,
        ),
        performance=PerformanceConfigModel(
            context_cache_ttl=settings.context_cache_ttl,
            context_cache_max_size=settings.context_cache_max_size,
            context_token_budget=settings.context_token_budget,
            dedup_top_k=settings.dedup_top_k,
            merge_suggestions_threshold=settings.merge_suggestions_threshold,
            auto_consolidate_limit=settings.auto_consolidate_limit,
            auto_consolidate_top_k=settings.auto_consolidate_top_k,
        ),
        retrieval=RetrievalConfigModel(
            bm25_weight=settings.bm25_weight,
            vector_weight=settings.vector_weight,
            reranker_rrf_weight=settings.reranker_rrf_weight,
            reranker_semantic_weight=settings.reranker_semantic_weight,
            reranker_confidence_weight=settings.reranker_confidence_weight,
            reranker_importance_weight=settings.reranker_importance_weight,
            reranker_freshness_weight=settings.reranker_freshness_weight,
            reranker_usage_weight=settings.reranker_usage_weight,
            reranker_intent_weight=settings.reranker_intent_weight,
            reranker_key_term_bonus=settings.reranker_key_term_bonus,
        ),
        system_info=SystemInfoModel(
            embedding_model=settings.embedding_model,
            embedding_dimensions=settings.embedding_dimensions,
            database_url=settings.database_url,
            api_host=settings.api_host,
            api_port=settings.api_port,
            memory_dir=await asyncio.to_thread(_get_memory_dir),
            config_path=str(CONFIG_PATH),
        ),
    )


@router.patch("/v1/config", response_model=ConfigPatchResult)
async def patch_config(
    body: ConfigPatchBody,
    _identity: Annotated[AgentIdentity, Depends(require_scope("config:write"))],
) -> ConfigPatchResult:
    """更新运行时配置并持久化到 config.yaml。"""
    changed_fields: list[str] = []
    config_data = await asyncio.to_thread(_read_config_file)

    # 逐段应用已知配置段的变更
    for section_name in _SECTION_MODELS:
        section_data = getattr(body, section_name, None)
        if section_data is None:
            continue
        if section_name not in config_data:
            config_data[section_name] = {}
        # 只更新请求中显式提供的字段
        for key, value in section_data.model_dump(exclude_unset=True).items():
            if config_data[section_name].get(key) != value:
                config_data[section_name][key] = value
                changed_fields.append(f"{section_name}.{key}")

    # 写回 config.yaml
    if changed_fields:

        def _write_config() -> None:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(
                    config_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
                )

        await asyncio.to_thread(_write_config)

        # 重新加载内存中的配置对象
        reload_yaml_config()
        settings.reload()
        parasitic_evolution_config.reload()

    return ConfigPatchResult(applied=bool(changed_fields), changed_fields=changed_fields)
