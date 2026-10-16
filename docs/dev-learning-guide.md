# cwiki 开发学习文档

> 本文档面向希望深入理解 cwiki 项目架构与实现原理的开发者，从整体设计到核心模块逐层展开。

## 一、项目定位

cwiki 是一个 **Agent 记忆基础设施**，为 AI 编程助手提供知识的持久化存储、智能检索和持续进化能力。它不是一个传统的 Wiki 系统，而是专门为 AI Agent 在工作会话中「记住事情」而设计的基础设施层。

核心理念可以用三个关键词概括：

- **持久进化** — 知识不是一次性存储，而是持续积累、去重、合并、升级
- **持久学习** — 通过记忆检索和关联，让每次对话都建立在已有知识之上
- **寄生式生长** — 记忆系统附着在 Agent 工作流上，不干扰正常开发流程

### 边界约束

| 做 | 不做 |
|----|------|
| 个人知识管理 | 多用户/团队协作 |
| Agent 记忆存储与检索 | 通用 SaaS 服务 |
| 知识进化与质量治理 | 复杂权限系统 |

## 二、技术栈总览

### 后端

| 层 | 技术 | 说明 |
|----|------|------|
| Web 框架 | FastAPI | 异步 API，20 个路由模块 |
| ORM | SQLAlchemy (async) + aiosqlite | 异步 SQLite，25 张表 |
| 数据库迁移 | Alembic | 28 个迁移版本 |
| 向量检索 | numpy | 余弦相似度批量计算 |
| 关键词检索 | 自定义 BM25 | 标准 BM25 算法（IDF=log(1+N/n)） |
| 中文分词 | jieba | CJK 文本分词 |
| Embedding | fastembed 本地 ONNX 模型 | 零 API 依赖，hash fallback |
| 文件监控 | watchdog | Markdown 文件变更监听 |
| CLI | typer | 命令行入口 |
| 代码规范 | ruff (lint + format), mypy (strict) | — |
| 测试 | pytest (asyncio_mode=auto) | 800+ 测试用例 |

### 前端

| 层 | 技术 |
|----|------|
| 框架 | React 18 + TypeScript 5 |
| 构建 | Vite 5 |
| 样式 | Tailwind CSS 3 |
| 路由 | React Router 6 |
| 服务端状态 | TanStack React Query 5 |
| Markdown 渲染 | react-markdown + remark-gfm |
| 图标 | lucide-react |
| 测试 | vitest + @testing-library/react |
| 国际化 | 自研 Context-based i18n（中/英双语） |

### MCP 适配层

| 组件 | 说明 |
|------|------|
| 协议 | JSON-RPC 2.0 over stdio |
| 工具数 | 14 个 MCP 工具 |
| 可靠投递 | Write-ahead outbox + 自动重试 |

## 三、项目结构

