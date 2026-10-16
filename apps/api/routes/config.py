"""运行时配置端点。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.auth import AgentIdentity
from apps.api.deps import require_scope
from packages.domain.config import (
    CONFIG_PATH,
    parasitic_evolution_config,
    reload_yaml_config,
    settings,
)

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
