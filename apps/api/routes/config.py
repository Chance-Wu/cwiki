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
    LOCAL_CONFIG_PATH,
    agent_policy_config,
    parasitic_evolution_config,
    reload_yaml_config,
    settings,
)
from packages.domain.write_decisions import build_agent_hint, parse_write_decisions
from packages.domain.write_policy import parse_write_policy

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
    auto_merge_threshold: float
    episodic_retrieval_enabled: bool


class MemoryConfigModel(BaseModel):
    title_max_length: int
    consolidate_threshold: float
    similarity_threshold: float
    relation_merge_threshold: float
    relation_update_threshold: float
    relation_conflict_threshold: float
    priority_discard_threshold: float
    priority_low_threshold: float
    priority_high_threshold: float


class PerformanceConfigModel(BaseModel):
    context_cache_ttl: float
    context_cache_max_size: int
    context_token_budget: int
    dedup_top_k: int
    merge_suggestions_limit: int
    merge_suggestions_top_k: int
    merge_suggestions_threshold: float
    auto_consolidate_limit: int
    auto_consolidate_top_k: int


class RetrievalConfigModel(BaseModel):
    bm25_weight: float
    vector_weight: float
    reranker_rrf_weight: float
    reranker_semantic_weight: float
    reranker_confidence_weight: float
    reranker_importance_weight: float
    reranker_freshness_weight: float
    reranker_usage_weight: float
    reranker_intent_weight: float
    reranker_key_term_bonus: float


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

    workspace: list[str] = Field(default_factory=list, max_length=20)
    type: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    keyword: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("workspace", "type", "tags", "keyword")
    @classmethod
    def _clean_values(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > 100:
                raise ValueError("单个匹配值不能超过 100 字符")
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
    rules: list[WriteRuleModel] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> WritePolicyModel:
        seen: set[str] = set()
        for rule in self.rules:
            key = rule.id.casefold()
            if key in seen:
                raise ValueError(f"规则 id 重复：{rule.id}")
            seen.add(key)
        return self


class WritePolicyData(WritePolicyModel):
    storage_path: str


class WriteDecisionRuleModel(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    action: Literal["write", "skip", "update"]
    description: str = Field(default="", max_length=300)
    examples: list[str] = Field(default_factory=list, max_length=5)
    match: WriteRuleMatchModel = Field(default_factory=WriteRuleMatchModel)

    @field_validator("examples")
    @classmethod
    def _clean_examples(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > 120:
                raise ValueError("单条示例不能超过 120 字符")
            if text not in cleaned:
                cleaned.append(text)
        return cleaned


class WriteDecisionModel(BaseModel):
    enabled: bool = False
    default_action: Literal["write", "skip"] = "write"
    rules: list[WriteDecisionRuleModel] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> WriteDecisionModel:
        seen: set[str] = set()
        for rule in self.rules:
            key = rule.id.casefold()
            if key in seen:
                raise ValueError(f"规则 id 重复：{rule.id}")
            seen.add(key)
        return self


class WriteDecisionData(WriteDecisionModel):
    storage_path: str
    preview: str


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
        storage_path=str(LOCAL_CONFIG_PATH),
    )


def _read_local_config() -> dict[str, Any]:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    with open(LOCAL_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _write_local_write_policy(body: WritePolicyModel) -> None:
    """写入 config.local.yaml，保留该文件中的其他设备本地覆盖项。

    不写 config.yaml：运行时策略属于本机操作偏好，且避免 PyYAML 重写
    共享配置文件时丢失注释。
    """
    data = _read_local_config()
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
    with open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
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
        storage_path=str(LOCAL_CONFIG_PATH),
        preview=build_agent_hint(policy, ""),
    )


def _write_local_write_decisions(body: WriteDecisionModel) -> None:
    data = _read_local_config()
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
    with open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
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
    """更新写入决策：写入 config.local.yaml 并即时重载。"""
    parsed = parse_write_decisions(body.model_dump())
    if (
        parsed.enabled != body.enabled
        or parsed.default_action != body.default_action
        or len(parsed.rules) != len(body.rules)
    ):
        raise HTTPException(status_code=422, detail="写入决策校验失败：部分规则无法解析")

    await asyncio.to_thread(_write_local_write_decisions, body)
    reload_yaml_config()
    settings.reload()
    agent_policy_config.reload()
    return _effective_write_decisions()


@router.get("/v1/config/write-policy", response_model=WritePolicyData)
async def get_write_policy() -> WritePolicyData:
    """获取当前生效的写入策略。"""
    return _effective_write_policy()


@router.put("/v1/config/write-policy", response_model=WritePolicyData)
async def update_write_policy(
    body: WritePolicyModel,
    _identity: Annotated[AgentIdentity, Depends(require_scope("config:write"))],
) -> WritePolicyData:
    """更新写入策略：写入 config.local.yaml 并即时重载运行时配置。"""
    parsed = parse_write_policy(body.model_dump())
    if parsed.enabled != body.enabled or len(parsed.rules) != len(body.rules):
        raise HTTPException(status_code=422, detail="写入策略校验失败：部分规则无法解析")

    await asyncio.to_thread(_write_local_write_policy, body)
    reload_yaml_config()
    settings.reload()
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
            merge_suggestions_limit=settings.merge_suggestions_limit,
            merge_suggestions_top_k=settings.merge_suggestions_top_k,
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

    # 读取当前配置
    if CONFIG_PATH.exists():

        def _read_config() -> dict[str, Any]:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

        config_data = await asyncio.to_thread(_read_config)
    else:
        config_data = {}

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