```
cwiki/
├── apps/
│   ├── api/              # FastAPI 后端主进程
│   │   ├── main.py       # 应用工厂 + CLI 入口
│   │   ├── auth.py       # Agent 身份认证
│   │   ├── deps.py       # FastAPI 依赖注入
│   │   ├── file_sync.py  # 文件同步工具
│   │   └── routes/       # 20 个路由模块
│   ├── web/              # React 前端 SPA
│   │   └── src/
│   │       ├── pages/        # 8 个页面
│   │       ├── components/   # 共享组件 + 业务组件
│   │       ├── hooks/        # 13 个自定义 Hook
│   │       ├── lib/          # API 客户端、工具函数
│   │       └── i18n/         # 国际化
│   └── worker/           # 后台异步任务
│       ├── run_worker.py     # Worker 入口
│       ├── tasks.py          # 8 个注册任务
│       ├── scoring.py        # 候选记忆评分
│       ├── dedup.py          # 去重与关系分类
│       └── episode_builder.py # 事件流 → 情节摘要
│
├── packages/
│   ├── domain/           # 核心领域层
│   │   ├── models/       # 25 张 ORM 表（5 个文件：base + 4 模型）
│   │   ├── schemas/      # Pydantic 请求/响应模型（5 个文件）
│   │   ├── config.py     # 配置加载（config.yaml）
│   │   ├── database.py   # 异步数据库引擎
│   │   ├── types.py      # 11 种记忆类型定义 + 校验
│   │   ├── task_queue.py # 内存异步任务队列
│   │   ├── settings.py   # 运行时设置
│   │   ├── errors.py     # 领域异常定义
│   │   ├── export_import.py # 数据导入导出
│   │   ├── paths.py      # 路径工具
│   │   ├── secrets.py    # 密钥管理
│   │   └── time_utils.py # 时间工具
│   ├── memory/           # 记忆服务层
│   │   ├── service.py    # 核心管线：提交 → 审核 → 入库
│   │   ├── quality_gate.py     # 5 维质量门控
│   │   ├── duplicate_detection.py # 多信号去重（n-gram + embedding）
│   │   ├── spaced_repetition.py   # SM-2 间隔重复
│   │   ├── review_service.py     # 审核调度
│   │   ├── type_classifier.py    # 类型自动推断
│   │   ├── content_security.py   # 注入检测
│   │   ├── utility_score.py      # 效用评分
│   │   ├── health.py             # 健康度计算
│   │   ├── memory_gap.py         # 知识空白检测
│   │   ├── similarity.py         # 统一分词 + Jaccard 相似度
│   │   └── evolution_metrics.py  # 进化效果指标
│   ├── retrieval/        # 检索引擎
│   │   ├── engine.py     # 10 步混合检索管线
│   │   ├── bm25.py       # 自定义 BM25 关键词索引（IDF=log(1+N/n)）
│   │   ├── embedding.py  # fastembed 本地 ONNX Embedding 生成
│   │   ├── optimizer.py  # 检索优化
│   │   ├── vector_utils.py # numpy 余弦相似度
│   │   ├── query/analyzer.py   # 查询意图分析
│   │   ├── ranking/      # 重排序（reranker + temporal + diversity）
│   │   └── context/      # 上下文组装（去重、冲突、token 预算）
│   ├── storage/          # 存储抽象层
│   │   ├── file_store.py   # Markdown 文件读写（{workspace}/{type}/ 目录结构）
│   │   ├── meta_store.py   # _meta/ 关系数据 JSON（feedback / usage / review_schedule 等）
│   │   ├── rebuilder.py    # 从 MD + _meta 重建 SQLite（schema 缺失时经 Alembic 自动创建）
│   │   ├── indexer.py      # SQLite + 向量索引同步
│   │   ├── vector_index.py # numpy 向量索引（.npz 持久化）
│   │   ├── config.py       # 存储配置（index.db / vectors.npz 位于 cwiki-data/ 下）
│   │   └── git_version.py  # Git 版本信息
│   └── protocol/         # 协议信封定义
│
├── adapters/
│   └── qoder/            # Qoder MCP 适配器
│       ├── mcp_server.py    # MCP 服务器
│       ├── transport.py     # stdio 传输层
│       ├── signal_engine.py # 信号提取引擎
│       ├── tool_definitions.py # MCP 工具定义
│       ├── content_processing.py # 内容处理
│       ├── client.py        # REST API 异步客户端
│       ├── outbox.py        # Write-ahead outbox
│       ├── workspace.py     # 工作区解析
│       ├── commands/        # MCP 命令处理
│       ├── hooks/           # 钩子系统
│       └── skills/          # 技能管理
│
├── skills/               # 宿主 skill（cwiki-save 等）
├── scripts/              # 运维脚本
│   ├── setup.py            # Agent 接入配置（MCP 注册 / skill 安装 / 迁移初始化）
│   ├── migrate_to_git.py   # SQLite → MD + _meta 全量导出
│   ├── rebuild_db.py       # 从 MD + _meta 重建数据库
│   ├── recompute.py        # 重算派生字段（SM-2 调度等）
│   ├── verify_rebuild.py   # MD/_meta/DB 三方一致性校验
│   ├── port_utils.py       # 跨平台端口管理
│   ├── restart_watcher.py  # 重启守护
│   ├── run_alembic.py      # Alembic 包装（patch 损坏的 entry_points）
│   └── run_pytest.py       # pytest 包装（同上）
│
├── benchmarks/           # 检索评测
│   ├── evaluators/       # IR 指标计算（Recall、MRR、NDCG）
│   ├── runners/          # 5 条管线对比评测
│   └── performance/      # 规模基准测试（10K → 1M）
│
├── migrations/           # Alembic 迁移（28 个版本）
├── tests/                # 测试套件（46 个文件）
├── config.yaml           # 统一配置
├── cwiki-data/           # 数据主源：MD + _meta/ + cwiki.db + index.db + vectors.npz
│                         #   随 Git 多设备同步；DB / 索引为可重建产物
└── tasks.py              # 跨平台任务运行器
```

---

## 四、数据库模型（25 张表）

数据库是理解整个系统的最佳起点。cwiki 使用 SQLAlchemy 异步 ORM，底层为 SQLite（aiosqlite），共 25 张表分布在 4 个模型文件中。

### 4.1 记忆核心（12 张表）

```
packages/domain/models/memory.py
```

| 表名 | 职责 | 关键字段 |
|------|------|----------|
| `memory` | 已验证的正式记忆 | title, content, type, status, confidence, importance, version, embedding(512维), valid_from/to, usage_count |
| `candidate_memory` | 待审核的候选记忆 | 继承 memory 字段 + 质量评分（novelty, reusability, stability 等）+ duplicate_probability + client_write_id（幂等写入） |
| `memory_version` | 版本历史 | memory_id, version, change_type, changed_by, reason |
| `evidence` | 证据关联 | 多态关联到 memory 或 candidate，链接到 event/episode |
| `review` | 审核记录 | action(approve/reject/merge), before_content, after_content, reason |
| `memory_usage` | 使用追踪 | position, stage, trace_id, session_id |
| `memory_feedback` | 反馈记录 | feedback_type(positive/negative), reason |
| `memory_conflict` | 冲突追踪 | 两条记忆间的矛盾，status(open/resolved) |
| `memory_lifecycle_event` | 生命周期审计 | event_type(archive/consolidate 等) |
| `memory_relation` | 记忆关系图 | relation_type(supports/contradicts/relates_to), confidence |
| `proactive_push_record` | 主动推送记录 | relevance_score, keywords |
| `review_schedule` | 间隔重复计划 | ease_factor, interval_days, repetitions, next_review（SM-2 算法） |

