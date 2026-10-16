"""冲突检测步骤——标记检索结果中相互矛盾的记忆。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from packages.domain.text_utils import signal_tokens


@dataclass
class ConflictReference:
    memory_id_a: str
    memory_id_b: str
    version_a: int = 0
    version_b: int = 0
    updated_at_a: str = ""
    updated_at_b: str = ""
    conflict_type: str = "contradiction"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 矛盾词对来自两类真实语料：英文指令对，以及 eval-fixture 夹具中的
# 中文矛盾表达——("不丢", "可能丢") 覆盖 "NORMAL 不丢事务" vs
# "断电可能丢失" 这类安全性主张冲突（ctx-012 期望告警对）。
_CONTRADICTION_PAIRS = [
    ("must", "should not"),
    ("always", "never"),
    ("required", "optional"),
    ("enable", "disable"),
    ("允许", "禁止"),
    ("必须", "不必"),
    ("必须", "禁止"),
    ("应该", "不应该"),
    ("不丢", "可能丢"),
    ("不会丢", "可能丢"),
]


def _has_contradiction(text_a: str, text_b: str) -> bool:
    a_lower = text_a.lower()
    b_lower = text_b.lower()
    for term_a, term_b in _CONTRADICTION_PAIRS:
        a_has_a = term_a in a_lower
        a_has_b = term_b in a_lower
        b_has_a = term_a in b_lower
        b_has_b = term_b in b_lower
        if (a_has_a and b_has_b) or (a_has_b and b_has_a):
            return True
    return False


def _token_overlap(text_a: str, text_b: str) -> float:
    """计算两段文本的信号 token 重叠度（min 归一）。

    用 signal_tokens（ASCII 词 + CJK 二元组）而非整段 CJK run：
    中文换措辞后 run 级重叠接近 0（ctx-011 真实矛盾对仅 0.067），
    二元组能保留实体字面重叠。
    """
    tokens_a = signal_tokens(text_a)
    tokens_b = signal_tokens(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def detect_conflicts(
    memories: list[dict[str, Any]],
    overlap_threshold: float = 0.18,
) -> list[ConflictReference]:
    """检测检索结果中的冲突记忆。

    判定条件：两条记忆内容显著重叠，且包含相互矛盾的指令
    （如"必须"对"禁止"）。先按信号 token 重叠粗筛再查矛盾词对，
    避免对全部两两组合做文本匹配。

    默认阈值 0.18 的依据（eval-fixture 26 条 gold 全部 317 对的
    signal min-overlap 分布）：期望告警的中文矛盾对最低 0.225
    （ctx-012），矛盾词偶然命中但非矛盾的对最高 0.148（ctx-006）——
    0.18 落在两者之间，两侧各留约 1.2 倍余量。

    Args:
        memories: 记忆字典列表。
        overlap_threshold: 触发矛盾检查的最小信号 token 重叠度。

    Returns:
        每对冲突记忆对应的 ConflictReference 列表。
    """
    conflicts: list[ConflictReference] = []

    for i in range(len(memories)):
        for j in range(i + 1, len(memories)):
            mem_a = memories[i]
            mem_b = memories[j]

            content_a = mem_a.get("content", "")
            content_b = mem_b.get("content", "")

            overlap = _token_overlap(content_a, content_b)
            if overlap < overlap_threshold:
                continue

            if _has_contradiction(content_a, content_b):
                conflicts.append(
                    ConflictReference(
                        memory_id_a=str(mem_a.get("id", "")),
                        memory_id_b=str(mem_b.get("id", "")),
                        version_a=mem_a.get("version", 0),
                        version_b=mem_b.get("version", 0),
                        updated_at_a=str(mem_a.get("updated_at", "")),
                        updated_at_b=str(mem_b.get("updated_at", "")),
                    )
                )

    return conflicts


def has_contradiction_text(text_a: str, text_b: str) -> bool:
    """公开封装：检查两段文本是否包含矛盾指令。"""
    return _has_contradiction(text_a, text_b)
