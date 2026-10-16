"""候选三档过滤（none/demote/hard）的统一实现：过期 / 低置信 / 低相关。

职责划分（避免双重惩罚）：engine 在 rerank 之后只执行 hard 档早删——
被剔除的候选不再占用多样性名额、不参与 utility 聚合查询；assembler 在
流水线入口执行全部档位（覆盖直连组装器的调用方与评测路径）。demote
惩罚只在组装器入口生效一次，engine 对 demote/none 档直通。

relevance_floor 的取值依据（W3 定值，改动前先重跑两组评测）：
- 评测集（context gold 26 条）：分数型负例最高 0.55、正例最低 0.58、
  期望告警的矛盾对成员全部 ≥0.78——0.5 档拦下 24/28 负例且不误杀正例
  （剩余 4 条负例中 0.75 一条是改写重复、由去重负责，0.50/0.52/0.55
  三条属灰色区，宁可放行）；
- 生产实测（夹具 5 查询的 composite 分布 0.41-0.86）：强查询全部保留、
  弱查询保留头部数条——宁缺毋滥但不至于空上下文。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from packages.retrieval.ranking.temporal import STALE_DEMOTE_FACTOR, is_stale_item

logger = logging.getLogger(__name__)

# 低置信候选的 demote 惩罚因子：confidence 低于 floor 的候选分数乘 0.5——
# 与 hard 档区分（保留可见性），但使其难以与正常置信候选竞争前排
CONFIDENCE_DEMOTE_FACTOR = 0.5
# 低相关（score 低于 relevance_floor）候选的 demote 惩罚因子，语义同上
RELEVANCE_DEMOTE_FACTOR = 0.5

_VALID_MODES = ("none", "demote", "hard")

# 过滤事件：(memory_id, stage, reason)。stage 同时是 filter_reasons 里的
# 阶段名（stale/confidence/relevance_floor），reason 区分剔除与降权。
FilterEvent = tuple[str, str, str]


def normalize_mode(mode: str, name: str) -> str:
    """校验档位取值；非法值告警并按 none 处理——配置错误不阻断检索。"""
    if mode not in _VALID_MODES:
        logger.warning("未知过滤档位 %s=%r，按 none 处理", name, mode)
        return "none"
    return mode


def apply_entry_filters(
    items: list[dict[str, Any]],
    *,
    stale_mode: str = "none",
    confidence_mode: str = "none",
    confidence_floor: float = 0.0,
    relevance_mode: str = "none",
    relevance_floor: float = 0.0,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[FilterEvent]]:
    """在组装流水线入口按三档策略过滤候选。

    - 过期（valid_to 已过）按 stale_mode 处理；
    - confidence 低于 confidence_floor（且 floor > 0）按 confidence_mode 处理，
      条目缺 confidence 键时不判定（合成条目/调用方未提供的场景不误杀）；
    - score 低于 relevance_floor（且 floor > 0）按 relevance_mode 处理。

    Args:
        items: 候选记忆字典列表（至少含 score，可选 valid_to / confidence）。
        stale_mode / confidence_mode / relevance_mode: none / demote / hard。
        confidence_floor / relevance_floor: 判定阈值，<= 0 视为关闭该过滤。
        now: 过期判定的参考时间，默认当前 UTC（测试可注入固定时间）。

    Returns:
        (过滤后的候选列表, 过滤事件列表)。hard 命中即删；demote 依次累计
        （同一候选可能产生多个事件，如"过期且低分"会同时记录 stale 与
        relevance_floor），返回副本不修改输入；事件为 (memory_id, stage,
        reason) 三元组，由调用方转成 FilterReason。
    """
    stale_mode = normalize_mode(stale_mode, "stale_filter_mode")
    confidence_mode = normalize_mode(confidence_mode, "confidence_floor_mode")
    relevance_mode = normalize_mode(relevance_mode, "relevance_floor_mode")

    stale_active = stale_mode != "none"
    conf_active = confidence_mode != "none" and confidence_floor > 0
    rel_active = relevance_mode != "none" and relevance_floor > 0
    if not (stale_active or conf_active or rel_active):
        return list(items), []

    result: list[dict[str, Any]] = []
    events: list[FilterEvent] = []
    for item in items:
        mem_id = str(item.get("id", ""))
        score = item.get("score", 0)
        adjusted = score

        # 判定链不短路（仅 hard 命中即删）：stale demote 后仍继续做
        # confidence/relevance 判定，否则"过期且低分"条目会借 demote
        # 分支逃过 relevance floor（ctx-019 实测泄漏路径）
        if stale_active and is_stale_item(item, now):
            if stale_mode == "hard":
                events.append((mem_id, "stale", "expired"))
                continue
            events.append((mem_id, "stale", "expired_demoted"))
            adjusted *= STALE_DEMOTE_FACTOR

        confidence = item.get("confidence")
        if conf_active and confidence is not None and confidence < confidence_floor:
            if confidence_mode == "hard":
                events.append((mem_id, "confidence", "below_confidence_floor"))
                continue
            events.append((mem_id, "confidence", "low_confidence_demoted"))
            adjusted *= CONFIDENCE_DEMOTE_FACTOR

        if rel_active and adjusted < relevance_floor:
            if relevance_mode == "hard":
                events.append((mem_id, "relevance_floor", "below_relevance_floor"))
                continue
            events.append((mem_id, "relevance_floor", "low_relevance_demoted"))
            adjusted *= RELEVANCE_DEMOTE_FACTOR

        result.append({**item, "score": adjusted} if adjusted != score else item)

    if events:
        logger.debug("Entry filters processed %d/%d candidates", len(events), len(items))
    return result, events
