"""从 config.yaml 加载的数据库与应用配置。"""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
LOCAL_CONFIG_PATH = CONFIG_PATH.with_name("config.local.yaml")

API_V1_PREFIX = "/v1"

_DEFAULT_RERANKER_WEIGHTS: dict[str, float] = {
    "rrf_weight": 0.38,
    "semantic_weight": 0.15,
    "confidence_weight": 0.10,
    "importance_weight": 0.12,
    "freshness_weight": 0.10,
    "usage_weight": 0.06,
    "intent_weight": 0.09,
    "key_term_bonus": 0.08,
}

_DEFAULT_MEMORY_TITLE_MAX_LENGTH = 80

# 安全默认值：单用户本地部署只监听回环地址，CORS 仅放行前端 Vite dev 源。
# 手机/局域网设备访问属于显式放开，由用户改 config.yaml 覆盖，代码不做兜底放宽
_DEFAULT_API_HOST = "127.0.0.1"
_DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
_DEFAULT_MEMORY_THRESHOLDS: dict[str, float] = {
    "consolidate": 0.85,
    "similarity": 0.70,
    "relation_merge": 0.95,
    "relation_update": 0.80,
    "relation_conflict": 0.60,
    "priority_discard": 0.35,
    "priority_low": 0.65,
    "priority_high": 0.85,
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """将 *override* 递归合并进 *base* 的副本。

    冲突键的处理：两边都是 dict 时继续递归合并，否则以 override 的值为准。
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml_config() -> dict[str, Any]:
    """加载 config.yaml，若存在 config.local.yaml 则叠加其覆盖项。"""
    config: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    if LOCAL_CONFIG_PATH.exists():
        with open(LOCAL_CONFIG_PATH, encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        if local:
            logger.info("Merging config.local.yaml overrides")
            config = _deep_merge(config, local)

    return config


_yaml_config = _load_yaml_config()


def reload_yaml_config() -> dict[str, Any]:
    """重新从磁盘读取 config.yaml，并更新模块级缓存。"""
    global _yaml_config
    _yaml_config = _load_yaml_config()
    return _yaml_config


class Settings:
    """从 config.yaml 加载的应用设置。

    敏感字段支持环境变量覆盖：
    - CWIKI_OPENAI_API_KEY 覆盖 app.openai_api_key
    """

    def __init__(self) -> None:
        db_cfg = _yaml_config.get("database", {})
        app_cfg = _yaml_config.get("app", {})

        self.database_url: str = db_cfg.get("url", "sqlite+aiosqlite:///./cwiki-data/cwiki.db")
        self.embedding_dimensions: int = app_cfg.get("embedding_dimensions", 1536)
        self.openai_api_key: str = os.environ.get(
            "CWIKI_OPENAI_API_KEY", app_cfg.get("openai_api_key", "")
        )
        self.embedding_model: str = app_cfg.get("embedding_model", "BAAI/bge-small-zh-v1.5")
        self.app_name: str = app_cfg.get("app_name", "cwiki")
        self.debug: bool = app_cfg.get("debug", False)
        self.api_host: str = app_cfg.get("api_host", _DEFAULT_API_HOST)
        self.api_port: int = app_cfg.get("api_port", 5172)
        # list() 拷贝避免外部修改 settings.cors_origins 时污染模块级默认值
        self.cors_origins: list[str] = app_cfg.get("cors_origins", list(_DEFAULT_CORS_ORIGINS))
        # 本机 API 鉴权 token（app.auth_token）：默认空 = 不鉴权，保持单用户
        # 本地零配置体验；配置后受保护端点要求 Authorization: Bearer <token>。
        # 建议 token 写在 config.local.yaml（随设备、不入代码仓库）
        self.api_auth_token: str = app_cfg.get("auth_token", "")

        self._load_runtime_fields()

    def _load_runtime_fields(self) -> None:
        """加载检索与记忆相关字段，供 __init__ 和 reload 共用。"""
        retrieval_cfg = _yaml_config.get("retrieval", {})
        self.bm25_weight = retrieval_cfg.get("bm25_weight", 0.4)
        self.vector_weight = retrieval_cfg.get("vector_weight", 0.6)
        self.reranker_rrf_weight = retrieval_cfg.get(
            "reranker_rrf_weight", _DEFAULT_RERANKER_WEIGHTS["rrf_weight"]
        )
        self.reranker_semantic_weight = retrieval_cfg.get(
            "reranker_semantic_weight", _DEFAULT_RERANKER_WEIGHTS["semantic_weight"]
        )
        self.reranker_confidence_weight = retrieval_cfg.get(
            "reranker_confidence_weight", _DEFAULT_RERANKER_WEIGHTS["confidence_weight"]
        )
        self.reranker_importance_weight = retrieval_cfg.get(
            "reranker_importance_weight", _DEFAULT_RERANKER_WEIGHTS["importance_weight"]
        )
        self.reranker_freshness_weight = retrieval_cfg.get(
            "reranker_freshness_weight", _DEFAULT_RERANKER_WEIGHTS["freshness_weight"]
        )
        self.reranker_usage_weight = retrieval_cfg.get(
            "reranker_usage_weight", _DEFAULT_RERANKER_WEIGHTS["usage_weight"]
        )
        self.reranker_intent_weight = retrieval_cfg.get(
            "reranker_intent_weight", _DEFAULT_RERANKER_WEIGHTS["intent_weight"]
        )
        self.reranker_key_term_bonus = retrieval_cfg.get(
            "reranker_key_term_bonus", _DEFAULT_RERANKER_WEIGHTS["key_term_bonus"]
        )
        # 效用分权重：上下文优先级排序中同优先级内按 score + w×utility 排序，
        # 让「检索到且实际有用」的记忆在同分候选中更靠前
        self.utility_weight: float = retrieval_cfg.get("utility_weight", 0.15)
        # 检索可解释性：开启时把各路信号分项与逐条过滤原因写入 trace 的
        # metadata JSON 列（零迁移），供排查检索质量问题；关闭时不落库
        self.explain_enabled: bool = retrieval_cfg.get("explain_enabled", True)
        # 候选过滤三档策略（none/demote/hard）：过期（valid_to 已过）与低置信
        # 候选的处理档位。默认 demote——压分保留可见性，而非直接剔除；
        # 是否升 hard 由检索评测的负例数据决定（回退风险高时保持 demote）
        self.stale_filter_mode: str = retrieval_cfg.get("stale_filter_mode", "demote")
        self.confidence_floor_mode: str = retrieval_cfg.get("confidence_floor_mode", "demote")
        # 低置信判定阈值：confidence 低于它的候选按 confidence_floor_mode 处理；
        # 0 表示关闭该过滤（等价 none 档）
        self.confidence_floor: float = retrieval_cfg.get("confidence_floor", 0.3)
        # 相关性下限三档策略：按检索综合分（score）剔除/降权明显不相关候选。
        # 默认 none 的原因（W3 阈值扫描实测）：rerank composite 在小候选池上
        # min-max 归一化失去区分度（单候选全 0），精确命中场景 composite 仅
        # 0.34-0.45，hard 阈值会把唯一结果清场；top10 正常分布（0.54+）与
        # NEG 又无可靠分离点（median 0.527 vs 0.485）。该过滤适用场景是
        # score 语义明确的调用方（如 context 评测的手造池分 0.3-0.95），
        # 生产检索链路保持关闭，负例拦截依赖检索器排序质量本身
        self.relevance_floor_mode: str = retrieval_cfg.get("relevance_floor_mode", "none")
        self.relevance_floor: float = retrieval_cfg.get("relevance_floor", 0.5)

        memory_cfg = _yaml_config.get("memory", {})
        self.memory_title_max_length = memory_cfg.get(
            "title_max_length", _DEFAULT_MEMORY_TITLE_MAX_LENGTH
        )
        self.consolidate_threshold = memory_cfg.get(
            "consolidate_threshold", _DEFAULT_MEMORY_THRESHOLDS["consolidate"]
        )
        self.similarity_threshold = memory_cfg.get(
            "similarity_threshold", _DEFAULT_MEMORY_THRESHOLDS["similarity"]
        )
        self.relation_merge_threshold = memory_cfg.get(
            "relation_merge_threshold", _DEFAULT_MEMORY_THRESHOLDS["relation_merge"]
        )
        self.relation_update_threshold = memory_cfg.get(
            "relation_update_threshold", _DEFAULT_MEMORY_THRESHOLDS["relation_update"]
        )
        self.relation_conflict_threshold = memory_cfg.get(
            "relation_conflict_threshold", _DEFAULT_MEMORY_THRESHOLDS["relation_conflict"]
        )
        self.priority_discard_threshold = memory_cfg.get(
            "priority_discard_threshold", _DEFAULT_MEMORY_THRESHOLDS["priority_discard"]
        )
        self.priority_low_threshold = memory_cfg.get(
            "priority_low_threshold", _DEFAULT_MEMORY_THRESHOLDS["priority_low"]
        )
        self.priority_high_threshold = memory_cfg.get(
            "priority_high_threshold", _DEFAULT_MEMORY_THRESHOLDS["priority_high"]
        )

        # 三档审核：高分候选自动生效（默认关，灰度放量）
        self.auto_approve_enabled: bool = memory_cfg.get("auto_approve_enabled", False)
        self.auto_approve_value_threshold: float = memory_cfg.get(
            "auto_approve_value_threshold", 0.85
        )
        self.auto_approve_confidence_threshold: float = memory_cfg.get(
            "auto_approve_confidence_threshold", 0.8
        )
        self.auto_approve_gate_threshold: float = memory_cfg.get(
            "auto_approve_gate_threshold", 0.75
        )
        self.auto_approve_duplicate_threshold: float = memory_cfg.get(
            "auto_approve_duplicate_threshold", 0.4
        )

        # 相似度计算策略：jaccard | embedding | hybrid
        self.similarity_strategy: str = memory_cfg.get("similarity_strategy", "hybrid")
        # 混合策略权重（仅 hybrid 策略生效）
        hybrid_weights = memory_cfg.get("similarity_hybrid_weights", {})
        self.similarity_hybrid_weights = {
            "title": hybrid_weights.get("title", 0.20),
            "content": hybrid_weights.get("content", 0.35),
            "keyword": hybrid_weights.get("keyword", 0.15),
            "embedding": hybrid_weights.get("embedding", 0.30),
        }

        perf_cfg = _yaml_config.get("performance", {})
        self.context_cache_ttl: float = perf_cfg.get("context_cache_ttl", 30.0)
        self.context_cache_max_size: int = perf_cfg.get("context_cache_max_size", 256)
        self.context_token_budget: int = perf_cfg.get("context_token_budget", 2000)
        self.dedup_top_k: int = perf_cfg.get("dedup_top_k", 20)
        self.merge_suggestions_limit: int = perf_cfg.get("merge_suggestions_limit", 100)
        self.merge_suggestions_top_k: int = perf_cfg.get("merge_suggestions_top_k", 10)
        self.merge_suggestions_threshold: float = perf_cfg.get("merge_suggestions_threshold", 0.5)
        self.auto_consolidate_limit: int = perf_cfg.get("auto_consolidate_limit", 500)
        self.auto_consolidate_top_k: int = perf_cfg.get("auto_consolidate_top_k", 20)

    @property
    def is_sqlite(self) -> bool:
        """是否为 SQLite —— 决定连接池与 PRAGMA 配置策略。"""
        return self.database_url.startswith("sqlite")

    def reload(self) -> None:
        """从 config.yaml 刷新运行时可编辑字段。"""
        app_cfg = _yaml_config.get("app", {})
        self.debug = app_cfg.get("debug", False)
        self.cors_origins = app_cfg.get("cors_origins", list(_DEFAULT_CORS_ORIGINS))
        self.api_auth_token = app_cfg.get("auth_token", "")
        self._load_runtime_fields()


settings = Settings()


class ParasiticEvolutionConfig:
    """寄生式记忆演化的功能开关（渐进式放量）。

    只保留仍有生产代码引用的开关；常开（P0/P1 已稳定）或从未使用的
    开关已移除，以降低配置复杂度。
    """

    def __init__(self) -> None:
        self._load_flags()

    def _load_flags(self) -> None:
        """从 config.yaml 加载功能开关。"""
        cfg = _yaml_config.get("parasitic_evolution", {})
        self.memory_gap_detection_enabled: bool = cfg.get("memory_gap_detection_enabled", False)
        self.proactive_push_enabled: bool = cfg.get("proactive_push_enabled", False)
        self.memory_relations_enabled: bool = cfg.get("memory_relations_enabled", False)
        self.relation_reinforcement_enabled: bool = cfg.get("relation_reinforcement_enabled", False)
        self.relation_reinforcement_rate: float = float(cfg.get("relation_reinforcement_rate", 0.2))
        self.relation_decay_half_life_days: float = float(
            cfg.get("relation_decay_half_life_days", 30.0)
        )
        self.agent_profile_enabled: bool = cfg.get("agent_profile_enabled", False)
        self.memory_version_tracking_enabled: bool = cfg.get(
            "memory_version_tracking_enabled", False
        )
        self.auto_consolidate_enabled: bool = cfg.get("auto_consolidate_enabled", False)
        self.review_reminders_enabled: bool = cfg.get("review_reminders_enabled", False)
        self.mastery_coupled_decay_enabled: bool = cfg.get("mastery_coupled_decay_enabled", False)
        self.entity_extraction_enabled: bool = cfg.get("entity_extraction_enabled", False)
        self.write_time_conflict_enabled: bool = cfg.get("write_time_conflict_enabled", False)
        self.auto_merge_enabled: bool = cfg.get("auto_merge_enabled", False)
        self.auto_merge_threshold: float = cfg.get("auto_merge_threshold", 0.92)
        self.episodic_retrieval_enabled: bool = cfg.get("episodic_retrieval_enabled", False)
        # 基于 episode 的 problems/solutions 信号按规则生成 lesson 候选（零 LLM 调用）
        self.episode_candidate_extraction_enabled: bool = cfg.get(
            "episode_candidate_extraction_enabled", False
        )

    def reload(self) -> None:
        """从 config.yaml 刷新全部功能开关。"""
        self._load_flags()


parasitic_evolution_config = ParasiticEvolutionConfig()


class SchedulerConfig:
    """周期调度器间隔配置（小时）。"""

    def __init__(self) -> None:
        cfg = _yaml_config.get("scheduler", {})
        self.auto_consolidate_interval_hours: float = cfg.get("auto_consolidate_interval_hours", 6)
        self.review_reminders_interval_hours: float = cfg.get("review_reminders_interval_hours", 24)
        self.meta_export_interval_hours: float = cfg.get("meta_export_interval_hours", 12)


scheduler_config = SchedulerConfig()


class SkillsConfig:
    """技能系统配置 —— 支持技能加载的 Agent 类型。"""

    def __init__(self) -> None:
        cfg = _yaml_config.get("skills", {})
        agents_cfg = cfg.get("agents", {})

        self.agents: dict[str, dict[str, Path]] = {}
        for name, agent_cfg in agents_cfg.items():
            skills_dir = agent_cfg.get("skills_dir")
            if not skills_dir:
                continue
            entry: dict[str, Path] = {"skills_dir": Path(skills_dir).expanduser()}
            plugins_dir = agent_cfg.get("plugins_dir")
            if plugins_dir:
                entry["plugins_dir"] = Path(plugins_dir).expanduser()
            self.agents[name] = entry

        # skills/import 允许导入的源路径前缀；空列表 = 不限制
        raw_paths = cfg.get("import_allowed_paths", [])
        self.import_allowed_paths: list[Path] = [Path(p).expanduser().resolve() for p in raw_paths]


skills_config = SkillsConfig()
