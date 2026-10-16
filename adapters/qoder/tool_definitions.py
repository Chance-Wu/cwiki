"""cwiki 全部 14 个记忆工具的 MCP JSON Schema 定义。

纯数据集合——不依赖 MCPServer、CwikiClient 或传输层。
工具名与 description 是对宿主（Agent）可见的协议契约，保持原样不动。
"""

from __future__ import annotations

from typing import Any

from packages.domain.config import settings
from packages.domain.types import MIN_CONTENT_LENGTH, TYPE_DEFINITIONS


def build_tool_definitions() -> list[dict[str, Any]]:
    """构建带 JSON Schema 输入的完整 MCP 工具定义列表。"""
    type_rows = [
        f"{key}({tpl.get('name') or ''})" if tpl.get("name") else key
        for key, tpl in TYPE_DEFINITIONS.items()
    ]
    return [
        {
            "name": "memory_search",
            "description": (
                "搜索记忆。省略 workspace_name 时跨全部工作区搜索；"
                "项目相关召回建议传 workspace_name 限定工作区。"
                "curated=true 时按 token 预算组装上下文并返回记忆缺口提示"
                "（始终按工作区执行，省略 workspace_name 回落默认工作区）。"
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词（与 query 二选一必填）",
                    },
                    "query": {
                        "type": "string",
                        "description": "搜索关键词（keyword 的别名，二选一必填）",
                    },
                    "workspace_name": {
                        "type": "string",
                        "description": (
                            "工作区名称或 UUID；省略则跨全部工作区搜索"
                            "（curated=true 时省略回落默认工作区）"
                        ),
                    },
                    "curated": {
                        "type": "boolean",
                        "description": "按预算组装上下文",
                        "default": False,
                    },
                    "project": {
                        "type": "string",
                        "description": "项目过滤器，仅 curated=true",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "minimum": 100,
                        "maximum": 20000,
                        "default": 5000,
                        "description": "token 预算，仅 curated=true",
                    },
                    "mode": {
                        "type": "string",
                        "description": "搜索模式",
                        "enum": ["hybrid", "semantic"],
                        "default": "hybrid",
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "搜索过滤器。type: 按记忆类型过滤（如 lesson/decision/fact）；"
                            "min_confidence: 按最低置信度过滤（0.0–1.0）"
                        ),
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "记忆类型过滤器",
                            },
                            "min_confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                                "description": "最低置信度过滤器",
                            },
                        },
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回数",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 10,
                    },
                },
                "anyOf": [
                    {"required": ["keyword"]},
                    {"required": ["query"]},
                ],
            },
        },
        {
            "name": "memory_save",
            "description": (
                "提交新记忆候选。正文原样保存，type 省略则自动推断。"
                "保留关键背景、证据、推理和边界条件，让未来读者能理解来龙去脉。"
                "提交后状态为 pending_review，需人工批准。"
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "content": {
                        "type": "string",
                        "minLength": MIN_CONTENT_LENGTH,
                        "description": (
                            f"完整正文（Markdown 格式），至少 {MIN_CONTENT_LENGTH} 字符。"
                            "首句概括结论，用 ## 分段（标题前后留空行），关键结论加粗，"
                            "错误信息/命令用代码块原样保留。"
                            "服务端会自动规范化空行和尾部空白。"
                        ),
                    },
                    "title": {
                        "type": "string",
                        "maxLength": settings.memory_title_max_length,
                        "description": f"记忆标题，最多 {settings.memory_title_max_length} 字符",
                    },
                    "type": {
                        "type": "string",
                        "description": "记忆类型，不传自动推断：" + "、".join(type_rows),
                    },
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                },
                "required": ["title", "content"],
            },
        },
        {
            "name": "memory_status",
            "description": "查看工作区统计和本地投递积压。API 离线时仍返回本地计数。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "memory_types",
            "description": "获取可选的记忆类型列表和描述。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "按类型过滤",
                    },
                },
            },
        },
        {
            "name": "memory_history",
            "description": "查看记忆历史：lifecycle 返回事件，content 返回历史正文版本。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "记忆 ID",
                    },
                    "view": {
                        "type": "string",
                        "enum": ["lifecycle", "content"],
                        "default": "lifecycle",
                        "description": "历史视图",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                        "description": "最大返回数，仅 view=content",
                    },
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "memory_relations",
            "description": "查询记忆的关联关系图谱，支持多层深度。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "记忆 ID",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "关联深度",
                        "default": 1,
                    },
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "memory_update",
            "description": "更新正式记忆，未传字段保持不变。用 expected_version 防并发覆盖。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "记忆 ID",
                    },
                    "expected_version": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "当前版本号，防并发覆盖",
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": settings.memory_title_max_length,
                        "description": f"新标题，最多 {settings.memory_title_max_length} 字符",
                    },
                    "content": {
                        "type": "string",
                        "minLength": MIN_CONTENT_LENGTH,
                        "description": f"完整新正文（Markdown 格式），至少 {MIN_CONTENT_LENGTH} 字符，整体替换",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "置信度",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "importance": {
                        "type": "number",
                        "description": "重要性",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "reason": {
                        "type": "string",
                        "description": "更新原因",
                    },
                    "is_permanent": {
                        "type": "boolean",
                        "description": "标记为永久有效",
                    },
                    "permanent_reason": {
                        "type": "string",
                        "description": "永久标记原因",
                    },
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "memory_retry_failed",
            "description": "手动重放本地所有工作区的未完成写入。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "memory_checkpoint",
            "description": "对已采集事件和笔记执行规则提取，提交记忆候选。dry_run=true 仅预览。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                    "event_session_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "事件 Session ID，通常自动关联",
                    },
                    "trigger_reason": {
                        "type": "string",
                        "enum": [
                            "problem_solved",
                            "user_correction",
                            "technical_decision",
                            "convention_discovered",
                            "session_long",
                            "session_ending",
                            "manual",
                        ],
                        "description": "触发原因",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "仅预览不提交",
                        "default": False,
                    },
                },
                "required": ["trigger_reason"],
            },
        },
        {
            "name": "memory_export",
            "description": "导出工作区数据为 JSON，可指定实体类型或不传导出全部。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                    "entities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "实体类型列表，不传导出全部",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "memory_import",
            "description": "导入 JSON 数据到工作区。冲突策略：skip(默认)/overwrite/rename。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "data": {
                        "type": "object",
                        "description": "导出的 JSON 数据",
                    },
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["skip", "overwrite", "rename"],
                        "description": "冲突策略",
                        "default": "skip",
                    },
                },
                "required": ["data"],
            },
        },
        {
            "name": "memory_review_due",
            "description": "获取待复习的记忆列表。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回数",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20,
                    },
                },
                "required": [],
            },
        },
        {
            "name": "memory_review_submit",
            "description": "提交复习评分(0-5)：5完美/4犹豫后正确/3困难正确/2错误但记住/1错误易识别/0完全忘记。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "记忆 ID",
                    },
                    "quality": {
                        "type": "integer",
                        "description": "质量评分",
                        "minimum": 0,
                        "maximum": 5,
                    },
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                },
                "required": ["memory_id", "quality"],
            },
        },
        {
            "name": "memory_review_stats",
            "description": "获取复习统计：已调度、到期、今日已复习、掌握度分布、7天趋势。",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "workspace_name": {
                        "type": "string",
                        "description": "工作区名称或 UUID",
                    },
                },
                "required": [],
            },
        },
    ]
