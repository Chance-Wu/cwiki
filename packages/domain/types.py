"""记忆分类的类型定义与校验。"""

from __future__ import annotations

from packages.domain.config import settings

# 低于该长度的内容难以构成可复用的知识
MIN_CONTENT_LENGTH = 20


def validate_memory_title(title: str) -> str:
    """校验标题非空，且不超过配置的长度上限。"""
    if not title.strip():
        raise ValueError("title 不能为空，必须由 Agent 生成并传入")
    if len(title) > settings.memory_title_max_length:
        raise ValueError(f"title 最多 {settings.memory_title_max_length} 个字符")
    return title


def validate_memory_content(content: str) -> str:
    """校验正文去除首尾空白后达到最小长度。"""
    if len(content.strip()) < MIN_CONTENT_LENGTH:
        raise ValueError(f"content 去除首尾空白后至少 {MIN_CONTENT_LENGTH} 个字符")
    return content


TYPE_DEFINITIONS: dict[str, dict[str, str]] = {
    "fact": {
        "name": "事实",
        "description": "可核查的客观事实、观察结果或状态描述",
    },
    "decision": {
        "name": "决策",
        "description": "方案选择及其依据，核心是为什么选 A 不选 B",
        "structure": "decision_record",
    },
    "issue": {
        "name": "问题排查",
        "description": "问题症状、排查过程、根因分析和修复验证",
    },
    "convention": {
        "name": "编码约定",
        "description": "代码写法、命名规范等团队共同遵循的实践标准",
    },
    "pattern": {
        "name": "实践模式",
        "description": "反复验证有效的解决思路或设计模式，含适用条件",
    },
    "procedure": {
        "name": "操作步骤",
        "description": "可执行的操作步骤序列，含前置条件和成功判据",
    },
    "feedback": {
        "name": "协作偏好",
        "description": "用户明确表达的行为偏好和期望调整",
        "structure": "rule_then_why",
    },
    "reference": {
        "name": "资源指引",
        "description": "外部文档、工具或资源的入口和使用说明",
    },
    "constraint": {
        "name": "技术约束",
        "description": "客观能力边界和环境限制，不以人的意志为转移",
    },
    "lesson": {
        "name": "实战经验",
        "description": "从踩坑或成功中提炼的洞察，核心是下次应该怎么做",
        "structure": "rule_then_why",
    },
    "rule": {
        "name": "强制规则",
        "description": "必须或禁止事项，违反有明确后果",
    },
}

ALL_TYPES: list[str] = list(TYPE_DEFINITIONS.keys())
