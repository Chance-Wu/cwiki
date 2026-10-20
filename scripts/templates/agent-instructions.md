## cwiki 记忆

- 会话开始或切换话题时，用 `memory_search` 查相关记忆；工作区自动绑定当前项目，不需要传 `workspace_name`。
- 出现用户纠正、技术决策、踩坑、隐性约定、可复用资源时，按 `cwiki-save` skill 用 `memory_save` 提交；已有知识需要补充/纠偏时用 `memory_update`；无真实信号跳过，不凑条数。
- `memory_save` 结果回显 `workspace` 字段：核对它与当前项目一致再用；不一致（如落到 `default`）时补传 `workspace_name=<项目目录名>` 重提一次，不要静默接受错误归属。
- 回答中使用了某条记忆，可用 `memory_feedback` 标记 `useful` / `not_useful`；确认错误或过时的记忆用 `memory_forget` 软归档。
- 工具不可用时继续任务并注明“记忆不可用”，不要编造记忆内容。
- 内容完整优先：保留背景、证据、边界与可执行结论；类型只做分类，不强制格式。
