## cwiki 记忆

> 规则优先级：会话注入的「cwiki 写入决策」决定是否写入；`cwiki-save` skill 决定怎么写。本段是硬约束摘要，与 skill 细则冲突时以 skill 为准。

- 会话开始或切换话题时，用 `memory_search` 检索相关记忆：**省略 `workspace_name` 会跨全部工作区搜索**；项目相关召回请显式传 `workspace_name=<项目目录名>`。`memory_save` 的工作区由宿主 hook 自动绑定当前项目。
- 出现用户纠正、技术决策、踩坑、隐性约定、可复用资源等信号时，按 `cwiki-save` skill 用 `memory_save` 提交；无真实信号跳过，不凑条数。
- 不写入：凭据、密钥、令牌、未脱敏日志、一次性状态查询，以及可从代码或 git 直接推导的内容。
- 已有知识需要补充或纠偏时用 `memory_update`（先读原文）；`memory_save` 被 4xx 拒绝时不要原样重试——提示 skip 表示规则不允许写入，提示 update 时按返回的 `target_memory_id` 改用 `memory_update`。
- `memory_save` 回显 `workspace` 与当前项目不一致（如落到 `default`）时，补传 `workspace_name=<项目目录名>` 重提一次；错误归属的候选不审批。回显 `cached: true` 表示本地暂存，修复连接后用 `memory_retry_failed` 补投，不要重新生成；`delivery: confirmed` 仅表示 API 已接收，不等于已生效。
- 回答中使用了记忆时用 `memory_feedback` 标记 `useful` / `not_useful`；确认错误或过时的记忆用 `memory_forget` 软归档。工具不可用时继续任务并注明“记忆不可用”，不要编造记忆内容。
- 内容完整优先：保留背景、证据、边界与可执行结论；类型只做分类，正文用 Markdown（细则见 `cwiki-save` skill）。