### 4.2 会话与事件（5 张表）

```
packages/domain/models/session.py
```

| 表名 | 职责 |
|------|------|
| `session` | Agent 编码会话，关联 workspace + agent + project |
| `event` | 会话内的原子事件（prompt.submitted, tool.completed, test.passed 等），按 sequence 排序 |
| `episode` | 事件分组摘要，包含 goal, summary, importance，可产出候选记忆 |
| `agent_session` | MCP 适配层的轻量会话记录 |
| `session_note` | 会话中的原始笔记，可「形式化」为候选记忆 |

### 4.3 工作区与组织（5 张表）

```
packages/domain/models/workspace.py
```

| 表名 | 职责 |
|------|------|
| `workspace` | 顶层组织单元 |
| `project` | 工作区下的项目 |
| `agent` | 注册的 AI Agent |
| `agent_profile` | Agent 行为画像（提交率、形式化率等） |
| `audit_log` | 不可变审计日志 |

### 4.4 检索追踪（2 张表）

```
packages/domain/models/retrieval.py
```

| 表名 | 职责 |
|------|------|
| `retrieval_trace` | 每次检索请求的记录（query, intent, 候选数, 返回数, 延迟） |
| `retrieval_trace_item` | 单条记忆的管线追踪（stage, rank, score, used） |

### 4.5 自定义类型

```python
# packages/domain/models/base.py
UUIDType = String(36)  # UUID 存储为字符串
JSONBType = JSON  # JSON 字段
VectorType = Text  # Embedding 向量存储为 JSON 数组文本
```

---

## 五、核心管线：记忆的生命周期

理解 cwiki 的关键在于理解一条数据的完整生命周期。一条记忆从产生到被检索，经历以下阶段：

### 5.1 写入管线（Candidate → Review → Memory）

```
Agent 调用 memory_save
       │
       ▼
┌──────────────────┐
│ Write-Ahead Outbox │  ← 崩溃安全的预写日志
└──────┬───────────┘
       │ HTTP POST
       ▼
┌──────────────────┐
│ 参数校验          │  ← 标题 ≤80 字，正文 ≥20 字
│ 内容安全检查      │  ← 正则注入检测（中/英文）
│ 类型自动推断      │  ← 关键词匹配 11 种类型
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 提交时去重        │  ← bigram 预过滤 + 多信号去重（n-gram + embedding）
│ 质量门控评分      │  ← 5 维评分（稳定/可复用/可操作/有范围/有证据）
└──────┬───────────┘
       │
       ▼
  CandidateMemory（状态: pending_review）
       │
       │  异步任务队列
       ▼
┌──────────────────┐
│ 生成 Embedding    │  ← fastembed 本地 ONNX 模型
│ 深度去重检查      │  ← 混合检索 + 关系分类（NEW/UPDATE/MERGE/CONFLICT）
│ 价值评分          │  ← 6 维加权公式
└──────┬───────────┘
       │
       ▼
  人工/Agent 审核（支持 SM-2 间隔重复调度）
       │
       ├── approve → 创建 Memory + 写入 Markdown 文件 + 更新索引
       ├── reject  → 标记拒绝
       └── merge   → 合并到已有 Memory + 创建 MemoryVersion
```

### 5.2 质量门控（5 维评分）

```python
# packages/memory/quality_gate.py
compute_quality_gate(candidate) → {
    "stable":          内容是否稳定（非临时状态）,
    "reusable":        是否可跨场景复用,
    "actionable":      是否可指导具体行动,
    "scoped":          是否有明确的适用范围,
    "evidence_backed": 是否有证据支撑,
}
```

每个维度通过关键词启发式 + 内容长度 + 类型基础分来计算。质量分越低，审核优先级越高。

### 5.3 去重机制

```python
# packages/memory/duplicate_detection.py
detect_duplicate(candidate, existing_memory) → DuplicateVerdict

# 相似度计算：n-gram Jaccard + embedding 余弦加权
similarity = 0.20 × title_sim + 0.35 × content_sim + 0.15 × keyword_sim + 0.30 × embedding_sim

# 判定阈值
EXACT_DUPLICATE:   similarity ≥ 0.85
POSSIBLE_DUPLICATE: similarity ≥ 0.60
DISTINCT:           similarity <  0.60
```

### 5.4 价值评分（Worker 异步计算）

```python
# apps/worker/scoring.py
value_score = 0.20 × novelty       # 1.0 - 与已有记忆的最大余弦相似度
          + 0.20 × reusability
          + 0.15 × stability
          + 0.15 × confidence
          + 0.15 × importance
          + 0.15 × evidence_strength

# 优先级分类
< 0.35  → discard（丢弃）
< 0.65  → low_priority
< 0.85  → normal
≥ 0.85  → high_value
```

### 5.5 间隔重复（SM-2 算法）

```python
# packages/memory/spaced_repetition.py
sm2_algorithm(quality: 0-5) → {
    ease_factor:   调整后的难度因子,
    interval_days: 下次复习间隔天数,
    repetitions:   连续成功次数,
}

# quality < 3 → 重置 interval=1
# quality ≥ 3 → interval 递增（1→6→...）

# 掌握程度映射
new → learning → familiar → proficient → mastered
```

---

## 六、检索引擎：10 步混合管线

