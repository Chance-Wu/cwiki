"""Skill 管理端点——基于文件，支持多 Agent。

路由处理器保持轻量；扫描与发布逻辑分别位于
``_skill_scanner`` 与 ``_skill_publisher``。
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from apps.api.auth import AgentIdentity
from apps.api.deps import require_scope
from apps.api.routes._skill_publisher import (
    build_skill_response,
    detect_provided_by,
    detect_provided_by_path,
    ensure_plain_parents,
    ensure_plain_tree,
    get_agents_for_skill,
    publish_to_agent,
    unpublish_from_agent,
    validate_name,
)
from apps.api.routes._skill_scanner import (
    PROJECT_SKILLS_DIR,
    SKILL_NAME_RE,
    SOURCE_MARKER,  # noqa: F401 — used by tests via skills.SOURCE_MARKER
    build_skill_md,
    get_cached_skills,
    invalidate_skills_cache,
    is_link,
    parse_skill_md,
    publication_kind,
)
from packages.domain.config import API_V1_PREFIX, skills_config
from packages.domain.paths import validate_path_component

# 向后兼容别名，供测试与内部调用方使用
_invalidate_skills_cache = invalidate_skills_cache
_get_agents_for_skill = get_agents_for_skill
_parse_skill_md = parse_skill_md
_publication_kind = publication_kind
_publish_to_agent = publish_to_agent

router = APIRouter(prefix=API_V1_PREFIX, tags=["skills"])


# --------------- Pydantic 模型 ---------------


class SkillCreate(BaseModel):
    name: str
    description: str
    body: str
    agents: list[str] = []

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        validate_path_component(v)
        if not SKILL_NAME_RE.fullmatch(v):
            raise ValueError("Skill name must be kebab-case (lowercase letters, digits, hyphens)")
        return v


class SkillUpdate(BaseModel):
    description: str | None = None
    body: str | None = None


class SkillImport(BaseModel):
    source_path: str


class SkillPublishRequest(BaseModel):
    agents: list[str]


# --------------- 读端点 ---------------


@router.get("/skills/agents")
async def list_skill_agents(
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:read"))] = None,
) -> list[str]:
    """列出所有配置了 skills 支持的 Agent。"""
    return list(skills_config.agents.keys())


@router.get("/skills")
async def list_skills(
    source: str | None = None,
    agent: str | None = None,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:read"))] = None,
) -> list[dict[str, Any]]:
    """列出 skills，可按来源过滤；省略 source 时返回全部。"""
    if source:
        result = get_cached_skills(source)
    else:
        result = get_cached_skills()
    if agent:
        result = [s for s in result if agent in s.get("agents", [])]
    return result


@router.get("/skills/{name}")
async def get_skill(
    name: str,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:read"))] = None,
) -> dict[str, Any]:
    """获取 skill 详情（含完整正文）。"""
    for skill in get_cached_skills():
        if skill["name"] == name:
            return skill
    raise HTTPException(status_code=404, detail="Skill not found")


# --------------- 写端点 ---------------


@router.post("/skills", status_code=201)
async def create_skill(
    body: SkillCreate,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:write"))] = None,
) -> dict[str, Any]:
    """创建新项目 skill，并可选发布到各 Agent。"""
    skill_dir = PROJECT_SKILLS_DIR / body.name
    skill_md = skill_dir / "SKILL.md"

    ensure_plain_parents(skill_dir)
    if skill_dir.exists() or is_link(skill_dir):
        raise HTTPException(status_code=409, detail=f"Skill '{body.name}' already exists")
    for agent_name in body.agents:
        if agent_name in skills_config.agents:
            target = skills_config.agents[agent_name]["skills_dir"] / body.name
            ensure_plain_parents(target)
            if target.exists() or is_link(target):
                from apps.api.routes._skill_publisher import _conflict

                raise _conflict(target)

    skill_dir.mkdir(parents=True, exist_ok=True)
    content = build_skill_md(body.name, body.description, body.body)
    await asyncio.to_thread(skill_md.write_text, content, encoding="utf-8")

    enabled_agents = []
    for agent_name in body.agents:
        if agent_name in skills_config.agents and publish_to_agent(body.name, agent_name):
            enabled_agents.append(agent_name)

    invalidate_skills_cache()
    return build_skill_response(
        name=body.name,
        description=body.description,
        body=body.body,
        agents=enabled_agents,
        provided_by=[],
        path=str(skill_md),
    )


@router.patch("/skills/{name}")
async def update_skill(
    name: str,
    body: SkillUpdate,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:write"))] = None,
) -> dict[str, Any]:
    """更新项目 skill 并刷新其托管副本。"""
    name = validate_name(name)
    skill_dir = PROJECT_SKILLS_DIR / name
    ensure_plain_parents(skill_dir)
    ensure_plain_tree(skill_dir)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise HTTPException(status_code=404, detail="Skill not found")

    # 先检查所有副本再写源目录，链接冲突时源文件保持原样
    enabled_agents = get_agents_for_skill(name)
    for agent_name in enabled_agents:
        target = skills_config.agents[agent_name]["skills_dir"] / name
        if publication_kind(target, skill_dir) == "copy":
            ensure_plain_tree(target)

    parsed = parse_skill_md(skill_md)
    if not parsed:
        raise HTTPException(status_code=422, detail="Invalid SKILL.md format")

    new_desc = body.description if body.description is not None else parsed["description"]
    new_body = body.body if body.body is not None else parsed["body"]

    content = build_skill_md(name, new_desc, new_body)
    await asyncio.to_thread(skill_md.write_text, content, encoding="utf-8")

    for agent_name in enabled_agents:
        publish_to_agent(name, agent_name)
    invalidate_skills_cache()
    return build_skill_response(
        name=name,
        description=new_desc,
        body=new_body,
        agents=enabled_agents,
        provided_by=detect_provided_by(name),
        path=str(skill_md),
    )


@router.delete("/skills/{name}", status_code=204)
async def delete_skill(
    name: str,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:write"))] = None,
) -> None:
    """删除项目 skill，并从所有 Agent 移除。"""
    name = validate_name(name)
    skill_dir = PROJECT_SKILLS_DIR / name
    ensure_plain_parents(skill_dir)
    ensure_plain_tree(skill_dir)
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")

    for agent_name in skills_config.agents:
        unpublish_from_agent(name, agent_name)

    await asyncio.to_thread(shutil.rmtree, skill_dir)
    invalidate_skills_cache()


@router.post("/skills/{name}/publish")
async def publish_skill(
    name: str,
    body: SkillPublishRequest | None = None,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:write"))] = None,
) -> dict[str, Any]:
    """把项目 skill 发布到指定 Agent（默认 qoder）。"""
    name = validate_name(name)
    skill_dir = PROJECT_SKILLS_DIR / name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")

    target_agents = body.agents if body and body.agents else ["qoder"]
    enabled_agents = []

    for agent_name in target_agents:
        if agent_name in skills_config.agents and publish_to_agent(name, agent_name):
            enabled_agents.append(agent_name)

    parsed = parse_skill_md(skill_dir / "SKILL.md")
    invalidate_skills_cache()
    return build_skill_response(
        name=name,
        description=parsed["description"] if parsed else "",
        body=parsed["body"] if parsed else "",
        agents=enabled_agents,
        provided_by=detect_provided_by(name),
        path=str(skill_dir / "SKILL.md"),
    )


@router.post("/skills/{name}/unpublish")
async def unpublish_skill(
    name: str,
    body: SkillPublishRequest | None = None,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:write"))] = None,
) -> dict[str, Any]:
    """从指定 Agent 取消发布 skill（默认全部 Agent）。"""
    name = validate_name(name)
    skill_dir = PROJECT_SKILLS_DIR / name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")

    target_agents = body.agents if body and body.agents else list(skills_config.agents.keys())

    for agent_name in target_agents:
        unpublish_from_agent(name, agent_name)

    enabled_agents = get_agents_for_skill(name)
    parsed = parse_skill_md(skill_dir / "SKILL.md")
    invalidate_skills_cache()
    return build_skill_response(
        name=name,
        description=parsed["description"] if parsed else "",
        body=parsed["body"] if parsed else "",
        agents=enabled_agents,
        provided_by=detect_provided_by(name),
        path=str(skill_dir / "SKILL.md"),
    )


@router.post("/skills/import", status_code=201)
async def import_skill(
    body: SkillImport,
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("skills:write"))] = None,
) -> dict[str, Any]:
    """从任意路径把 skill 导入项目 skills 目录。"""
    source = Path(body.source_path).expanduser().resolve()

    if source.is_file() and source.name == "SKILL.md":
        source_dir = source.parent
    elif source.is_dir():
        source_dir = source
    else:
        raise HTTPException(
            status_code=400, detail="Path must point to a SKILL.md file or a skill directory"
        )

    skill_md = source_dir / "SKILL.md"
    if not skill_md.is_file():
        raise HTTPException(status_code=400, detail="No valid SKILL.md found at source path")

    parsed = parse_skill_md(skill_md)
    if not parsed:
        raise HTTPException(
            status_code=400, detail="Invalid SKILL.md format (missing name in frontmatter)"
        )

    name = validate_name(parsed["name"], status_code=400)
    dest_dir = PROJECT_SKILLS_DIR / name
    ensure_plain_parents(dest_dir)
    if dest_dir.exists() or is_link(dest_dir):
        raise HTTPException(status_code=409, detail=f"Skill '{name}' already exists in project")

    ensure_plain_tree(source_dir)
    await asyncio.to_thread(shutil.copytree, source_dir, dest_dir)

    provided_by = detect_provided_by_path(source_dir)

    dest_md = dest_dir / "SKILL.md"
    invalidate_skills_cache()
    return build_skill_response(
        name=parsed["name"],
        description=parsed["description"],
        body=parsed["body"],
        agents=[],
        provided_by=provided_by,
        path=str(dest_md),
    )
