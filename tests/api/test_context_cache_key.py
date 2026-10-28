"""上下文检索缓存键回归：不同 project/session/过滤条件不能命中同一条缓存。"""

from __future__ import annotations

import uuid

from apps.api.routes.context import _cache_key
from packages.domain.schemas import ContextRequest


def _request(**overrides) -> ContextRequest:
    base = {
        "workspace_id": "ws",
        "agent_id": uuid.UUID(int=1),
        "session_id": uuid.UUID(int=2),
        "keyword": "缓存键",
    }
    base.update(overrides)
    return ContextRequest(**base)


def test_cache_key_separates_projects_and_sessions() -> None:
    base_key = _cache_key(_request())
    assert base_key != _cache_key(_request(project_id=uuid.uuid4()))
    assert base_key != _cache_key(_request(session_id=uuid.uuid4()))
    assert base_key != _cache_key(_request(mode="hybrid"))
    assert base_key != _cache_key(_request(max_tokens=8000))
    assert base_key != _cache_key(_request(event_types=["error"]))


def test_cache_key_stable_for_identical_requests() -> None:
    assert _cache_key(_request()) == _cache_key(_request())
