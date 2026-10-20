"""查询分析器——将原始查询解析为结构化表示（PRD 第 15 节）。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnalyzedQuery:
    raw: str
    intent: str = "unknown"
    entities: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    is_question: bool = False
    confidence: float = 0.0
    is_short: bool = False
    is_complex: bool = False
    negations: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    key_terms: list[str] = field(default_factory=list)
    is_historical_query: bool = False

    def to_dict(self) -> dict[str, Any]:
        # 序列化结果中排除 raw 与 is_question（对下游无分析价值）。
        return {k: v for k, v in asdict(self).items() if k not in ("raw", "is_question")}


_INTENT_KEYWORDS: dict[str, list[str]] = {
    "project_rule": [
        "规则",
        "规范",
        "约定",
        "必须",
        "不能",
        "禁止",
        "要求",
        "rule",
        "convention",
        "must",
        "should not",
        "always",
        "never",
    ],
    "lesson": [
        "为什么",
        "坑",
        "问题",
        "经验",
        "教训",
        "踩坑",
        "出错",
        "失败",
        "why",
        "pitfall",
        "lesson",
        "gotcha",
        "mistake",
        "bug",
    ],
    "fact": [
        "是什么",
        "什么版本",
        "什么技术",
        "哪个",
        "多少",
        "what is",
        "which version",
        "fact",
        "version",
    ],
    "procedure": [
        "怎么",
        "如何",
        "步骤",
        "流程",
        "操作",
        "方法",
        "how to",
        "procedure",
        "steps",
        "guide",
    ],
    "constraint": [
        "限制",
        "约束",
        "不能",
        "上限",
        "最多",
        "constraint",
        "limit",
        "maximum",
        "boundary",
    ],
    "decision": [
        "决策",
        "决定",
        "选择了",
        "方案",
        "取舍",
        "权衡",
        "decision",
        "chose",
        "tradeoff",
        "alternative",
    ],
}

# 意图达到满置信度所需的命中关键词数。
_CONFIDENCE_FULL_MATCH = 3

# 历史意图查询标记：明确在问"X 出来之前/当初/演进"等往事的查询。
# 此类查询下过期（valid_to 已过）记忆正是答案，temporal 信号与
# stale 过滤应豁免，否则 gold 被压成底分/剔除（W4 C5-q2 实测）。
# "之前/以前"单独出现太宽（"检索之前先分词"是流程顺序非历史），
# 用"之前是怎么/之前用/X 之前"等组合限定误报。
_HISTORICAL_QUERY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"以前",
        r"之前是怎么",
        r"之前是",
        r"之前用",
        r"出来之前",
        r"推出之前",
        r"上线之前",
        r"发布之前",
        r"引入之前",
        r"出现之前",
        r"诞生之前",
        r"存在之前",
        r"当初",
        r"当年",
        r"曾经",
        r"历史上",
        r"历史方案",
        r"旧方案",
        r"旧版本",
        r"老版本",
        r"老方案",
        r"过去用",
        r"原来用",
        r"演进",
        r"演变",
        r"变迁",
        r"used to",
        r"previously",
        r"historically",
        r"legacy",
        r"old (?:version|approach|way)",
        r"before (?:switching|migrating|upgrading|we (?:used|adopted))",
    ]
]

# 预编译意图关键词正则（避免每个查询重复编译）。
_INTENT_KEYWORD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    intent: [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]
    for intent, keywords in _INTENT_KEYWORDS.items()
}

_SYNONYMS: dict[str, list[str]] = {
    "部署": ["发布", "上线", "deploy", "release", "publish"],
    "发布": ["部署", "上线", "deploy", "release", "publish"],
    "配置": ["设置", "参数", "config", "settings"],
    "设置": ["配置", "参数", "config", "settings"],
    "错误": ["异常", "报错", "失败", "error", "exception", "fail"],
    "异常": ["错误", "报错", "失败", "error", "exception", "fail"],
    "优化": ["改进", "提升", "性能", "optimize", "improve", "performance"],
    "改进": ["优化", "提升", "optimize", "improve", "enhance"],
    "检索": ["搜索", "查询", "召回", "search", "query", "retrieval", "查找"],
    "搜索": ["检索", "查询", "search", "query", "retrieval", "查找"],
    "记忆": ["知识", "笔记", "memory", "knowledge", "经验"],
    "知识": ["记忆", "笔记", "knowledge", "memory", "经验"],
    "重构": ["重写", "改造", "refactor", "rewrite"],
    "重写": ["重构", "改造", "refactor", "rewrite"],
    "测试": ["单测", "用例", "test", "unit test", "单元测试"],
    "缓存": ["cache", "redis", "memcached"],
    "数据库": ["db", "database", "mysql", "postgres", "sqlite"],
    "接口": ["api", "endpoint", "路由", "route"],
    "认证": ["鉴权", "授权", "登录", "auth", "authentication", "authorization"],
    "安全": ["security", "vulnerability", "漏洞"],
    "性能": ["performance", "速度", "延迟", "throughput", "响应时间"],
    "并发": ["parallel", "concurrent", "异步", "async"],
    "向量": ["embedding", "vector", "嵌入"],
    "关键词": ["keyword", "bm25", "全文搜索"],
    "相关性": ["relevance", "准确度", "匹配度"],
    "权重": ["weight", "系数", "参数"],
    "阈值": ["threshold", "临界值", "门限"],
    "排除": ["过滤", "排除清单", "exclusion", "filter"],
    "结构": ["structure", "格式", "format", "模板"],
    "查重": ["去重", "dedup", "duplicate", "相似检测"],
    "审核": ["review", "审批", "approve", "检查"],
}

_SYNONYM_REVERSE: dict[str, list[str]] = {}
for _term, _syns in _SYNONYMS.items():
    for _syn in _syns:
        _SYNONYM_REVERSE.setdefault(_syn.lower(), []).append(_term)

_ENTITY_PATTERNS = [
    re.compile(r"[A-Z][a-z]+(?:Service|Controller|Repository|Mapper|Interceptor|Handler|Config)"),
    re.compile(
        r"(?:Spring|MyBatis|Java|Python|React|Docker|Kubernetes|FastAPI|SQLAlchemy|Redis|Nginx"
        r"|Vue|Angular|Svelte|Next\.?js|Vite|Webpack|TypeScript|JavaScript|Go|Rust|Node\.?js"
        r"|PostgreSQL|MySQL|MongoDB|SQLite|Elasticsearch"
        r"|Kafka|RabbitMQ|Celery|gRPC|GraphQL|WebSocket|REST"
        r"|Terraform|Ansible|Helm|Prometheus|Grafana|Jenkins"
        r"|OAuth2?|JWT|SAML|OpenID)"
    ),
    re.compile(r"@?\w+(?:Transactional|Autowired|Component|Service|Repository|Fixture|Route)"),
    re.compile(r"\b(?:BM25|RRF|NDCG|FAISS|pgvector|TF-IDF|LSH|HNSW)\b"),
    re.compile(r"\b[A-Z]{2,}(?:API|SDK|CLI|UI|UX|CI|CD|ORM|SSO)\b"),
    re.compile(r"\b(?:memory_save|memory_search|memory_update|memory_review)\b"),
    re.compile(r"\b(?:cwiki|qoder|AGENTS\.md|config\.yaml)\b", re.IGNORECASE),
    re.compile(r"\b(?:embedding|reranker|retrieval|vector|bm25)\b", re.IGNORECASE),
    re.compile(r"\b(?:feedback|lesson|decision|fact|procedure|reference|convention)\b"),
]

_STOP_WORDS = frozenset(
    {
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "上",
        "也",
        "很",
        "到",
        "说",
        "要",
        "去",
        "你",
        "会",
        "着",
        "没有",
        "看",
        "好",
        "自己",
        "这",
        "他",
        "她",
        "它",
        "们",
        "那",
        "些",
        "什么",
        "怎么",
        "如何",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "about",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "our",
    }
)


def analyze_query(query: str) -> AnalyzedQuery:
    """解析查询：意图识别、实体抽取，以及否定/短语/关键词提取与同义词扩展。"""
    result = AnalyzedQuery(raw=query)

    result.is_question = (
        query.strip().endswith("?")
        or query.strip().endswith("？")
        or any(kw in query for kw in ["怎么", "如何", "为什么", "什么", "哪", "多少"])
    )

    query_stripped = query.strip()
    word_count = len(query_stripped.split())
    char_count = len(query_stripped)
    result.is_short = char_count < 10 or word_count <= 2
    result.is_complex = char_count > 50 or word_count > 8

    best_intent = "unknown"
    best_score = 0.0
    total_matches = 0
    for intent, keywords in _INTENT_KEYWORDS.items():
        patterns = _INTENT_KEYWORD_PATTERNS[intent]
        raw_hits = sum(1 for pat in patterns if pat.search(query))
        total_matches += raw_hits
        # 按关键词表长度归一，避免关键词多的意图获得不公平优势。
        normalized = raw_hits / len(keywords) if keywords else 0.0
        if normalized > best_score:
            best_score = normalized
            best_intent = intent
    if best_score > 0:
        result.intent = best_intent
        # 置信度 = 归一得分 × 关键词数 / 满分命中数（封顶 1.0）：
        # 绝对命中次数越多越可信，归一化只用于挑意图
        result.confidence = min(
            best_score * len(_INTENT_KEYWORDS.get(best_intent, [])) / _CONFIDENCE_FULL_MATCH, 1.0
        )

    seen_entities: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.finditer(query):
            entity = match.group()
            key = entity.lower()
            if key not in seen_entities:
                seen_entities.add(key)
                result.entities.append(entity)

    result.negations = _extract_negations(query)
    result.phrases = _extract_phrases(query)
    result.key_terms = _extract_key_terms(query)
    result.expanded_terms = _expand_synonyms(query, result.key_terms)
    result.needs = _infer_needs(result.intent, result.is_question)
    result.is_historical_query = any(p.search(query) for p in _HISTORICAL_QUERY_PATTERNS)

    return result


def _expand_synonyms(query: str, key_terms: list[str] | None = None) -> list[str]:
    expanded: list[str] = []
    query_lower = query.lower()

    for term, synonyms in _SYNONYMS.items():
        if term.lower() in query_lower:
            for syn in synonyms:
                if syn.lower() not in query_lower and syn not in expanded:
                    expanded.append(syn)

    tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z_]\w*", query)
    for token in tokens:
        if token.lower() in _STOP_WORDS or len(token) < 2:
            continue
        if token in _SYNONYMS:
            for syn in _SYNONYMS[token]:
                if syn.lower() not in query_lower and syn not in expanded:
                    expanded.append(syn)
        for original in _SYNONYM_REVERSE.get(token.lower(), []):
            if original not in query_lower and original not in expanded:
                expanded.append(original)

    # 扩展词最多 8 个：过多会稀释查询、拉低 BM25 相关性区分度
    return expanded[:8]


# 否定提取。疑问句式（"要不要加"、"需不需要"）形如"X 不 X"，其"不"字
# 子串会撞上否定模式——实测把"要不要加"提取出否定"加"，正文含该词的
# gold 记忆被 negation_penalty 乘 0.3 沉底（C11-q3 评测翻车根因）。
# 负向后顾断言排除前字相同的疑问式；真否定（"不要用 root"）不受影响。
_NEGATION_PATTERNS = [
    re.compile(r"(?<!要)不要([^\s,，。]+)"),
    re.compile(r"排除([^\s,，。]+)"),
    re.compile(r"除了([^\s,，。]+)(?:之外|以外)"),
    re.compile(r"(?<!需)不需要([^\s,，。]+)"),
    re.compile(r"(?<!想)不想要([^\s,，。]+)"),
    re.compile(r"(?<!包)不包括([^\s,，。]+)"),
    re.compile(r"(?<!含)不包含([^\s,，。]+)"),
    re.compile(r"without\s+([^\s,]+)", re.IGNORECASE),
    re.compile(r"exclude?\s+([^\s,]+)", re.IGNORECASE),
]


def _extract_negations(query: str) -> list[str]:
    negations: list[str] = []
    for pattern in _NEGATION_PATTERNS:
        for match in pattern.finditer(query):
            negated = match.group(1).strip()
            if negated and len(negated) < 20:
                negations.append(negated)
    return negations


_PHRASE_PATTERNS = [
    re.compile(r"[" "「]([^" "」]+)[" "」]"),
    re.compile(r"\*\*([^*]+)\*\*"),
    re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})"),
    re.compile(r"([\u4e00-\u9fff]{2,8})"),
]


def _extract_phrases(query: str) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for pattern in _PHRASE_PATTERNS:
        for match in pattern.finditer(query):
            phrase = match.group(1).strip()
            if phrase and phrase.lower() not in seen and len(phrase) >= 2:
                seen.add(phrase.lower())
                phrases.append(phrase)
    return phrases[:5]


def _extract_key_terms(query: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z_]\w{2,}", query)
    key_terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        lower = token.lower()
        if lower in _STOP_WORDS or lower in seen:
            continue
        seen.add(lower)
        key_terms.append(token)
    return key_terms[:10]


def _infer_needs(intent: str, is_question: bool) -> list[str]:
    needs_map = {
        "project_rule": ["rule", "constraint"],
        "lesson": ["lesson", "action"],
        "fact": ["fact"],
        "procedure": ["procedure", "steps"],
        "constraint": ["constraint", "rule"],
        "decision": ["decision", "rationale"],
    }
    needs = needs_map.get(intent, [])
    if is_question and not needs:
        needs = ["explanation"]
    return needs
