---
name: memory-recall
description: 开工前查询 cwiki 获取项目知识、历史决策、已知问题和编码约定，避免重复踩坑。
---

# 记忆检索

涉及以下场景时，应先用 `memory_search` 查询已有知识：
- 项目约定或编码规范
- 历史决策或架构选择
- 已知问题或排查经验
- 模块关系与依赖
- 已解决的问题

## 用法

1. 业务相关召回（项目约定、历史决策、模块知识）：调用 `memory_search`，`workspace_name` 设为当前项目目录名，`query` 描述当前任务关键词
2. 通用召回（用户偏好、通用技术知识、跨项目经验）：省略 `workspace_name`，跨全部工作区检索
3. 查看返回的 `items`，提取相关知识
4. 将相关记忆应用到当前工作

## 前置条件

检索不依赖 API：MCP 直接以只读模式读取 `cwiki-data/cwiki.db`，强命中直接返回本地结果；弱命中会自动回落 API 的混合检索。API 不可用时降级为本地关键词检索（结果带 `degraded: true`、无语义重排）。写入（`memory_save`/`memory_update`/`memory_feedback`）仍需 API 运行（默认 `http://127.0.0.1:5172`，`python tasks.py serve`）；不可用时继续任务并注明写入暂不可用。
