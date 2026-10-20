---
name: cwiki-save
description: 按需检索和保存知识。会话开始或话题切换时用 memory_search 检索相关记忆建立上下文；出现用户纠正、调试发现、技术决策、方案取舍、踩坑教训、技术学习等可复用信号时用 memory_save 提交。内容完整优先，类型仅分类，不把正文压成摘要。没有真实信号就跳过，不凑条数。
---

# cwiki 知识提取助手

本 skill 是知识提取策略的唯一来源，工具能力以当前 MCP `tools/list` 为准。

## 核心原则

**内容完整优先，类型仅作分类。宁可多提交有依据的知识，由人工审核过滤，不要遗漏。**

先写清值得保留的信息，再选类型。篇幅和条数不是目标。满足任一即可保存：(1) 帮助未来 agent 建立在已有知识之上；(2) 帮助用户学习、回顾或检索技术知识。

**工具概览**（16 个，均 `memory_` 前缀）：核心 `search`/`save`/`update`/`feedback`/`forget`；状态 `status`/`types`；检查点 `checkpoint`；恢复 `retry_failed`；辅助 `relations`/`history`（拆分前查 relations，更新前查 history）；复习 `review_due`/`review_submit`/`review_stats`；运维 `export`/`import`。

首次使用：确认 `save`/`search` 可用，调 `status` 核对工作区和限制。

## 工具参数速查

**所有工具 schema 均为 `additionalProperties: false`，传入表中未列出的键会被直接拒绝。工作区自动使用 Agent 当前绑定的项目（宿主 hook 实时同步），`workspace_name` 仅在明确要跨项目操作时才传。**

| 工具 | 必填 | 可选 | 接收 workspace_name |
|------|------|------|:---:|
| `memory_search` | `keyword` 或 `query`（二选一） | `limit`(非 curated 1–100，curated 1–50，默认 10)、`mode`(hybrid/semantic)、`curated`、`max_tokens`、`project`、`filters`(`type`/`min_confidence`) | ✓ |
| `memory_save` | `title`(≤80 字符)、`content`(≥20 字符) | `type` | ✓ |
| `memory_update` | `memory_id` | `content`、`title`、`expected_version`、`confidence`、`importance`、`reason`、`is_permanent`、`permanent_reason` | ✗ |
| `memory_feedback` | `memory_id`、`feedback_type` | `reason` | ✓ |
| `memory_forget` | `memory_id` | `reason` | ✓ |
| `memory_history` | `memory_id` | `view`(lifecycle/content)、`limit`(仅 content 视图) | ✗ |
| `memory_relations` | `memory_id` | `depth`(默认 1) | ✗ |
| `memory_checkpoint` | `trigger_reason` | `dry_run`、`event_session_id` | ✓ |
| `memory_status` | — | — | ✓ |
| `memory_types` | — | `type`(过滤) | ✗ |
| `memory_retry_failed` | —（无任何参数） | — | ✗ |
| `memory_review_due` | — | `limit`(1-100，默认 20) | ✓ |
| `memory_review_submit` | `memory_id`、`quality`(0-5) | — | ✓ |
| `memory_review_stats` | — | — | ✓ |
| `memory_export` | — | `entities` | ✓ |
| `memory_import` | `data` | `strategy`(skip/overwrite/rename) | ✓ |

常见调用形态：

```text
memory_search(keyword="业务关键词", limit=5)                                  # 工作区自动绑定当前项目
memory_search(keyword="关键词", limit=5)                                        # 通用召回 / 查重：跨全部工作区
memory_save(title="主题", content="完整正文…", type="lesson")                  # 自动写入当前项目
memory_update(memory_id="<id>", content="新正文…", reason="补充边界条件")
```

标注 ✗ 的工具不接收工作区参数。`keyword` 与 `query` 等价，传其一即可；`trigger_reason` 枚举见「检查点与结束前回顾」；`max_tokens` 与 `project` 仅在 `curated=true` 时使用。**工作区默认自动绑定 Agent 当前项目**（宿主 hook 实时同步，`memory_save` 不需要传 `workspace_name`）；`memory_search` 省略时跨全部工作区搜索，传 `workspace_name` 只用于显式限定。

## 信号识别

按需执行，非每轮强制。会话开始、切换话题、调试问题时先搜索；有可复用知识就提交，无真实信号就跳过。

