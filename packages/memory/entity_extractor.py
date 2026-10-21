"""轻量级实体抽取：jieba 词性标注 + 正则模式。"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 代码标识符模式：驼峰 / 下划线 / 常量大写 / 常见技术后缀
_CODE_PATTERNS = [
    re.compile(r"[a-z]+[A-Z][a-zA-Z]*"),
    re.compile(r"[a-z]+_[a-z_]+"),
    re.compile(r"[A-Z][A-Z0-9_]+"),
    re.compile(r"[a-zA-Z]+(?:Service|Manager|Handler|Factory|Builder|Config|Util|Helper)"),
]

# 领域实体模式：类名后缀、技术栈名称、框架注解/装饰器、检索术语、项目专有名词
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
]

_STOP_WORDS = frozenset(
    {
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
        "this",
        "that",
        "with",
        "for",
        "not",
        "but",
        "from",
        "have",
        "has",
        "its",
        "it",
        "in",
        "on",
        "at",
        "to",
        "of",
        "and",
        "or",
        "if",
    }
)


def extract_entities(text: str) -> list[str]:
    """三层抽取实体：jieba 词性过滤 → 领域正则 → 代码标识符正则。"""
    terms: set[str] = set()

    # jieba 未安装或分词失败时静默降级，正则两层仍可工作
    try:
        import jieba.posseg as pseg

        # 只保留名词类（n/nr/ns/nt/nz）、英文（eng）、动名词（vn），过滤动词/虚词噪声
        allowed_flags = {"n", "nr", "ns", "nt", "nz", "eng", "vn"}
        for word, flag in pseg.cut(text):
            w = word.strip()
            if len(w) >= 2 and flag in allowed_flags and w.lower() not in _STOP_WORDS:
                terms.add(w)
    except Exception:
        # 降级路径：实体抽取是增强功能，失败不应影响写入主流程
        logger.debug("jieba POS tagging failed", exc_info=True)

    for pattern in _ENTITY_PATTERNS:
        for match in pattern.findall(text):
            m = match.strip()
            if len(m) >= 2 and m.lower() not in _STOP_WORDS:
                terms.add(m)

    for pattern in _CODE_PATTERNS:
        for match in pattern.findall(text):
            m = match.strip()
            if len(m) > 2 and m.lower() not in _STOP_WORDS:
                terms.add(m)

    return sorted(terms)