检索是 cwiki 的另一半核心。`RetrievalEngine` 实现了一个精心设计的 10 步管线，融合了关键词检索和向量检索的优势。

```
查询输入
  │
  ▼
① 查询分析 ─────── 意图分类（6 类）+ 实体提取 + 同义词扩展
  │
  ▼
② BM25 检索 ───── 关键词匹配，返回 Top 50
  │
③ 向量检索 ─────── 余弦相似度，返回 Top 50（numpy 批量计算）
  │
  ▼
④ RRF 融合 ─────── Reciprocal Rank Fusion (k=60) 合并两路结果
  │
  ▼
⑤ 加载完整记录 ─── 从数据库加载 Memory 对象
  │
  ▼
⑥ 时间衰减 ─────── 基于 valid_from/to 和 last_used_at 计算新鲜度
  │                 expired=0.1, 7天内=0.95, 30天内=0.8, 90天内=0.6, 更旧=0.4
  ▼
⑦ 多信号重排序 ─── 加权融合：
  │                 0.38×RRF + 0.16×importance + 0.13×confidence
  │                 + 0.13×freshness + 0.08×usage + 0.12×intent_match
  ▼
⑧ 多样性过滤 ───── 每种类型最多保留 3 条
  │
  ▼
⑨ 上下文组装 ───── 去重(Jaccard>0.80) → 冲突检测 → 优先级排序 → token 预算裁剪
  │
  ▼
⑩ 追踪记录 ─────── 写入 retrieval_trace + retrieval_trace_item
```

### 6.1 查询分析

```python
# packages/retrieval/query/analyzer.py
AnalyzedQuery {
    intent:         locate | compare | explain | how_to | what_is | troubleshoot
    entities:       技术栈实体（React, Spring Boot, SQL 等）
    expanded_terms: 同义词扩展
    is_question:    是否为疑问句
    confidence:     置信度
}
```

内置双向同义词映射和技术栈实体模式识别。

### 6.2 RRF 融合

Reciprocal Rank Fusion 是一种无需调分的排名融合算法：

```
RRF_score(d) = Σ 1 / (k + rank_i(d))    # k=60
```

对每条记忆，取其在 BM25 排名和向量排名中的倒数之和作为融合分数。

### 6.3 上下文组装

```python
# packages/retrieval/context/assembler.py
assemble_context() 执行：
  1. 去重（Jaccard > 0.80 的视为重复）
  2. 冲突检测（token 重叠 > 0.4 且含矛盾指令）
  3. 优先级排序（constraint > decision > rule > lesson > fact > ...）
  4. 多样性过滤
  5. token 预算裁剪（默认 2000，支持 500/1000/2000/4000/8000）
  6. 格式化输出
```

### 6.4 Token 估算（CJK 感知）

```python
# packages/retrieval/context/token_counter.py
estimate_tokens(text):
    英文: 4 字符 ≈ 1 token
    CJK:  1.5 字符 ≈ 1 token
```

---

## 七、MCP 适配器

MCP（Model Context Protocol）适配器是 Agent 与 cwiki 之间的桥梁，运行在独立进程中，通过 stdio 进行 JSON-RPC 2.0 通信。

### 7.1 架构

```
AI Agent (Qoder/Codex)
     │
     │ stdio (JSON-RPC 2.0)
     ▼
┌─────────────────────┐
│   MCPServer          │  adapters/qoder/mcp_server.py
│   ├─ 14 个 MCP 工具  │
│   ├─ WriteAheadOutbox │  ← 崩溃安全写入
│   ├─ SessionManager   │  ← 会话生命周期
│   └─ SignalDetector   │  ← 规则驱动的信号提取
└────────┬────────────┘
         │ HTTP (async httpx)
         ▼
┌─────────────────────┐
│   CwikiClient        │  adapters/qoder/client.py
│   └─ REST API 封装   │  ← 指数退避重试（503/429）
└────────┬────────────┘
         │
         ▼
   FastAPI 后端 (port 5172)
```

### 7.2 14 个 MCP 工具

| 工具 | 功能 |
|------|------|
| `memory_search` | 搜索记忆；`curated=true` 获取精选上下文 |
| `memory_save` | 提交候选记忆（经 outbox 保证可靠投递） |
| `memory_status` | 查看统计与积压 |
| `memory_types` | 获取可选类型列表 |
| `memory_history` | `view="lifecycle"`（默认）查看生命周期；`view="content"` 查看正文版本历史 |
| `memory_relations` | 查询记忆关系图 |
| `memory_update` | 更新已有记忆（整体替换正文） |
| `memory_retry_failed` | 重试 outbox 中的失败写入 |
| `memory_checkpoint` | 从事件/笔记中提取候选记忆 |
| `memory_export` | 导出工作区数据 |
| `memory_import` | 导入工作区数据 |
| `memory_review_due` | 获取到期复习的记忆 |
| `memory_review_submit` | 提交复习结果（SM-2 算法更新间隔） |
| `memory_review_stats` | 查看复习统计 |