| 信号模式 | 典型类型 |
|----------|----------|
| 用户纠正、明确偏好、被认可的建议 | feedback |
| 决策取舍、需求变化、暂缓/搁置决定 | decision |
| 调试发现、排查转折、失败尝试与边界 | issue / lesson |
| 重复踩坑、非显然 workaround、性能经验 | lesson / constraint |
| 隐性规则、安全红线、强制要求 | rule |
| 版本兼容、环境限制、工具配置陷阱 | constraint / lesson |
| 代码中反复出现的写法、项目特有约定 | convention / pattern |
| 操作/迁移/部署中的非显然步骤 | procedure |
| 架构认知、设计取舍、系统级 tradeoff | decision / convention |
| 认知纠偏——"原来不是 X，是 Y" | lesson / fact |
| 技术原理系统性讲解（含教科书级） | fact / lesson |
| 技术选型对比——A vs B 的优劣、适用场景 | decision |
| 知识梳理——整理某领域知识图谱或学习路径 | fact / reference |
| 外部资源入口、文档链接、API 地址、工具/库推荐 | reference |
| 跨会话重复提问、显式记忆请求 | 先 `memory_search` 找已有记忆：有 → `memory_update` 补充新信息；无 → `memory_save` 新建 |

交互信号：工作流偏好（feedback）、显式记忆请求（优先级最高）。无法准确分类时省略 `type`，`fact` 是兜底标签。仅从行为推测的偏好必须标明推测。

**跳过**：一次性状态查询、纯确认、可从代码/git 直接读取的细节、未加工的原样搬运。技术性知识经整理就有价值——记忆价值在于可检索，不在于独创。凭据和未脱敏日志不写入。

**可检索性检验**：写完后问"未来什么场景会检索到它"——答不上来 = 不够具体，需补充关键词、场景或结论。

**提交前自检清单**：
- [ ] 能回答"未来什么场景会检索到它"
- [ ] 首句即结论
- [ ] 含具体证据或数据（代码块、错误信息、配置值）
- [ ] 限定条件/边界保留
- [ ] 有行动指导（下次该怎么做）
- [ ] Markdown 格式（`##` 分段、关键结论加粗）

## 查重与决策

识别到信号后，先查重再决定动作。后端在提交时也会自动检测相似记忆并返回提示。

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

### 格式模板

按实际内容选用，不强制每个段落都出现。各类型推荐 Callout 见下表：

| 类型 | 推荐结构 | Callout |
|------|----------|---------|
| **事实** (fact) | 核心结论 → `## 机制/原理` → `## 关键特性` → `## 适用边界` → `## 对比`（可选表格） | `> [!abstract]` |
| **实战经验** (lesson) | 洞察一句话 → `## 背景` → `## 发现` → `## 下次应该` → `## 边界条件` | `> [!info]` |
| **问题排查** (issue) | 根因一句话 → `## 现象`（代码块原样保留错误） → `## 根因` → `## 解决方案` → `## 边界条件` | `> [!bug]` |
| **决策** (decision) | 结论一句话 → `## 背景` → `## 方案对比`（表格） → `## 取舍理由` + **Why:** / **How to apply:** | `> [!quote]` |
| **编码约定** (convention) | 约定一句话 → `## 规则` → `## 示例`（代码块） → `## 例外` | `> [!info]` |
| **实践模式** (pattern) | 模式一句话 → `## 适用场景` → `## 做法` → `## 反例` | `> [!tip]` |
| **操作步骤** (procedure) | 目标一句话 → `## 前置条件` → `## 步骤`（编号列表） → `## 成功判据` | `> [!info]` |
| **协作偏好** (feedback) | 规则一句话 + **Why:** + **How to apply:**（短偏好 <100 字无需 `##`） | `> [!tip]` |
| **资源指引** (reference) | 资源一句话 → `## 用途` → `## 访问方式` + 链接（不只存 URL，记为什么值得收藏） | `> [!bookmark]` |
| **技术约束** (constraint) | 约束一句话 → `## 来源` → `## 影响范围` → `## 例外` | `> [!warning]` |
| **强制规则** (rule) | 规则一句话 → `## 必须/禁止` → `## 后果` → `## 例外` | `> [!warning]` |

### 反模式与提交前自检

**避免**：

格式层面：纯文本墙（>5 行无结构）、装饰性标题（`## 总结` 无关键词）、空泛过渡（"综上所述"）、为凑结构拆段、标题后无空行。

内容层面：

- **正确的废话**——"要注意性能"、"代码要可维护"——无法指导决策，不如不写
- **无证据结论**——"X 比 Y 好"但不说在什么场景、用什么指标衡量
- **缺边界**——只说"怎么做"不说"什么时候不适用"
- **无行动指导**——读完知道"是什么"但不知道"下次该怎么做"

