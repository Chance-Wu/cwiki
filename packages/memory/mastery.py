"""掌握度相关配置的共享辅助函数。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def is_mastery_coupled_decay_enabled() -> bool:
    """查询寄生演化配置中是否启用「掌握度耦合衰减」。

    开启后衰减速度与 SM-2 的 ease_factor 挂钩：掌握越牢（EF 越高）衰减越慢。
    配置加载失败按未启用处理，仅记录 debug 日志。
    """
    try:
        from packages.domain.config import parasitic_evolution_config

        return parasitic_evolution_config.mastery_coupled_decay_enabled
    except Exception:
        logger.debug("Failed to load parasitic evolution config", exc_info=True)
        return False
