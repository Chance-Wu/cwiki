"""应用设置。"""

from packages.domain.config import Settings, settings


def get_settings() -> Settings:
    """获取全局设置单例。"""
    return settings