**提交前确认**：能回答"未来什么场景会检索到它"→ 有效 Markdown → 首句即结论 → 含具体证据或数据 → 限定条件/边界保留 → 有行动指导 → 有检索价值。

## 保存与更新

`memory_save(title=标题, content=完整正文, type=可选)`。**`title`（≤80 字符）与 `content` 均必填**；type 不传自动推断；**workspace_name 通常不传**——宿主 hook 会把工作区实时同步到当前项目。**返回结果回显 `workspace` 字段：每次保存后核对它是当前项目；若落到 `default` 或他区（hook 未激活、注册表过期、宿主刚切换项目），补传 `workspace_name=<项目目录名>` 重提一次；错误归属的 pending 候选不审批即可（人工拒绝或在 Web 控制台删除），绝不留到转正。**最低 `len(content.strip()) >= 20`，**有效最低 30 字符**（排除规则会拒绝 <30 或 >80% 代码的内容）。`#memory/{type}` 和 `#memory/{workspace}` 标签由服务端自动注入。新候选为 `pending_review`，需人工批准。

### 服务端处理链

提交后经过以下处理（agent 无需手动执行，但了解可避免意外拒绝）：

1. **内容规范化**：去除行尾空白、合并 3+ 空行为 1 行、标题前确保空行、末尾单换行。**语义不变**，仅格式化。
2. **排除规则**：`len(content.strip()) < 30` 或代码行占比 >80% 会被拒（认为可从代码/git 直接推导）。
3. **注入检测**：匹配 13 种 prompt 注入模式（中英文），命中则拒绝。
4. **相似检测**：与现有记忆比对（标题 20% + 正文 35% + 关键词 15% + embedding 余弦 30%），相似度 ≥0.70 的作为 `similar_memories` 返回提示。
5. **质量门控**：5 维评分（stable/reusable/actionable/scoped/evidence_backed）决定审核优先级。
6. **幂等保护**：`client_write_id = ms:{sha256(content)[:16]}`，重试时相同内容不会重复创建。

### 类型最低完整性要求（MQ-201 结构化契约）

正文应包含该类型的关键要素，缺失会降低质量分但不会阻止提交：

| 类型 | 至少应包含 |
|------|-----------|
| fact | 结论 + 解释/来源 + 适用范围 |
| decision | 结论 + 背景 + 理由/取舍 |
| lesson | 经验结论 + 触发场景 + 原因 + 下次做法 |
| issue | 现象 + 环境 + 根因 + 解决方案 + 验证结果 |
| convention | 规则 + 适用范围 + 例外 |
| rule | 约束 + 适用对象 + 违反后果 |
| constraint | 限制条件 + 触发条件 + 影响 |
| procedure | 前置条件 + 步骤 + 预期结果 + 验证方法 |
| pattern | 适用场景 + 做法 + 有效条件 + 反例 |
| feedback | 反馈主体 + 明确表述 + 作用范围 |
| reference | 资源入口 + 用途 + 来源/版本 |

### 两层去重

- **Agent 端**（提交前）：`memory_search(keyword=..., limit=5)` 主动查重，决定新建/跳过/更新/合并。
- **Server 端**（提交时）：自动检测相似记忆并返回 `similar_memories`，仅作提示不阻止提交。

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

## 反馈与遗忘

- 回答中实际使用了某条记忆 → `memory_feedback(memory_id=..., feedback_type="useful")`；帮助不大 → `not_useful`；内容过时/错误 → `outdated` / `wrong`。
- 确认一条记忆错误且不应继续出现 → `memory_forget(memory_id=..., reason="...")`。这是软归档，可在控制台恢复；不要用更新正文来“假装删除”。
- 反馈是后续排序和归档的依据，只对真正相关的记忆调用，不刷量。

## 检查点与结束前回顾

实时处理优先，检查点只兜底。关键节点调用 `memory_checkpoint`，trigger_reason：`user_correction`（用户纠正）、`problem_solved`（完成排查）、`technical_decision`（确定取舍）、`convention_discovered`（发现约定）、`session_long`（深入学习）、`session_ending`（会话结束）。

逐个评估候选（`dry_run=true`）→ 无问题提交、有遗漏补充、输入不完整标注"部分检查"。会话结束补齐未采集信号，输出 `新增 N / 更新 M / 跳过 K（原因）`。

## 反馈校准与汇报

被拒时分析原因调整阈值；同类连续被拒 2 次暂停反思；用户修改正文时记录模式。

**汇报**：有提交时 `新增 N 条（待审核）、更新 M 条（主题）`；暂存/失败时补充；无变化时不输出。
