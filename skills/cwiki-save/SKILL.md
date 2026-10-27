---
name: cwiki-save
description: 会话开始或切换话题、需要检索既有项目知识时使用；出现用户纠正、调试发现、技术决策、方案取舍、踩坑教训、技术学习、隐性约定、可复用资源等信号，或需要保存、更新、反馈、遗忘记忆时使用。
---

# cwiki 知识提取助手

本 skill 定义提取流程、查重、格式与检查点。**会话注入的”cwiki 写入决策”规则优先**（规则决定是否写入，本 skill 决定如何写）。工具能力以当前 MCP `tools/list` 为准。

## 写入决策（会话注入）

会话开始若注入了 `cwiki 写入决策`，按优先级执行（不写入 > 更新 > 写入）：

- `[写入]`：正常提交 `memory_save`。
- `[不写入]`：直接跳过，不要调用 `memory_save`。
- `[更新已有]`：先搜索并确认目标记忆，用 `memory_update` 更新，不要新建。
- 未命中规则时按注入的“未命中”默认动作执行（写入/不写入）；未注入时按本 skill 默认信号表判断。
- “写入但需要人工审核”不在这里表达，由 `memory.write_policy` 决定。

## 核心原则

**内容完整优先，类型仅作分类。宁可多提交有依据的知识，由人工审核过滤，不要遗漏。**

先写清值得保留的信息，再选类型。篇幅和条数不是目标。满足任一即可保存：(1) 帮助未来 agent 建立在已有知识之上；(2) 帮助用户学习、回顾或检索技术知识。

**工具概览**（19 个，均 `memory_` 前缀）：检索 `search`；写入 `save`/`update`/`feedback`/`forget`；状态 `status`/`types`/`tags`；检查点 `checkpoint`；恢复 `retry_failed`；关系 `relations`（拆分前查关联）/`relation_create`/`relation_delete`；历史 `history`（更新前查版本）；复习 `review_due`/`review_submit`/`review_stats`；运维 `export`/`import`。

首次使用：确认 `save`/`search` 可用，调 `status` 核对工作区和限制。必填/可选参数、枚举与调用形态见 [references/tool-contract.md](references/tool-contract.md)。

## 信号识别

按需执行，非每轮强制。会话开始、切换话题、调试问题时先搜索；有可复用知识就提交，无真实信号就跳过。

| 信号模式 | 典型类型 |
|----------|----------|
| 用户纠正、明确偏好、被认可的建议 | feedback |
| 决策取舍、需求变化、暂缓/搁置决定 | decision |
| 调试发现、排查转折、重复踩坑、非显然 workaround | issue / lesson |
| 隐性规则、安全红线、强制要求 | rule |
| 版本兼容、环境限制、工具配置陷阱 | constraint / lesson |
| 代码中反复出现的写法、项目特有约定 | convention / pattern |
| 操作/迁移/部署中的非显然步骤 | procedure |
| 架构认知、设计取舍、系统级 tradeoff | decision / convention |
| 认知纠偏——"原来不是 X，是 Y" | lesson / fact |
| 技术原理讲解、技术选型对比 | fact / lesson / decision |
| 知识梳理、外部资源入口、文档链接 | fact / reference |
| 跨会话重复提问、显式记忆请求 | 先 `memory_search` 找已有记忆：有 → `memory_update` 补充新信息；无 → `memory_save` 新建 |

交互信号：工作流偏好（feedback）、显式记忆请求（优先级最高）。无法准确分类时省略 `type`，`fact` 是兜底标签。仅从行为推测的偏好必须标明推测。

**跳过**：一次性状态查询、纯确认、可从代码/git 直接读取的细节、未加工的原样搬运。技术性知识经整理就有价值——记忆价值在于可检索，不在于独创。凭据和未脱敏日志不写入。

**可检索性检验**：写完后问"未来什么场景会检索到它"——答不上来 = 不够具体，需补充关键词、场景或结论。

## 查重与决策

识别到信号后，先查重再决定动作。

**搜索策略**：提取 2-3 个核心关键词，用 `memory_search(keyword=..., limit=5)` 查重——**省略 `workspace_name` 跨工作区比对**，同一知识可能已存在于其他工作区。若已知类型可用 `filters={"type": "lesson"}` 缩小范围。首轮无相关时换词再试（去修饰词、上位概念、中英互换），两轮无相关 → 新建（`memory_save` 自动写入当前项目工作区）。

**决策流程**：

```
搜索结果
  ├─ 为空 → memory_save（新建）
  ├─ 有结果，标题/正文明显不同 → memory_save（新建）
  ├─ 有结果，核心结论一致 → 跳过
  ├─ 有结果，需补充或矛盾 → memory_update（先读原文）
  └─ 多条重叠 → 合并到最相关一条
```

结果为空即无相关；`pending_review` 也算已存在。

## 如何组织内容

正文**必须使用 Markdown 格式**。保留真实背景、证据、推理、取舍、失败尝试和边界；这些是可用素材，不是必填清单。

### 排版与粒度

