## cwiki 记忆

- 会话开始或切换话题时，用 `memory_search` 查相关记忆：项目约定/历史决策会自动命中当前项目（工作区自动绑定）；跨项目通用知识直接省略参数查全部。
- 出现用户纠正、技术决策、踩坑、隐性约定、可复用资源时，按 `cwiki-save` skill 用 `memory_save` 提交（不要传 workspace_name，自动写入当前项目）；已有知识需要补充/纠偏时用 `memory_update`；无真实信号跳过，不凑条数。
- `memory_save` 结果回显 `workspace` 字段：核对它是当前项目再用；若落到 `default` 或他区，补传 `workspace_name=<项目目录名>` 重提一次，错误归属的 pending 候选不审批即可。
- 回答中使用了某条记忆，可用 `memory_feedback` 标记 `useful` / `not_useful`；确认错误或过时的记忆用 `memory_forget` 软归档（可恢复）。
- 工具不可用时继续任务并注明“记忆不可用”，不要编造记忆内容。
- 内容完整优先：保留背景、证据、边界与可执行结论；类型只做分类，不强制格式。
