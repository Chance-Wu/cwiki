# 记忆质量管线调用链

> MQ-001 交付物：梳理提炼、评分、去重、审核和正式记忆转换的完整调用链。

## 总览

```
Agent/用户 ──→ MCP memory_save ──→ API POST /v1/candidates
                                          │
                          ┌────────────────┼────────────────────┐
                          ▼                ▼                    ▼
                   排除列表检查      相似检测(提交时)      质量门评分
                   (quality_gate)   (duplicate_detection)  (quality_gate)
                          │                │                    │
                          └────────────────┼────────────────────┘
                                          ▼
                              CandidateMemory(status=pending_review)
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                   Embedding生成     Scoring评分      Dedup去重
                   (fastembed)     (scoring.py)     (dedup.py)
                          │               │               │
                          └───────────────┼───────────────┘
                                          ▼
                              审核分流（自动 or 人工）
                                    │           │
                                    ▼           ▼
                            自动批准       人工审核
                           (auto_approve)  (reviews API)
                                    │           │
                                    └─────┬─────┘
                                          ▼
                              approve_candidate(service)
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                    创建 Memory     文件镜像同步      索引更新
                    (active,v=1)   (file_sync.py)   (BM25+向量)
```

## 1. 候选产生（三条路径）

### 路径 A：MCP memory_save（Agent/用户主动提交）

| 步骤 | 函数 | 位置 | 说明 |
|------|------|------|------|
| 1 | `MCPServer._handle_memory_save` | `adapters/qoder/mcp_server.py:722-803` | 接收 title/content，安全检测 |
| 2 | `_outbox_submit` → `_submit_write` | `mcp_server.py:483-543` | Outbox 可靠投递 |
| 3 | `CwikiClient.submit_candidate` | `adapters/qoder/client.py:193-215` | HTTP POST `/v1/candidates` |

### 路径 B：MCP memory_checkpoint（事件流自动提取）

| 步骤 | 函数 | 位置 | 说明 |
|------|------|------|------|
| 1 | `MCPServer._handle_memory_checkpoint` | `mcp_server.py:1206-1287` | 拉取事件+笔记 |
| 2 | `extract_memories_from_events` | `adapters/qoder/signal_engine.py:195-294` | 规则匹配：笔记→候选、失败→issue、关键词→类型 |
| 3 | `_checkpoint_submit_candidates` | `mcp_server.py:966-1022` | SHA-256 去重后逐条提交 |

### 路径 C：Episode finalize（失败→修复信号）

| 步骤 | 函数 | 位置 | 说明 |
|------|------|------|------|
| 1 | `task_finalize_episode` | `apps/worker/tasks.py:69-175` | 构建 episode |
| 2 | `_generate_episode_candidate` | `tasks.py:282-329` | problems+solutions 非空时触发 |
| 3 | `_build_episode_lesson_candidate` | `tasks.py:253-279` | 构造 lesson 标题/正文 |

## 2. API 候选创建

```
POST /v1/candidates → create_candidate_endpoint (apps/api/routes/candidates.py:40-101)
  │
  ├─ create_candidate (packages/memory/service.py:273-362)
  │    ├─ 幂等校验（client_write_id）
  │    ├─ check_exclusion_list (quality_gate.py:142-159)  ← 硬性过滤：<30字 or >80%代码
  │    ├─ _find_similar_at_submit (service.py:262)
  │    │    └─ batch_detect_duplicates_with_embedding (duplicate_detection.py:329)
  │    │         └─ 四路加权：标题n-gram 20% + 正文n-gram 35% + BM25 15% + embedding 30%
  │    ├─ compute_quality_gate (quality_gate.py:178-197)  ← 五维评分
  │    │    ├─ _score_stable       ← 类型基础分 + 长度 + 绝对化词 - 版本号
  │    │    ├─ _score_reusable     ← 跨上下文词 + 长度 + 代码块 + 示例
  │    │    ├─ _score_actionable   ← 动词密度 + 结构化 + 条件句 + why/how
  │    │    ├─ _score_scoped       ← 长度 + 主题数
  │    │    └─ _score_evidence_backed ← 证据数 + 内部证据 + 信号类型
  │    └─ 创建 CandidateMemory(status=pending_review)
  │
  └─ 入队 task_generate_candidate_embedding
```

## 3. Worker 处理管线

### Step 1: Embedding 生成

```
task_generate_candidate_embedding (tasks.py:590-621)
  ├─ embedding_service.generate(text)  → fastembed ONNX 本地模型
  ├─ 写入 candidate.embedding
  └─ 入队 task_score_candidate
```

### Step 2: 评分