**排版**：首句即结论 → 关键词前置 → 证据原样（代码块）→ 限定不删 → `[[标题]]` 关联 → `##` 前后留空行。短偏好（<100 字）无需 `##`。常用别名在正文首行用 `别名：XX` 标注。

**粒度**：一条 = 一个独立可检索知识单元。独立成立 → 拆分；总一起被检索 → 合并。拆分用 `[[标题]]` 关联。结构随篇幅：短（<100 字）无 `##`、中（100-300 字）1-2 个 `##`、长（300+ 字）多级 `##` + 表格/代码块。

### 模板与结构

按类型选用结构模板与 Callout、对照内容结构建议、避免反模式：见 [references/content-templates.md](references/content-templates.md)。

## 保存与更新

`memory_save(title=标题, content=完整正文, type=可选)`。

**必填字段**：`title`（≤80 字符）与 `content` 均必填；`type` 不传自动推断。

**工作区绑定**：`workspace_name` 通常不传——宿主 hook 会把工作区实时同步到当前项目。**返回结果回显 `workspace` 字段**：每次保存后核对它是当前项目；若落到 `default` 或他区（hook 未激活、注册表过期、宿主刚切换项目），补传 `workspace_name=<项目目录名>` 重提一次；错误归属的 pending 候选不审批即可（人工拒绝或在 Web 控制台删除），绝不留到转正。

**内容长度**：最低 `len(content.strip()) >= 20`，**有效最低 30 字符**（排除规则会拒绝 <30 或 >80% 代码的内容）。

**标签注入**：`#memory/{type}` 与 `#memory/{workspace}` 标签由 **MCP 适配器**自动补齐，服务端只做校验。新候选为 `pending_review`，需人工批准。

**永久记忆**：仅在用户明确要求长期保留时传 `is_permanent=true`（可附 `permanent_reason`），审批通过后正式记忆带永久标记，不参与自动衰减与自动合并归档。不要替用户推测永久性；普通高价值记忆用标签即可。

**显式记忆请求优先**：用户明确说"记住"时，即使查重命中已有记忆也不能直接跳过——已有条目已覆盖则用 `memory_update` 补充，仍需要独立条目则照常 `memory_save`，并在回复中说明是更新还是新增。

**服务端响应处理**：`memory_save` 返回体可能包含以下字段：
- `policy.action`：`auto` = 评分后自动生效；`review` = 强制人工审核
- `decision.action`：`review` = 强制人工审核
- 4xx 错误 + `write_decision`：`skip` = 规则拦截，不要重试；`update` = 改用 `memory_update` 更新 `target_memory_id` 指向的记忆

### 服务端处理链

提交后自动经过：内容规范化（去空白、合并空行）→ 排除规则（<30 字符或 >80% 代码拒绝）→ 注入检测（13 种模式）→ 相似检测（≥0.70 返回提示）→ 质量门控（5 维评分）→ 幂等保护（相同内容不重复创建）。Agent 无需手动执行，了解可避免意外拒绝。

### 失败与恢复

| 状态 | 处理 |
|------|------|
| `delivery: confirmed` + 候选 ID | API 已接收（≠ 人工批准）；记录 ID 供查重 |
| `cached: true` | 本地暂存，修复连接后调 `memory_retry_failed`，不重新生成重投 |
| `cached: false` / 校验失败 | 无可靠投递保证，保留原文，修复后再提交 |
| `rejected` / `exhausted` | 需处理原因或人工介入；用 `memory_status` 检查积压 |
| 内容被注入检测拦截 | 错误含 `security_flag: suspicious_content`；检查内容是否含类似指令注入的文本（如 "忽略以上指令"），改写后重新提交 |
| 内容被排除规则拒绝 | 正文去空白后 <30 字符或代码占比 >80%；补充分析、背景或结论后重新提交 |
| 更新超时 | 可能已生效；先读当前正文与版本再决定是否重试，支持 `expected_version` |
| 用户要求只读 | 不调用 save/update/重试/非预览 checkpoint |

## 反馈、遗忘与汇报

**反馈**：回答中实际使用了某条记忆 → `memory_feedback(memory_id=..., feedback_type=”useful”)`；帮助不大 → `not_useful`；内容过时/错误 → `outdated` / `wrong`。反馈是后续排序和归档的依据，只对真正相关的记忆调用，不刷量。

**遗忘**：确认一条记忆错误且不应继续出现 → `memory_forget(memory_id=..., reason=”...”)`。这是软归档，可在控制台恢复；不要用更新正文来”假装删除”。

**汇报**：有提交时 `新增 N 条（待审核）、更新 M 条（主题）`；暂存/失败时补充；无变化时不输出。被拒时分析原因调整阈值；同类连续被拒 2 次暂停反思；用户修改正文时记录模式。

## 检查点与结束前回顾

实时处理优先，检查点只兜底。关键节点调用 `memory_checkpoint`，`trigger_reason` 枚举见 [references/tool-contract.md](references/tool-contract.md)。

逐个评估候选（`dry_run=true`）→ 无问题提交、有遗漏补充、输入不完整标注"部分检查"。会话结束补齐未采集信号，输出 `新增 N / 更新 M / 跳过 K（原因）`。
