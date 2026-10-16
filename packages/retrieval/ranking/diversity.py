"""多样性过滤——保证最终结果覆盖不同记忆类型（PRD 第 21 节）。"""

from __future__ import annotations


def apply_diversity(
    ranked: list[tuple[str, float, str]],
    top_k: int = 10,
    max_per_type: int = 3,
) -> list[tuple[str, float, str]]:
    """过滤排序结果以保证类型多样性。

    贪心策略：按得分顺序扫描，同类型超过上限即跳过，
    让低分异类型记忆补位，避免单一类型霸榜。

    Args:
        ranked: (memory_id, score, memory_type) 元组列表，已按得分排序。
        top_k: 返回结果上限。
        max_per_type: 同类型记忆的最大数量。

    Returns:
        保持多样性的过滤结果。
    """
    top_k = max(1, top_k)
    max_per_type = max(1, max_per_type)
    type_counts: dict[str, int] = {}
    result: list[tuple[str, float, str]] = []

    for memory_id, score, mem_type in ranked:
        count = type_counts.get(mem_type, 0)
        if count >= max_per_type:
            continue
        type_counts[mem_type] = count + 1
        result.append((memory_id, score, mem_type))
        if len(result) >= top_k:
            break

    return result
