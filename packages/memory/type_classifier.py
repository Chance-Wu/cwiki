"""基于关键词匹配的轻量级记忆类型分类器。

本模块零外部依赖（纯 Python），因此可被 MCP 适配器进程直接导入，
无需拉起 SQLAlchemy、numpy 等重量级包。
"""

from __future__ import annotations


def infer_memory_type(content: str, title: str | None = None) -> str:
    """根据内容关键词推断记忆类型。

    返回记忆类型字符串（如 ``"feedback"``、``"issue"``、``"decision"`` 等），
    无关键词命中时回退为 ``"fact"``。

    提供可选的 *title* 时，先按标题匹配（优先级更高），实现标题加权分类。
    """
    # 类型关键词组（按优先级排序，靠前的类型优先命中）
    type_keywords = [
        (
            "feedback",
            ["不要", "不应该", "以后别", "错了", "纠正", "偏好", "希望", "prefer", "应该"],
        ),
        (
            "issue",
            [
                "报错",
                "修复",
                "bug",
                "失败",
                "解决了",
                "根因",
                "HTTP 500",
                "status 500",
                "错误",
                "排查",
                "error",
                "fix",
            ],
        ),
        ("decision", ["选择", "决定", "改用", "架构", "设计决策", "选型", "取舍"]),
        ("procedure", ["步骤", "流程", "先", "然后", "操作指南", "配置步骤"]),
        ("convention", ["规范", "约定", "命名", "统一", "格式", "风格", "写法"]),
        (
            "constraint",
            [
                "不支持",
                "不兼容",
                "已移除",
                "版本限制",
                "上限",
                "下限",
                "依赖版本",
            ],
        ),
        ("rule", ["必须", "禁止", "不允许", "强制", "严禁", "务必"]),
        ("lesson", ["踩坑", "教训", "经验", "学到了", "下次注意", "原来是因为"]),
        ("pattern", ["模式", "反复出现", "工作流", "惯用", "最佳实践", "套路"]),
        ("reference", ["文档", "链接", "工具", "API", "外部", "参考", "网址", "URL"]),
    ]

    # 提供标题时，先逐类型检查标题（优先级高于正文）
    if title:
        for type_name, keywords in type_keywords:
            if any(kw in title for kw in keywords):
                return type_name

    # 再检查正文
    for type_name, keywords in type_keywords:
        if any(kw in content for kw in keywords):
            return type_name

    return "fact"
