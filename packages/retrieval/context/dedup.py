"""去重步骤——移除检索结果中的重复记忆。"""

from __future__ import annotations

from typing import Any

from packages.domain.text_utils import signal_tokens
from packages.memory.similarity import jaccard_from_sets
from packages.retrieval.context.conflict import has_contradiction_text


def deduplicate_with_details(
    memories: list[dict[str, Any]],
    threshold: float = 0.30,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """deduplicate 的带明细变体：额外返回每条被移除记忆的判重目标。

    返回 (保留列表, [(被移除 id, 判重目标 id)])。目标 id 即因得分更高
    而被保留的那条记忆，供上下文组装器记录 ``duplicate_of:<id>`` 级别
    的过滤原因；原 deduplicate 保留原签名作薄包装，不影响既有调用方。

    Args:
        memories: 至少含 'content' 与 'score' 键的记忆字典列表。
        threshold: 判定为重复的信号 Jaccard 相似度阈值。

    Returns:
        (去重后保留高得分条目的列表, 被移除条目与保留目标的明细) 元组。
    """
    if not memories:
        return [], []

    token_sets = [signal_tokens(m.get("content", "")) for m in memories]
    kept: list[int] = []
    removed: set[int] = set()
    details: list[tuple[str, str]] = []

    for i in range(len(memories)):
        if i in removed:
            continue
        for j in range(i + 1, len(memories)):
            if j in removed:
                continue
            sim = jaccard_from_sets(token_sets[i], token_sets[j])
            if sim >= threshold:
                if has_contradiction_text(
                    memories[i].get("content", ""), memories[j].get("content", "")
                ):
                    # 矛盾对不是重复：跳过这一对，继续检查后续组合
                    continue
                if memories[i].get("score", 0) >= memories[j].get("score", 0):
                    removed.add(j)
                    details.append((str(memories[j].get("id", "")), str(memories[i].get("id", ""))))
                else:
                    removed.add(i)
                    details.append((str(memories[i].get("id", "")), str(memories[j].get("id", ""))))
                    break
        if i not in removed:
            kept.append(i)

    return [memories[i] for i in kept], details


def deduplicate(
    memories: list[dict[str, Any]],
    threshold: float = 0.30,
) -> list[dict[str, Any]]:
    """按内容相似度移除重复记忆（薄包装，不返回判重明细）。

    发现重复时保留得分更高的一条。双方含矛盾词对（如"必须/禁止"）
    时豁免判重——互相矛盾的是互补观点而非重复，必须都进入上下文
    供冲突检测告警；否则 ctx-025 类矛盾对（信号 Jaccard 0.436 高于
    阈值）会先被去重吞掉，冲突告警随之丢失。

    默认阈值 0.30 的依据（eval-fixture 26 条 gold 全部 317 对的
    signal Jaccard 分布）：须判重的改写重复对 0.344（ctx-026）、
    字面重复对 0.817（ctx-007），非重复对最高仅 0.145——0.30 与
    改写对保持约 1.15 倍判定余量，与正常对上限保持约 2 倍安全余量。

    Args:
        memories: 至少含 'content' 与 'score' 键的记忆字典列表。
        threshold: 判定为重复的信号 Jaccard 相似度阈值。

    Returns:
        去重后保留高得分条目的列表。
    """
    if not memories:
        return []

    token_sets = [signal_tokens(m.get("content", "")) for m in memories]
    kept: list[int] = []
    removed: set[int] = set()

    for i in range(len(memories)):
        if i in removed:
            continue
        for j in range(i + 1, len(memories)):
            if j in removed:
                continue
            sim = jaccard_from_sets(token_sets[i], token_sets[j])
            if sim >= threshold:
                if has_contradiction_text(
                    memories[i].get("content", ""), memories[j].get("content", "")
                ):
                    # 矛盾对不是重复：跳过这一对，继续检查后续组合
                    continue
                if memories[i].get("score", 0) >= memories[j].get("score", 0):
                    removed.add(j)
                else:
                    removed.add(i)
                    break
        if i not in removed:
            kept.append(i)

    return [memories[i] for i in kept]
