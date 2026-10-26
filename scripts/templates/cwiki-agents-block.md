## cwiki 记忆

- 会话开始或切换话题时，用 `memory_search` 检索相关记忆：默认只查当前项目（工作区自动绑定）；跨项目通用知识可省略 `workspace_name` 查全部。
- 出现用户纠正、技术决策、踩坑、隐性约定、可复用资源等信号时，按 `cwiki-save` skill 用 `memory_save` 提交；无真实信号跳过，不凑条数。
- 不写入：凭据、密钥、令牌、未脱敏日志、一次性状态查询，以及可从代码或 git 直接推导的内容。
- 已有知识需要补充或纠偏时用 `memory_update`（先读原文）；`memory_save` 被 4xx 拒绝时不要原样重试——提示 skip 表示规则不允许写入，提示 update 时按返回的 `target_memory_id` 改用 `memory_update`。
- `memory_save` 回显的 `workspace` 与当前项目不一致（如落到 `default`）时，补传 `workspace_name=<项目目录名>` 重提一次；错误归属的候选不审批。
- 回答中使用了记忆时用 `memory_feedback` 标记 `useful` / `not_useful`；确认错误或过时的记忆用 `memory_forget` 软归档。工具不可用时继续任务并注明“记忆不可用”，不要编造记忆内容。
- 内容完整优先：保留背景、证据、边界与可执行结论；类型只做分类，不强制格式。