`memory_search` 默认 `curated=false`；精选模式保留 `context` 和 `items`。省略 `workspace_name` 时跨工作区检索（`curated=true` 回落默认工作区）。正文版本历史不用于读取当前正文。参数范围与模式边界见 [MCP 工具参考](../adapters/qoder/README.md#mcp-tools)。提取策略由 `cwiki-save` skill 定义。

### 7.3 Write-Ahead Outbox

```
memory_save 调用
     │
     ▼
写入本地 outbox 文件（per-workspace JSON）
  ├─ 原子写入（temp + replace）
  ├─ 文件锁（Windows: msvcrt / Unix: fcntl）
  └─ 状态: pending → failed → exhausted（3 次失败后）
     │
     ▼
HTTP POST 到 API
  ├─ 成功 → 移除 outbox 条目, delivery: confirmed
  └─ 失败 → 保留条目，等待自动重试或 memory_retry_failed
```

---

## 八、后台 Worker

Worker 与 API 在同一进程内启动，通过 `TaskQueue`（内存异步队列，4 个并发 worker）执行后台任务。

### 8.1 注册的 8 个任务

| 任务 | 职责 |
|------|------|
| `finalize_episode` | 将事件流构建为情节摘要（goal, summary, actions, problems, lessons） |
| `score_candidate` | 计算候选记忆的价值评分（6 维加权） |
| `generate_embedding` | 为正式记忆生成 Embedding（fastembed 本地 ONNX） |
| `generate_candidate_embedding` | 为候选记忆生成 Embedding |
| `batch_generate_embeddings` | 批量生成所有缺失的 Embedding（fastembed 本地 ONNX 批量） |
| `dedup_check` | 混合检索找相似记忆 + 关系分类（NEW/UPDATE/MERGE/CONFLICT/REJECT） |
| `auto_consolidate_similar` | 自动合并 Jaccard > 0.85 的高度相似记忆 |
| `check_review_reminders` | 检查到期复习并发送提醒 |

### 8.2 TaskQueue 设计

```python
# packages/domain/task_queue.py
class TaskQueue:
    - 内存异步队列，4 个并发 worker
    - 任务去重（name + args 相同则跳过）
    - 指数退避重试（最多 3 次）
    - 定期清理已完成任务
    - 崩溃恢复：recover_orphaned_candidates() 重新入队卡住的候选
```

### 8.3 去重关系分类

```python
# apps/worker/dedup.py
classify_relation(embedding_similarity) → {
    > 0.95  → MERGE 或 UPDATE（几乎相同）
    > 0.80  → UPDATE（高度相关）
    > 0.60  → 检查冲突标志 → CONFLICT 或 NEW
    ≤ 0.60  → NEW（全新记忆）
}
```

冲突检测通过否定词匹配实现（must/should not, always/never, enable/disable，中英文双语）。

---

## 九、存储层

cwiki 采用 SQLite + Markdown + 向量索引的三层存储策略，整体位于 `cwiki-data/` 下随 Git 多设备同步；其中 DB 与索引均为可重建产物。

### 9.1 三层存储

| 层 | 技术 | 文件 | 职责 |
|----|------|------|------|
| 主存储 | SQLite | `cwiki-data/cwiki.db` | 所有 ORM 表，事务一致性（可重建） |
| 文件存储 | Markdown + YAML frontmatter | `./cwiki-data/{workspace}/{type}/{id}_{title}.md` | 人类可读、可编辑 |
| 关系数据 | JSON | `./cwiki-data/_meta/{memory_id}.json` | feedback / usage / review_schedule / lifecycle 等关系数据 |
| 索引层 | SQLite + numpy | `cwiki-data/index.db` + `cwiki-data/vectors.npz` | BM25 全文索引 + 向量索引（可重建） |

### 9.2 文件存储格式

```markdown
---
id: "uuid"
title: "记忆标题"
type: "decision"
status: "active"
confidence: 0.85
importance: 0.7
version: 3
created_at: "2026-01-15T10:30:00"
updated_at: "2026-09-20T14:22:00"
---

记忆正文内容（Markdown 格式）
```

### 9.3 向量索引

```python
# packages/storage/vector_index.py
class VectorIndex:
    - numpy 矩阵存储（.npz 格式）
    - 元数据 JSON 持久化（.json 格式）
    - 批量余弦相似度搜索
    - 支持增量 add/remove
```

### 9.4 Git 同步与可重建

Markdown 与 `_meta/` JSON 是数据主源，两者共同构成 Git 同步的完整内容：

```
cwiki-data/                      # 随 GitHub 私有仓库多设备同步（cwiki-data/sync.py，数据仓库自管）
  ├── {workspace}/{type}/*.md    # 记忆正文（人类可读，git 原生合并）
  ├── _meta/{memory_id}.json     # 关系数据（按记忆分文件，冲突罕见）
  ├── cwiki.db                   # SQLite 主库（可重建，二进制不可合并）
  ├── index.db / vectors.npz     # 派生索引（可重建）
```

- **重建**：`python tasks.py rebuild-db` 基于 MD + `_meta/` 重建 SQLite 与向量索引；DB 缺失时经 Alembic 自动创建 schema，完成后自动 `recompute`（重放 review_history 重建 SM-2 调度等派生字段）
- **校验**：`python scripts/verify_rebuild.py` 比对 MD / `_meta/` / DB 三方记忆数量与关键字段
- **同步**：`python cwiki-data/sync.py`（数据仓库自管）执行 WAL checkpoint 后将 MD + `_meta/` + `cwiki.db` + 索引一并 commit，再 pull / push；`python tasks.py start` 仅自动 pull 代码仓库，DB 缺失时自动重建
- **冲突兜底**：`cwiki.db` 二进制冲突无法合并，可删除本地 DB 与索引后经 `rebuild-db` 从 MD + `_meta/` 重建

> 详见 [Git 同步指南](git-sync.md)。

---

## 十、前端架构

### 10.1 路由与页面

```
/           → HomePage        仪表盘（EvolutionPanel + LearningPanel）
/pending    → InboxPage       候选记忆审核队列
/memories   → MemoriesPage    正式记忆浏览器
/skills     → SkillsPage      技能管理
/review     → ReviewPage      间隔重复复习
/settings   → SettingsPage    配置管理
/config     → ConfigPage      运行时配置
*           → NotFoundPage    404
```

所有页面通过 `React.lazy()` + `React.Suspense` 实现懒加载。

### 10.2 数据流

```
组件 → useXxx Hook → API Client (lib/api.ts) → FastAPI (port 5172)
              │
              └─ TanStack React Query
                   ├─ 自动缓存（30s staleTime）
                   ├─ 失败重试（1 次）
                   └─ 乐观更新
```

### 10.3 核心 Hook

| Hook | 职责 |
|------|------|
| `useCandidates` | 候选记忆 CRUD + 审核操作 |
| `useMemories` | 正式记忆浏览 + 详情 |
| `useSearch` | 多模式搜索（BM25/混合/语义） |
| `useReview` | 间隔重复复习 |
| `useDashboard` | 仪表盘统计数据 |
| `useSettings` | 配置读写 |
| `useSkills` | 技能管理 |
| `useConflicts` | 冲突管理 |
| `useModal` | 模态框状态管理 |

### 10.4 国际化

自研的轻量 i18n 方案，基于 React Context：

```typescript
// i18n/I18nProvider.tsx
// 支持 zh（简体中文）和 en（英文）
// 通过 useTranslation() hook 在组件中使用
```

---

## 十一、配置系统

所有配置统一在 `config.yaml` 中管理，通过 `packages/domain/config.py` 的 `Settings` 类加载。

### 11.1 主要配置段

```yaml
app:
  api_host: "0.0.0.0"
  api_port: 5172
  debug: true
  embedding_model: "BAAI/bge-small-zh-v1.5"
  embedding_dimensions: 512

database:
  url: "sqlite+aiosqlite:///./cwiki-data/cwiki.db"

memory:
  similarity_threshold: 0.7
  consolidate_threshold: 0.85
  title_max_length: 80
  # ... 更多阈值

parasitic_evolution:           # 寄生式知识进化功能开关
  memory_gap_detection_enabled: true
  proactive_push_enabled: true
  memory_relations_enabled: true
  agent_profile_enabled: true
  auto_consolidate_enabled: true
  # ... 更多开关

retrieval:
  bm25_weight: 0.6
  vector_weight: 0.4
  reranker_rrf_weight: 0.38
  reranker_importance_weight: 0.16
  reranker_confidence_weight: 0.13
  reranker_freshness_weight: 0.13
  reranker_intent_weight: 0.12
  reranker_usage_weight: 0.08
  reranker_key_term_bonus: 0.08

storage:
  memory_dir: "./cwiki-data"   # Markdown 文件存储目录
```

## 十二、记忆类型系统

cwiki 定义了 11 种记忆类型，类型仅用于分类，不影响存储结构。

| 类型 | 名称 | 说明 | 典型场景 |
|------|------|------|----------|
| `fact` | 事实 | 客观可验证的信息 | "Python 3.11+ 是必需的" |
| `decision` | 决策 | 带有理由的选择 | "选择 SQLite 因为单用户场景" |
| `issue` | 问题排查 | 问题症状、排查过程与修复验证 | "Windows 加密软件阻断 .txt 文件" |
| `convention` | 编码约定 | 代码写法和团队实践标准 | "魔法字符串提取为类常量" |
| `pattern` | 实践模式 | 反复验证有效的解决思路 | "Write-ahead outbox 保证可靠投递" |
| `procedure` | 操作步骤 | 可执行的分步操作指南 | "数据库迁移步骤" |
| `feedback` | 协作偏好 | 用户明确的行为偏好和调整 | "不要在 Windows 上用 sed -i" |
| `reference` | 资源指引 | 外部文档或资源的入口说明 | "Grafana 延迟看板地址" |
| `constraint` | 技术约束 | 客观能力边界和环境限制 | "不做多用户/团队协作" |
| `lesson` | 实战经验 | 从踩坑或成功中提炼的洞察 | "mock 测试通过了但生产迁移失败" |
| `rule` | 强制规则 | 必须或禁止的硬规则 | "调用 cwiki 工具必须传 workspace_name" |

类型推断通过 `type_classifier.py` 的关键词匹配实现，标题中的关键词权重更高。无法匹配时回退为 `fact`。

---

## 十三、评分体系全景

cwiki 中有多套评分系统，各有侧重：

### 13.1 质量门控（提交时）

```
5 维评估：stable / reusable / actionable / scoped / evidence_backed
→ 综合 quality_score
→ 映射到 review_priority（质量越低，优先级越高）
```

### 13.2 价值评分（Worker 异步）

```
6 维加权：novelty(0.20) / reusability(0.20) / stability(0.15)
         / confidence(0.15) / importance(0.15) / evidence_strength(0.15)
→ value_score → 优先级分类（discard / low / normal / high）
```

### 13.3 效用评分（运行时）

```
5 维加权：retrieval_success(0.30) / agent_usage(0.25)
         / human_feedback(0.20) / freshness(0.15) / evidence_strength(0.10)
→ utility_score → 反映记忆的实际使用价值
```

### 13.4 健康度（综合判断）

```
基于 utility_score + feedback + staleness + conflicts
→ 状态：healthy / needs_review / suspicious / conflicted
```

---

## 十四、开发命令速查

日常开发通过 `python tasks.py` 跨平台运行（Windows/Mac/Linux 通用），常用命令如下：

| 操作 | 命令 |
|------|------|
| 一键启动（API + Worker + 前端） | `python tasks.py start` |
| 仅启动 API | `python tasks.py serve` |
| 仅启动前端 | `python tasks.py web` |
| 运行测试 | `python tasks.py test` |
| 代码检查 | `python tasks.py lint` |
| 代码格式化 | `python tasks.py format` |
| 安装依赖 | `python tasks.py install` |
| 数据库迁移（向上） | `python tasks.py migrate-up` |
| 数据库迁移（回滚） | `python tasks.py migrate-down` |
| 创建迁移 | `python tasks.py migrate-create "描述"` |
| 首次迁移（SQLite → MD + _meta） | `python tasks.py migrate-to-git` |
| 同步数据（数据仓库自管） | `python cwiki-data/sync.py` |
| 从 MD + _meta 重建数据库 | `python tasks.py rebuild-db` |
| 重算派生字段（SM-2 等） | `python tasks.py recompute` |
| 重建索引 | `curl -X POST http://127.0.0.1:5172/v1/file-memories/rebuild-index` |
| 重启服务 | `curl -X POST http://127.0.0.1:5172/v1/system/restart` |
| 历史事件回填 | `python tasks.py worker` |

---

## 十五、测试策略

项目使用 pytest-asyncio + 内存 SQLite 构建测试基础设施，每个测试独立事务回滚，10 个黄金场景覆盖关键路径。

### 15.1 测试分层

```
tests/
├── conftest.py              # 内存 SQLite + 事务回滚 + AsyncClient
├── test_bm25.py             # BM25 索引（中英文分词、边界条件）
├── test_reranker.py         # 重排序器（权重、意图加成）
├── test_scoring.py          # 价值评分（边界、权重、归一化）
├── test_quality_gate.py     # 质量门控（5 维、参数化边界）
├── test_duplicate_detection.py # 去重（精确/可能/不同）
├── test_outbox.py           # Outbox（原子写入、并发隔离、Windows 锁）
├── test_task_queue.py       # 任务队列
├── context/                 # 上下文组装测试
│   ├── test_assembly.py     # 完整组装管线
│   ├── test_conflict.py     # 冲突检测
│   ├── test_dedup.py        # 去重
│   ├── test_priority.py     # 优先级排序
│   └── test_token_budget.py # Token 预算
├── e2e/
│   └── test_golden_scenarios.py # 10 个黄金场景端到端测试
└── ...
```

### 15.2 测试模式

- **异步测试**：pytest-asyncio，`asyncio_mode=auto`
- **数据库隔离**：内存 SQLite + 事务级回滚（每个测试后 rollback）
- **认证覆盖**：通过 FastAPI 依赖注入模拟 Agent 身份
- **参数化边界**：对长度限制、阈值边界进行参数化测试
- **黄金场景**：10 个真实场景（SC-001 到 SC-010）覆盖项目约束、架构决策、Bug 教训等

### 15.3 评测基准

```
benchmarks/
├── 检索评测：Recall@K, Precision@K, MRR, NDCG@10, Useful@10
├── 5 条管线对比：bm25 / vector / hybrid_rrf / hybrid_rrf_rerank / full_pipeline
├── 目标：Recall@10 ≥ 0.80, Useful@10 ≥ 0.60, p95 < 700ms
└── 规模基准：10K → 1M 记忆，p50 < 150ms, p95 < 500ms
```

---

## 十六、关键设计模式

项目中反复出现的架构模式，理解它们有助于快速定位和修改代码。

### 16.1 应用工厂模式

```python
# apps/api/main.py
def create_app() -> FastAPI:
    app = FastAPI()
    app.router.lifespan_context = lifespan
    # 注册中间件、异常处理器、20 个路由模块
    return app


app = create_app()  # ASGI 入口
```

### 16.2 单例检索引擎

```python
# packages/retrieval/engine.py
_engine: RetrievalEngine | None = None


def get_retrieval_engine() -> RetrievalEngine:
    global _engine
    if _engine is None:
        _engine = RetrievalEngine(...)
    return _engine
```

### 16.3 幂等写入

```python
# CandidateMemory 表
UniqueConstraint(workspace_id, client_write_id)
# 相同的 client_write_id 不会创建重复候选
```

### 16.4 崩溃恢复

```python
# apps/worker/tasks.py
recover_orphaned_candidates()
# 启动时扫描卡在中间状态的候选记忆，重新入队处理
```

### 16.5 功能开关

```yaml
# config.yaml → parasitic_evolution 段
memory_gap_detection_enabled: true/false
proactive_push_enabled: true/false
auto_consolidate_enabled: true/false
# 每个进化功能都可独立开关
```

---

## 十七、数据流全景图

从 Agent 发起请求到前端展示，完整的数据流如下：

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Agent 会话                             │
│  (Qoder / Codex / 任何 MCP 兼容的 Agent)                        │
└───────────┬─────────────────────────────────┬───────────────────┘
            │ memory_save / memory_search      │
            │ (stdio JSON-RPC)                 │
            ▼                                  │
┌───────────────────────┐                      │
│   MCP 适配器           │                      │
│   ├─ MCPServer        │                      │
│   ├─ WriteAheadOutbox │                      │
│   └─ CwikiClient      │                      │
└───────────┬───────────┘                      │
            │ HTTP REST                         │
            ▼                                  │
┌───────────────────────────────────────────────┴─────────────────┐
│                     FastAPI 后端 (port 5172)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐    │
│  │ 路由层    │  │ 记忆服务  │  │ 检索引擎  │  │ TaskQueue    │    │
│  │ 19模块   │→ │ 质量门控  │  │ 10步管线  │  │ 4 worker    │    │
│  │          │  │ 去重检测  │  │ BM25+向量 │  │ 异步任务     │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘    │
└───────────┬──────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────┐
│                     存储层                                    │
│  ┌────────────┐  ┌────────────────┐  ┌──────────────────┐    │
│  │ SQLite      │  │ Markdown 文件   │  │ 向量索引          │    │
│  │ cwiki.db   │  │ ./cwiki-data/  │  │ vectors.npz      │    │
│  │ 25 张表     │  │ YAML 前置元数据 │  │ numpy 余弦相似度  │    │
│  └────────────┘  └────────────────┘  └──────────────────┘    │
└──────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────┐
│                     React 前端 (Vite)                         │
│  仪表盘 │ 审核队列 │ 记忆浏览 │ 搜索 │ 复习 │ 技能 │ 设置     │
└──────────────────────────────────────────────────────────────┘
```

---

## 十八、学习路径建议

如果你是第一次接触这个项目，建议按以下顺序理解：

### 第一阶段：理解数据模型

1. 阅读 `packages/domain/models/memory.py` — 理解 Memory 和 CandidateMemory 的区别
2. 阅读 `packages/domain/models/session.py` — 理解 Event → Episode → Memory 的转化链
3. 阅读 `packages/domain/types.py` — 理解 11 种类型和校验规则

### 第二阶段：理解写入管线

4. 阅读 `packages/memory/service.py` — 核心业务逻辑
5. 阅读 `packages/memory/quality_gate.py` — 质量门控如何打分
6. 阅读 `packages/memory/duplicate_detection.py` — 去重如何工作
7. 阅读 `apps/worker/scoring.py` 和 `apps/worker/dedup.py` — 异步评分和深度去重

### 第三阶段：理解检索管线

8. 阅读 `packages/retrieval/engine.py` — 10 步管线全貌
9. 阅读 `packages/retrieval/bm25.py` — 关键词检索
10. 阅读 `packages/retrieval/vector_utils.py` — 向量检索
11. 阅读 `packages/retrieval/context/assembler.py` — 上下文组装

### 第四阶段：理解适配层

12. 阅读 `adapters/qoder/outbox.py` — 可靠投递机制
13. 阅读 `adapters/qoder/mcp_server.py` — MCP 协议实现（文件较大，可分段阅读）

### 第五阶段：理解前端

14. 阅读 `apps/web/src/lib/api.ts` — API 客户端全貌
15. 阅读 `apps/web/src/App.tsx` — 路由结构
16. 选择一个页面深入阅读（建议 InboxPage — 审核队列，涉及最多的业务逻辑）

### 第六阶段：理解测试与评测

17. 阅读 `tests/conftest.py` — 测试基础设施
18. 阅读 `tests/integration/e2e/test_golden_scenarios.py` — 10 个黄金场景
19. 阅读 `benchmarks/evaluators/retrieval.py` — IR 评测指标

---

## 十九、常见开发场景

### 添加新的 API 路由

1. 在 `apps/api/routes/` 下创建新路由文件（参考现有模块的结构）
2. 在 `apps/api/main.py` 的 `create_app()` 中注册路由
3. 编写对应的测试文件

### 添加新的后台任务

1. 在 `apps/worker/tasks.py` 中定义任务函数
2. 在 `register_tasks()` 中注册
3. 任务通过 `TaskQueue.enqueue()` 调用

### 添加新的记忆类型

1. 在 `packages/domain/types.py` 的 `TYPE_DEFINITIONS` 中添加定义
2. 在 `packages/memory/type_classifier.py` 中添加关键词规则

### 调整检索行为

1. 权重调整 → 修改 `config.yaml` 的 `retrieval.reranker_*_weight`
2. 查询分析 → 修改 `packages/retrieval/query/analyzer.py`
3. 上下文组装 → 修改 `packages/retrieval/context/` 下的模块
4. 管线步骤 → 修改 `packages/retrieval/engine.py`

### 数据库迁移

1. 修改 `packages/domain/models/` 下的模型
2. 运行 `python tasks.py migrate-create "描述变更"`
3. 运行 `python tasks.py migrate-up` 应用迁移