```
task_score_candidate (tasks.py:332-431)
  ├─ 查询 workspace 下最多 500 条 active memory 的 embedding
  ├─ score_candidate (scoring.py:124-158)
  │    ├─ calculate_novelty (scoring.py:78-121)  ← 1 - max_cosine_similarity
  │    ├─ calculate_value_score (scoring.py:19-52)
  │    │    └─ 公式: 0.25*reusability + 0.20*stability + 0.20*confidence
  │    │            + 0.20*importance + 0.15*evidence_strength
  │    │    └─ 缺失维度 → 返回 None（不再默认 0.5）
  │    └─ classify_priority (scoring.py:55-75)
  │         ├─ < 0.35 or None → "needs_enrichment"
  │         ├─ 0.35-0.65 → "low_priority"
  │         ├─ 0.65-0.85 → "normal"
  │         └─ >= 0.85 → "high_value"
  ├─ 回写 value_score, novelty, duplicate_probability, similar_memory_id
  ├─ priority == "needs_enrichment" → 标记状态，返回
  └─ auto_approve_enabled → _maybe_auto_approve (tasks.py:453-527)
       ├─ 检查四阈值：value_score, confidence, quality_gate, duplicate_probability
       ├─ 检查无 open 冲突
       └─ 全部满足 → approve_candidate → 正式记忆
```

### Step 3: 去重

```
task_dedup_check (tasks.py:697-780)
  ├─ find_similar (dedup.py:254-316)
  │    ├─ BM25 关键词召回
  │    ├─ 向量余弦召回
  │    ├─ RRF 融合排序
  │    └─ classify_relation (dedup.py:94-127)  ← 逐条判定
  │         ├─ similarity > merge_threshold
  │         │    └─ _classify_high_similarity (dedup.py:64-91)
  │         │         ├─ 新版本号/日期 → "update_candidate"
  │         │         └─ 其余 → "similar"
  │         ├─ similarity > update_threshold → "update_candidate"
  │         ├─ similarity > conflict_threshold → "similar"
  │         └─ 其余 → "new"
  └─ 冲突时创建 MemoryConflict 记录
```

## 4. 审核与正式记忆转换

### 人工审核

```
POST /v1/reviews → create_review (apps/api/routes/reviews.py:354-481)
  ├─ _apply_simple_review_action (reviews.py:247-264)
  │    └─ approve_candidate (service.py:365-418)
  │         ├─ 创建 Memory(status="active", version=1)
  │         ├─ _maybe_extract_and_store_entities (service.py:29-46)
  │         ├─ MemoryLifecycleEvent("created")
  │         └─ ReviewService.schedule_memory (review_service.py:386)  ← SM-2 复习计划
  ├─ _auto_detect_relations (reviews.py:71-234)
  ├─ sync_memory_to_file (file_sync.py:49-88)
  │    ├─ memory_to_file → MemoryFile
  │    ├─ file_store.save → Markdown 写入
  │    └─ indexer.index_memory → BM25 + 向量索引更新
  └─ 入队 task_generate_embedding（正式记忆向量）
```

### 自动批准

```
_maybe_auto_approve (tasks.py:453-527)
  ├─ approve_candidate (service.py:365)
  ├─ Review(action="auto_approve", reviewer_type="system")
  ├─ sync_memory_to_file
  └─ 入队 generate_embedding
```

## 5. 关键模块清单

| 模块 | 文件 | 职责 |
|------|------|------|
| 候选创建 | `packages/memory/service.py` | 幂等写入、排除检查、相似检测、质量门 |
| 质量门 | `packages/memory/quality_gate.py` | 五维评分（stable/reusable/actionable/scoped/evidence） |
| 相似检测 | `packages/memory/duplicate_detection.py` | 四路加权判重 |
| 评分 | `apps/worker/scoring.py` | value_score + novelty + priority |
| 去重 | `apps/worker/dedup.py` | 混合召回 + 关系分类 |
| 任务编排 | `apps/worker/tasks.py` | Embedding → Scoring → Dedup → Auto-approve |
| 审核路由 | `apps/api/routes/reviews.py` | 人工审核 API |
| 文件同步 | `apps/api/file_sync.py` | Memory → Markdown 镜像 |
| 复习服务 | `packages/memory/review_service.py` | SM-2 间隔重复（非候选审核） |
| MCP 适配 | `adapters/qoder/mcp_server.py` | Agent 接入层 |
| 信号引擎 | `adapters/qoder/signal_engine.py` | 事件→候选规则提取 |

## 6. 数据模型关系

```
Episode 1──N CandidateMemory N──1 Memory
                │                    │
                ├─ embedding         ├─ embedding
                ├─ value_score       ├─ version
                ├─ novelty           ├─ status (active/archived/superseded/conflicted)
                ├─ quality_gate_*    ├─ content_contract (JSON)
                ├─ status            ├─ valid_from / valid_to
                │  (pending_review/  │
                │   needs_enrichment/│
                │   approved/        ├─ MemoryVersion (版本快照)
                │   rejected)        ├─ MemoryLifecycleEvent
                │                    ├─ MemoryConflict
                └─ Evidence ─────────┴─ Evidence
```
