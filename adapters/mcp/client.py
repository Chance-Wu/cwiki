"""cwiki REST API 的轻量异步 HTTP 客户端封装。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import httpx

from packages.domain.config import API_V1_PREFIX

logger = logging.getLogger("cwiki-mcp")

_NULL_UUID = "00000000-0000-0000-0000-000000000000"  # 未关联会话时的全零占位 ID


def _set_if_not_none(d: dict[str, Any], key: str, value: Any) -> None:
    """仅当 value 非 None 时写入 d[key]。"""
    if value is not None:
        d[key] = value


class MemoryUpdateUncertainError(RuntimeError):
    """PATCH 可能已在服务端生效；调用方须先回读确认，再决定是否重试。"""

    def __init__(self, memory_id: str):
        self.memory_id = memory_id
        super().__init__(
            f"记忆 '{memory_id}' 更新结果不确定，可能已生效；客户端未自动重试。"
            "请先查询记忆正文和版本，确认结果后再决定是否重试。"
        )


class CwikiClient:
    """围绕 cwiki REST API 的轻量异步封装。"""

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        heavy_timeout: float = 60.0,
        search_timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        # 三档超时对应后端接口特性：普通请求 / 重负载（导入导出）/ 检索类接口
        self.timeout = timeout
        self.heavy_timeout = heavy_timeout
        self.search_timeout = search_timeout
        self.agent_session_id: str | None = None
        self.event_session_id: str | None = None
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=self.timeout,
                # 后端固定在本机 127.0.0.1，禁用环境/注册表代理，
                # 否则本地请求会被系统代理转发而超时。
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=30,
                ),
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    def _auth_headers(self) -> dict[str, str]:
        """服务端配置 auth_token 时透传 Bearer 头；未配置则不带（保持零鉴权兼容）。"""
        from packages.domain.config import settings

        if settings.api_auth_token:
            return {"Authorization": f"Bearer {settings.api_auth_token}"}
        return {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        headers = self._auth_headers()
        url = f"{self.base_url}{path}"
        req_kwargs: dict[str, Any] = {"json": json_body, "params": params, "headers": headers}
        if timeout is not None:
            req_kwargs["timeout"] = timeout

        # 503/429 与网络错误按指数退避重试（1s、2s），上限 max_retries 次
        for attempt in range(max_retries + 1):
            try:
                resp = await self.http.request(method, url, **req_kwargs)
                if resp.status_code in (503, 429) and attempt < max_retries:
                    wait = 2**attempt
                    logger.debug(
                        "Retrying %s %s after %ds (status %d)",
                        method,
                        path,
                        wait,
                        resp.status_code,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return cast("dict[str, Any]", resp.json())
            except httpx.RequestError as exc:
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.debug("Retrying %s %s after %ds (%s)", method, path, wait, exc)
                    await asyncio.sleep(wait)
                    continue
                raise
        return {}

    # -- REST 端点 -----------------------------------------------------------

    async def list_workspaces(self, limit: int = 100) -> dict[str, Any]:
        """列出全部工作区，自动翻页聚合。"""
        all_items: list[dict[str, Any]] = []
        offset = 0
        total = 0

        while True:
            params = {"offset": offset, "limit": min(limit, 100)}
            result = await self._request("GET", f"{API_V1_PREFIX}/workspaces", params=params)
            total = result.get("total", 0)
            items = result.get("items", [])
            all_items.extend(items)

            if len(all_items) >= total or not items:
                break
            offset += len(items)

        return {"total": total, "items": all_items}

    async def get_context(
        self,
        query: str,
        workspace_id: str,
        project: str | None = None,
        max_items: int = 10,
        max_tokens: int = 5000,
    ) -> dict[str, Any]:
        session_id = self.agent_session_id or _NULL_UUID
        body: dict[str, Any] = {
            "keyword": query,
            "workspace_id": workspace_id,
            "agent_id": _NULL_UUID,
            "session_id": session_id,
            "max_items": max_items,
            "max_tokens": max_tokens,
        }
        if project:
            body["project_id"] = project
        return await self._request(
            "POST", f"{API_V1_PREFIX}/context", json_body=body, timeout=self.search_timeout
        )

    async def search(
        self,
        query: str,
        workspace_id: str | None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "keyword": query,
            "limit": limit,
        }
        if workspace_id:
            body["workspace_id"] = workspace_id
        if filters:
            body["filters"] = filters
        return await self._request(
            "POST", f"{API_V1_PREFIX}/search", json_body=body, timeout=self.search_timeout
        )

    async def recall(
        self,
        query: str,
        workspace_id: str | None,
        limit: int = 10,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"keyword": query, "limit": limit}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self._request(
            "POST",
            f"{API_V1_PREFIX}/file-memories/search/semantic",
            json_body=body,
            timeout=self.search_timeout,
        )

    async def submit_candidate(
        self,
        title: str,
        content: str,
        memory_type: str,
        workspace_id: str,
        project_id: str | None = None,
        source: str | None = None,
        client_write_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": title,
            "content": content,
            "type": memory_type,
            "workspace_id": workspace_id,
        }
        if project_id:
            body["project_id"] = project_id
        if source:
            body["source"] = source
        if client_write_id:
            body["client_write_id"] = client_write_id
        return await self._request("POST", f"{API_V1_PREFIX}/candidates", json_body=body)

    async def get_memory_status(self, workspace_id: str) -> dict[str, Any]:
        params: dict[str, Any] = {"workspace_id": workspace_id}
        return await self._request("GET", f"{API_V1_PREFIX}/memory-status", params=params)

    async def update_memory(
        self,
        memory_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        status: str | None = None,
        reason: str | None = None,
        is_permanent: bool | None = None,
        permanent_reason: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        _set_if_not_none(body, "title", title)
        _set_if_not_none(body, "content", content)
        _set_if_not_none(body, "confidence", confidence)
        _set_if_not_none(body, "importance", importance)
        _set_if_not_none(body, "status", status)
        _set_if_not_none(body, "reason", reason)
        _set_if_not_none(body, "is_permanent", is_permanent)
        _set_if_not_none(body, "permanent_reason", permanent_reason)
        _set_if_not_none(body, "expected_version", expected_version)
        # max_retries=0：PATCH 可能已生效，自动重试有并发覆盖风险；
        # 不确定失败一律抛 MemoryUpdateUncertainError，交由调用方回读确认
        try:
            return await self._request(
                "PATCH", f"{API_V1_PREFIX}/memories/{memory_id}", json_body=body, max_retries=0
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise MemoryUpdateUncertainError(memory_id) from exc
            raise
        except (httpx.RequestError, ValueError) as exc:
            # 响应丢失/非法不代表写入失败，按结果不确定处理而非直接报错。
            raise MemoryUpdateUncertainError(memory_id) from exc

    async def get_raw_events(
        self,
        workspace_id: str,
        session_id: str | None = None,
        event_type: str | None = None,
        since_minutes: int = 60,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "workspace_id": workspace_id,
            "since_minutes": since_minutes,
            "limit": limit,
        }
        if session_id:
            params["session_id"] = session_id
        if event_type:
            params["event_type"] = event_type
        return await self._request(  # type: ignore[return-value]
            "GET", f"{API_V1_PREFIX}/events/raw", params=params
        )

    async def get_workers_candidates(
        self,
        workspace_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "workspace_id": workspace_id,
            "source": "worker",
            "status": "pending_review",
            "limit": limit,
        }
        result = await self._request("GET", f"{API_V1_PREFIX}/candidates", params=params)
        return cast("list[dict[str, Any]]", result.get("items", []))

    async def create_agent_session(
        self,
        workspace_id: str,
        agent: str,
        agent_version: str | None = None,
        repository: str | None = None,
        branch: str | None = None,
        task: str | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "workspace_id": workspace_id,
            "agent": agent,
        }
        if agent_version:
            body["agent_version"] = agent_version
        if repository:
            body["repository"] = repository
        if branch:
            body["branch"] = branch
        if task:
            body["task"] = task
        try:
            return await self._request("POST", f"{API_V1_PREFIX}/agent-sessions", json_body=body)
        except Exception as exc:
            logger.warning("Failed to create agent session: %s", exc)
            return None

    async def complete_agent_session(
        self,
        session_id: str,
        outcome: str = "unknown",
    ) -> dict[str, Any] | None:
        try:
            return await self._request(
                "POST",
                f"{API_V1_PREFIX}/agent-sessions/{session_id}/complete",
                json_body={"outcome": outcome},
            )
        except Exception as exc:
            logger.warning("Failed to complete agent session: %s", exc)
            return None

    async def list_open_agent_sessions(
        self,
        workspace_id: str | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出尚未写入 outcome（仍开放）的 agent session。"""
        params: dict[str, Any] = {"open_only": "true", "limit": 50}
        if workspace_id:
            params["workspace_id"] = workspace_id
        if agent:
            params["agent"] = agent
        try:
            result = await self._request("GET", f"{API_V1_PREFIX}/agent-sessions", params=params)
            if result and "items" in result:
                return cast("list[dict[str, Any]]", result["items"])
        except Exception as exc:
            logger.warning("Failed to list open agent sessions: %s", exc)
        return []

    async def create_session_note(
        self,
        session_id: str,
        workspace_id: str,
        content: str,
        signal_type: str = "other",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"session_id": session_id, "workspace_id": workspace_id}
        body: dict[str, Any] = {"content": content, "signal_type": signal_type}
        return await self._request(
            "POST", f"{API_V1_PREFIX}/session-notes", json_body=body, params=params
        )

    async def list_session_notes(
        self,
        session_id: str,
        formalized: bool | None = None,
        limit: int = 50,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # checkpoint 需要正文做规则提取；列表默认只回预览，显式要 full。
        params: dict[str, Any] = {"session_id": session_id, "limit": limit, "view": "full"}
        if formalized is not None:
            params["formalized"] = str(formalized).lower()
        if workspace_id:
            params["workspace_id"] = workspace_id
        result = await self._request("GET", f"{API_V1_PREFIX}/session-notes", params=params)
        return cast("list[dict[str, Any]]", result.get("items", []))

    async def formalize_session_note(
        self, note_id: str, memory_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"memory_id": memory_id} if memory_id else {}
        return await self._request(
            "PATCH", f"{API_V1_PREFIX}/session-notes/{note_id}/formalize", json_body=body
        )

    async def submit_feedback(
        self,
        memory_id: str,
        workspace_id: str,
        feedback_type: str,
        source_type: str = "agent",
        source_id: str = "cwiki",
        reason: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "memory_id": memory_id,
            "workspace_id": workspace_id,
            "feedback_type": feedback_type,
            "source_type": source_type,
            "source_id": source_id,
        }
        _set_if_not_none(body, "reason", reason)
        return await self._request("POST", f"{API_V1_PREFIX}/feedback", json_body=body)

    async def get_memory_lifecycle(self, memory_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{API_V1_PREFIX}/memories/{memory_id}/lifecycle")

    async def get_memory_relations(self, memory_id: str, depth: int = 1) -> dict[str, Any]:
        return await self._request(
            "GET", f"{API_V1_PREFIX}/memories/{memory_id}/relations", params={"depth": depth}
        )

    async def create_memory_relation(
        self,
        memory_id: str,
        target_memory_id: str,
        relation_type: str,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"{API_V1_PREFIX}/memories/{memory_id}/relations",
            json={
                "target_memory_id": target_memory_id,
                "relation_type": relation_type,
                "confidence": confidence,
            },
        )

    async def delete_memory_relation(self, memory_id: str, relation_id: str) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            f"{API_V1_PREFIX}/memories/{memory_id}/relations/{relation_id}",
        )

    async def rename_tag(
        self, tag_name: str, new_name: str, workspace_id: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._request(
            "PUT",
            f"{API_V1_PREFIX}/tags/{tag_name}",
            json={"new_name": new_name},
            params=params,
        )

    async def merge_tags(
        self, source_tags: list[str], target_tag: str, workspace_id: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._request(
            "POST",
            f"{API_V1_PREFIX}/tags/merge",
            json={"source_tags": source_tags, "target_tag": target_tag},
            params=params,
        )

    async def delete_tag(self, tag_name: str, workspace_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._request(
            "DELETE",
            f"{API_V1_PREFIX}/tags/{tag_name}",
            params=params,
        )

    async def list_tags(self, workspace_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._request("GET", f"{API_V1_PREFIX}/tags", params=params)

    async def search_memories_by_tags(
        self,
        workspace_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if workspace_id:
            params["workspace_id"] = workspace_id
        if tags:
            params["tags"] = ",".join(tags)
        return await self._request("GET", f"{API_V1_PREFIX}/memories", params=params)

    async def get_memory_versions(self, memory_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return await self._request(  # type: ignore[return-value]
            "GET", f"{API_V1_PREFIX}/memories/{memory_id}/versions", params={"limit": limit}
        )

    async def export_data(
        self,
        workspace_id: str,
        fmt: str = "json",
        entities: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"format": fmt}
        if entities:
            body["entities"] = entities
        params: dict[str, Any] = {"workspace_id": workspace_id}
        return await self._request(
            "POST",
            f"{API_V1_PREFIX}/data/export",
            json_body=body,
            params=params,
            timeout=self.heavy_timeout,
        )

    async def import_data(
        self,
        data: dict[str, Any],
        workspace_id: str,
        strategy: str = "skip",
    ) -> dict[str, Any]:
        import io
        import json as _json

        url = f"{self.base_url}{API_V1_PREFIX}/data/import"
        params: dict[str, Any] = {"workspace_id": workspace_id, "strategy": strategy}

        json_bytes = _json.dumps(data, ensure_ascii=False).encode("utf-8")
        files = {"file": ("export.json", io.BytesIO(json_bytes), "application/json")}
        resp = await self.http.post(
            url,
            params=params,
            files=files,
            timeout=self.heavy_timeout,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return cast("dict[str, Any]", resp.json())

    # ── 复习相关 ───────────────────────────────────────────────────────────────

    async def get_due_reviews(self, workspace_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取到期待复习的记忆（间隔重复调度）。"""
        params: dict[str, Any] = {"workspace_id": workspace_id, "limit": limit}
        return await self._request(  # type: ignore[return-value]
            "GET", f"{API_V1_PREFIX}/review/due", params=params
        )

    async def submit_review(
        self, memory_id: str, quality: int, workspace_id: str
    ) -> dict[str, Any]:
        """提交某条记忆的复习评分结果。"""
        params: dict[str, Any] = {"workspace_id": workspace_id}
        return await self._request(
            "POST",
            f"{API_V1_PREFIX}/review/{memory_id}",
            json_body={"quality": quality},
            params=params,
        )

    async def get_review_stats(self, workspace_id: str) -> dict[str, Any]:
        """获取工作区的复习统计。"""
        params: dict[str, Any] = {"workspace_id": workspace_id}
        return await self._request("GET", f"{API_V1_PREFIX}/review/stats", params=params)
