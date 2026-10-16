export interface Workspace {
  id: string
  name: string
  created_at: string
  updated_at: string
}

export interface FileMemory {
  id: string
  title: string
  content: string
  type: string
  tags: string
  related: string
  version: number
  status: string
  source: string
  workspace: string | null
  created: string
  updated: string
  file_path: string
  similarity_score?: number
  is_permanent?: boolean
  updated_at?: string
  last_used_at?: string
  score?: number
  confidence?: number
  usage_count?: number
}

export interface Memory {
  id: string
  workspace_id: string
  project_id: string | null
  title: string
  content: string
  type: string
  source: string
  status: string
  confidence: number
  importance: number
  version: number
  valid_from: string | null
  valid_to: string | null
  usage_count: number
  is_permanent: boolean
  permanent_reason: string | null
  last_used_at: string | null
  content_contract: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface Candidate {
  id: string
  workspace_id: string
  workspace_name: string | null
  title: string
  content: string
  type: string
  source: string
  value_score: number | null
  quality_score: number | null
  quality_gate_score: number | null
  quality_gate_reason: string | null
  review_priority: number | null
  confidence: number | null
  importance: number | null
  novelty: number | null
  reusability: number | null
  stability: number | null
  future_utility: number | null
  actionability: number | null
  evidence_strength: number | null
  scope_confidence: number | null
  duplicate_probability: number | null
  similar_memory_id: string | null
  similar_memory_source: string | null
  similar_memory_title: string | null
  similar_memory_content_preview: string | null
  similar_memory_type: string | null
  similar_memory_relation: string | null
  status: string
  content_contract: Record<string, unknown> | null
  quality_report: Record<string, unknown> | null
  relation_decision: Record<string, unknown> | null
  extraction_version: string | null
  created_at: string
  updated_at: string
}

export interface SearchResult {
  id: string
  title: string
  content: string
  type: string
  score: number | null
}

export interface VersionCommit {
  hash: string
  message: string
  date: string
}

export interface MemoryVersion {
  id: string
  memory_id: string
  version: number
  title: string
  content: string
  change_type: string
  changed_by_type: string
  changed_by_id: string | null
  reason: string | null
  created_at: string
}

export interface Review {
  id: string
  candidate_id: string
  reviewer_type: string
  reviewer_id: string | null
  action: string
  before_content: string | null
  after_content: string | null
  reason: string | null
  created_at: string
}

export interface Conflict {
  id: string
  workspace_id: string
  memory_id: string
  candidate_id: string | null
  conflict_type: string
  description: string | null
  evidence: Record<string, unknown> | null
  status: string
  resolution: string | null
  created_at: string
  resolved_at: string | null
}

export interface Feedback {
  id: string
  workspace_id: string
  memory_id: string
  feedback_type: string
  source_type: string
  source_id: string | null
  reason: string | null
  created_at: string
}

export interface OptimizeResult {
  original_title: string
  original_content: string
  optimized_title: string
  optimized_content: string
  changes: string
}

export interface LifecycleTimeline {
  event_type: string
  timestamp: string | null
  metadata: Record<string, unknown> | null
}

export interface Lifecycle {
  memory_id: string
  current_status: string
  timeline: LifecycleTimeline[]
  age_days: number | null
  event_count: number
}

export interface Relation {
  id: string
  source_memory_id: string
  target_memory_id: string
  relation_type: string
  confidence: number
}

export interface RelatedMemory {
  id: string
  title: string
  type: string
}

export interface MergeSuggestion {
  source_id: string
  source_title: string
  source_content_preview: string
  target_id: string
  target_title: string
  target_content_preview: string
  similarity: number
  relation_type: string
}

export interface EvolutionMetrics {
  period_days: number
  notes: { created: number; formalized: number; formalization_rate: number }
  submissions: { total: number; approved: number; rejected: number; approval_rate: number }
  memory_health: { active: number; avg_confidence: number }
}

export interface MemoryStatus {
  workspace_id: string
  version: string
  memories: { total: number; active: number }
  candidates: { pending_review: number }
  conflicts: { open: number }
  retrieval: { traces: number }
  insights: {
    submission_trend: string
    recent_submissions_7d: number
    type_distribution: Record<string, number>
    low_confidence_count: number
    suggestions: string[]
  }
  evolution_metrics: EvolutionMetrics
}

export interface AgentSession {
  id: string
  workspace_id: string
  agent: string
  agent_version: string | null
  repository: string | null
  branch: string | null
  task: string | null
  started_at: string
  ended_at: string | null
  outcome: string | null
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface Agent {
  id: string
  workspace_id: string
  name: string
  type: string
  adapter: string
  version: string | null
  status: string
  capabilities: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface AgentProfile {
  id: string
  workspace_id: string
  agent_id: string
  total_sessions: number
  total_memories_submitted: number
  total_notes_created: number
  note_formalization_rate: number
  nudge_response_rate: number
  preferred_signal_types: string[]
  preferred_memory_types: string[]
  preferred_nudge_types: string[]
  updated_at: string
}

export interface AgentStat {
  total_sessions: number
  success_count: number
  last_seen_at: string | null
  avg_duration_ms: number
  memory_count: number
}

export interface AgentStats {
  agents: Record<string, AgentStat>
  total_memory_submissions: number
}

export interface ConfigData {
  app: { debug: boolean }
  parasitic_evolution: {
    memory_gap_detection_enabled: boolean
    proactive_push_enabled: boolean
    memory_relations_enabled: boolean
    agent_profile_enabled: boolean
    memory_version_tracking_enabled: boolean
    auto_consolidate_enabled: boolean
    review_reminders_enabled: boolean
    mastery_coupled_decay_enabled: boolean
    entity_extraction_enabled: boolean
    write_time_conflict_enabled: boolean
    auto_merge_enabled: boolean
    auto_merge_threshold: number
    episodic_retrieval_enabled: boolean
  }
  memory: {
    title_max_length: number
    consolidate_threshold: number
    similarity_threshold: number
    relation_merge_threshold: number
    relation_update_threshold: number
    relation_conflict_threshold: number
    priority_discard_threshold: number
    priority_low_threshold: number
    priority_high_threshold: number
  }
  performance: {
    context_cache_ttl: number
    context_cache_max_size: number
    context_token_budget: number
    dedup_top_k: number
    merge_suggestions_limit: number
    merge_suggestions_top_k: number
    merge_suggestions_threshold: number
    auto_consolidate_limit: number
    auto_consolidate_top_k: number
  }
  retrieval: {
    bm25_weight: number
    vector_weight: number
    reranker_rrf_weight: number
    reranker_confidence_weight: number
    reranker_importance_weight: number
    reranker_freshness_weight: number
    reranker_usage_weight: number
    reranker_intent_weight: number
    reranker_key_term_bonus: number
  }
  system_info: {
    embedding_model: string
    embedding_dimensions: number
    database_url: string
    api_host: string
    api_port: number
    memory_dir: string
    config_path: string
  }
}

export interface ConfigPatchResult {
  applied: boolean
  changed_fields: string[]
}

export interface HealthResponse {
  status: string
  database: string
  version: string
}

export interface TaskQueueCounts {
  pending: number
  running: number
  completed: number
  failed: number
}

export interface TaskQueueRetryStats {
  /** 重试中：PENDING 且 retry_count > 0 */
  retrying: number
  /** 全部任务的平均重试次数（含 0 次任务） */
  average_retry_count: number
  max_retry_count: number
}

export interface FailedTaskItem {
  id: string
  name: string
  error: string | null
  retry_count: number
  created_at: string
  completed_at: string | null
}

export interface TaskQueueFailedInfo {
  /** 全量失败计数，items 截断至队列侧上限（50 条） */
  total: number
  items: FailedTaskItem[]
}

export interface TaskQueueStatusResponse {
  counts: TaskQueueCounts
  oldest_pending_age_seconds: number | null
  oldest_running_age_seconds: number | null
  retry: TaskQueueRetryStats
  failed: TaskQueueFailedInfo
}

export interface TaskQueueRetryResponse {
  task_id: string
  status: string
}

export interface ConsistencyReport {
  healthy: boolean
  db_count: number
  md_count: number
  index_count: number
  vector_count: number
  /** MD 缺失：DB 有而 MD 无；MD 孤儿：MD 有而 DB 无 */
  md_missing: string[]
  md_orphan: string[]
  /** 索引缺失：DB 有而 index.db（active 行）无 */
  index_missing: string[]
  /** 向量未覆盖的 active 记忆 id：截断展示，完整数量见 vectors_missing_total */
  vectors_missing: string[]
  vectors_missing_total: number
  /** 载体读取失败原因，键为载体名（db/md/index/vectors），非空即不健康 */
  errors: Record<string, string>
}

export interface MemoryHealth {
  memory_id: string
  utility: {
    retrieval_success: number
    agent_usage: number
    human_feedback: number
    freshness: number
    evidence_strength: number
    utility: number
  }
  health: {
    status: string
    score: number
    reasons: string[]
  }
}

export interface LearningSuggestion {
  memory_id: string
  title: string
  type: string
  confidence: number
  importance: number
  last_used_at: string | null
  reason: string
}

export interface MemoryGap {
  type: string
  count: number
  expected_ratio: number
  actual_ratio: number
}

export interface LearningSuggestions {
  low_confidence: LearningSuggestion[]
  stale: LearningSuggestion[]
  memory_gaps: MemoryGap[]
  total_suggestions: number
}

export interface Skill {
  name: string
  description: string
  body: string
  source: 'project' | 'qoder' | 'codex' | 'plugin'
  agents: string[]
  publishable_to: string[]
  available_to: string[]
  builtin: boolean
  provided_by: string[]
  path: string
  editable: boolean
}

export interface SessionNote {
  id: string
  workspace_id: string
  session_id: string
  content: string
  signal_type: string | null
  confidence: number | null
  formalized: boolean
  formalized_memory_id: string | null
  created_at: string
}

export interface ReviewItem {
  memory_id: string
  title: string
  content: string
  memory_type: string
  ease_factor: number
  interval_days: number
  repetitions: number
  next_review: string
  last_review: string | null
  days_overdue: number
  mastery_level: string
  total_reviews: number
}

export interface ReviewResult {
  memory_id: string
  ease_factor: number
  interval_days: number
  repetitions: number
  next_review: string
  last_review: string
  mastery_level: string
  total_reviews: number
}

export interface ReviewStats {
  total_scheduled: number
  due_now: number
  due_today: number
  reviewed_today: number
  mastery_distribution: Record<string, number>
  review_trend: Array<{ date: string; count: number }>
}
