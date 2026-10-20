"""时态排序——按时间有效性为记忆打分与过滤（PRD 第 20 节）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from packages.domain.time_utils import days_since

# 时态打分的天数阈值：7 天内新近、30 天内中等、90 天以上陈旧。
_RECENT_DAYS = 7
_MODERATE_DAYS = 30
_STALE_DAYS = 90

# demote 档的过期惩罚因子：过期记忆乘 0.3 后，即使检索分 0.9 也只剩
# 0.27，低于 temporal_score 无有效期时的陈旧档（90 天以上 0.4）下限——
# 语义上"内容已过有效期"不应好于"90 天未更新"；不取更低值是为了
# 让强相关的过期记忆在列表尾部仍可见，而非完全不可见（那是 hard 档）。
STALE_DEMOTE_FACTOR = 0.3


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """确保 datetime 带时区（naive 值按 UTC 处理）。"""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def is_stale_item(item: dict[str, Any], now: datetime | None = None) -> bool:
    """判断单条记忆是否已过有效期（valid_to 已过期）。

    与 temporal_score 的过期判定同源：valid_to 非空且早于 now 即过期。
    尚未生效（valid_from 在未来）不算过期——那是"预置内容"，另有
    temporal_score 的分档处理。

    Args:
        item: 记忆字典，可选 valid_to 键（缺失视为不过期）。
        now: 参考时间，默认当前 UTC（测试可注入固定时间）。

    Returns:
        过期返回 True。
    """
    valid_to = _ensure_aware(item.get("valid_to"))
    if valid_to is None:
        return False
    ref = datetime.now(UTC) if now is None else _ensure_aware(now)
    assert ref is not None
    return valid_to < ref


def apply_stale_filter(
    items: list[dict[str, Any]],
    mode: str = "none",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """按过期状态过滤记忆列表（三档策略，供组装/重排挂点调用）。

    - none：现状行为，过期项原样保留（temporal_score 已给 0.1 底分参与排序）；
    - demote：过期项 score 乘 STALE_DEMOTE_FACTOR（不改其余字段，返回副本）；
    - hard：直接剔除过期项。

    Args:
        items: 记忆字典列表，可选 valid_to / score 键。
        mode: 过滤档位，none / demote / hard。
        now: 参考时间，默认当前 UTC（测试可注入固定时间）。

    Returns:
        按档位处理后的列表（不修改输入元素，demote 返回新字典）。

    Raises:
        ValueError: mode 不是 none / demote / hard。
    """
    if mode == "none":
        # 现状档：不干预，仅返回同序副本避免调用方误共享列表
        return list(items)
    if mode not in ("demote", "hard"):
        raise ValueError(f"未知的过期过滤档位: {mode!r}（可选 none/demote/hard）")

    result: list[dict[str, Any]] = []
    for item in items:
        if is_stale_item(item, now):
            if mode == "hard":
                continue
            result.append({**item, "score": item.get("score", 0) * STALE_DEMOTE_FACTOR})
        else:
            result.append(item)
    return result


def temporal_score(
    valid_from: datetime | None,
    valid_to: datetime | None,
    created_at: datetime | None,
    last_used_at: datetime | None,
    ignore_expiry: bool = False,
    now: datetime | None = None,
) -> float:
    """计算时态分。

    Args:
        ignore_expiry: 历史意图查询豁免——查询明确问"X 出来之前/演进"等
            往事时，过期记忆正是答案，跳过过期 0.1 底分分支，改按
            last_used/created 分档（此时新旧不构成相关性证据）。
        now: 参考时间，默认当前 UTC（测试可注入固定时间）。
    """
    now = _ensure_aware(now) if now is not None else datetime.now(UTC)
    assert now is not None

    valid_from = _ensure_aware(valid_from)
    valid_to = _ensure_aware(valid_to)
    created_at = _ensure_aware(created_at)
    last_used_at = _ensure_aware(last_used_at)

    # 已过有效期：保留 0.1 底分而非清零——参与排序但几乎必然沉底
    if not ignore_expiry and valid_to and valid_to < now:
        return 0.1

    if valid_from and valid_from > now:
        # 尚未生效：超 90 天视为无效（0.1），短期预置内容给中档 0.5
        days_until = (valid_from - now).total_seconds() / 86400
        if days_until > _STALE_DAYS:
            return 0.1
        return 0.5

    if valid_from and valid_from <= now:
        return 1.0

    # 无显式有效期时按时间衰减：最近使用优先于创建时间，
    # 分档降级而非线性衰减，拉开新旧记忆的区分度
    if last_used_at:
        days_since_use = days_since(last_used_at, now)
        if days_since_use < _RECENT_DAYS:
            return 0.95
        if days_since_use < _MODERATE_DAYS:
            return 0.8
        if days_since_use < _STALE_DAYS:
            return 0.6
        return 0.4

    if created_at:
        days_since_create = days_since(created_at, now)
        if days_since_create < _RECENT_DAYS:
            return 0.7
        if days_since_create < _MODERATE_DAYS:
            return 0.5
        return 0.3

    return 0.5
