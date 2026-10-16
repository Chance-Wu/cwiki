"""Skill 发布逻辑——把项目 skills 发布/取消发布到各 Agent 目录。"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from apps.api.routes._skill_scanner import (
    PROJECT_SKILLS_DIR,
    SKILL_NAME_RE,
    SOURCE_MARKER,
    is_link,
    normalized_source,
    publication_kind,
)
from packages.domain.config import skills_config
from packages.domain.paths import validate_path_component


def _conflict(path: Path) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"Skill publication conflict at '{path}': unowned target or symlink/junction; "
        "existing files were preserved",
    )


def ensure_plain_tree(path: Path) -> None:
    """复制/删除前的预检：遇符号链接或 junction 立即报冲突，绝不深入遍历。"""
    if is_link(path):
        raise _conflict(path)
    if path.is_dir():
        for child in path.iterdir():
            ensure_plain_tree(child)


def ensure_plain_parents(path: Path) -> None:
    """检查各级父目录均非链接，防止把目标写到意外的挂载点之外。"""
    for parent in path.parents:
        if is_link(parent):
            raise _conflict(parent)


def _refresh_copy(source: Path, target: Path) -> None:
    ensure_plain_parents(target)
    ensure_plain_tree(source)
    ensure_plain_tree(target)
    # 通过临时目录做"备份旧目录 → 原子改名换新 → 删备份"，失败时回滚旧目录
    staging = Path(tempfile.mkdtemp(prefix=".cwiki-skill-", dir=target.parent))
    prepared = staging / "copy"
    backup = staging / "previous"
    try:
        shutil.copytree(source, prepared)
        (prepared / SOURCE_MARKER).write_text(
            json.dumps({"source": normalized_source(source)}), encoding="utf-8"
        )
        if target.exists():
            target.rename(backup)
        try:
            prepared.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if not backup.exists():
            shutil.rmtree(staging)


def validate_name(name: str, status_code: int = 422) -> str:
    try:
        validate_path_component(name)
        if not SKILL_NAME_RE.fullmatch(name):
            raise ValueError("Skill name must be kebab-case (lowercase letters, digits, hyphens)")
        return name
    except ValueError as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def get_agents_for_skill(skill_name: str) -> list[str]:
    """检查哪些 Agent 已存在由本项目发布的副本/链接。"""
    skill_name = validate_name(skill_name)
    source = PROJECT_SKILLS_DIR / skill_name
    enabled = []
    for agent_name, config in skills_config.agents.items():
        if publication_kind(config["skills_dir"] / skill_name, source):
            enabled.append(agent_name)
    return enabled


def detect_provided_by(skill_name: str) -> list[str]:
    """检测哪些 Agent 以内置或插件形式提供同名 skill。"""
    from apps.api.routes._skill_scanner import get_cached_index

    index = get_cached_index()
    for s in index.skills:
        if s["name"] == skill_name:
            return [a for a in s.get("provided_by", []) if a != "project"]
    return []


def _path_within(resolved: Path, base: Path | None) -> bool:
    """判断解析后的路径是否位于 base 目录内部。"""
    if not base:
        return False
    try:
        return resolved.is_relative_to(base.resolve())
    except (OSError, ValueError):
        return False


def detect_provided_by_path(source_path: Path) -> list[str]:
    """检测路径落在哪个 Agent 的 skills/plugins 目录内。"""
    resolved = source_path.resolve()
    providers: set[str] = set()
    for agent_name, config in skills_config.agents.items():
        if _path_within(resolved, config["skills_dir"]) or _path_within(
            resolved, config.get("plugins_dir")
        ):
            providers.add(agent_name)
    return sorted(providers)


def publishable_agents_for_skill(skill_name: str) -> list[str]:
    """列出尚未以内置/插件形式提供该 skill 的 Agent（可发布目标）。"""
    from apps.api.routes._skill_scanner import get_cached_index

    return get_cached_index().publishable_to(skill_name)


def available_agents_for_skill(skill_name: str) -> list[str]:
    """列出可访问该 skill 的 Agent（已发布、在 skills_dir 或插件缓存中）。"""
    from apps.api.routes._skill_scanner import get_cached_index

    index = get_cached_index()
    for s in index.skills:
        if s["name"] == skill_name and s.get("source") == "project":
            return list(s.get("available_to", []))
    return []


def build_skill_response(
    *,
    name: str,
    description: str,
    body: str,
    agents: list[str],
    provided_by: list[str],
    path: str,
) -> dict[str, Any]:
    """构建全部写端点共享的项目 skill 标准响应结构。"""
    return {
        "name": name,
        "description": description,
        "body": body,
        "source": "project",
        "agents": agents,
        "builtin": False,
        "editable": True,
        "provided_by": provided_by,
        "publishable_to": publishable_agents_for_skill(name),
        "available_to": available_agents_for_skill(name),
        "path": path,
    }


def publish_to_agent(skill_name: str, agent_name: str) -> bool:
    """仅发布/刷新归本项目所有的目标，不碰他人创建的目录。"""
    skill_name = validate_name(skill_name)
    if agent_name not in skills_config.agents:
        return False

    skills_dir = skills_config.agents[agent_name]["skills_dir"]
    skill_dir = PROJECT_SKILLS_DIR / skill_name
    ensure_plain_parents(skill_dir)
    ensure_plain_tree(skill_dir)
    if not skill_dir.is_dir():
        return False

    target = skills_dir / skill_name
    ensure_plain_parents(target)
    kind = publication_kind(target, skill_dir)
    if kind == "symlink":
        return True
    if kind == "copy":
        _refresh_copy(skill_dir, target)
        return True
    if target.exists() or is_link(target):
        raise _conflict(target)

    skills_dir.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(skill_dir.resolve(), target_is_directory=True)
    except OSError:
        if target.exists() or is_link(target):
            raise _conflict(target) from None
        _refresh_copy(skill_dir, target)
    return True


def unpublish_from_agent(skill_name: str, agent_name: str) -> bool:
    """仅移除由本项目托管的链接/副本，非托管目标保持原样。"""
    skill_name = validate_name(skill_name)
    if agent_name not in skills_config.agents:
        return False

    target = skills_config.agents[agent_name]["skills_dir"] / skill_name
    kind = publication_kind(target, PROJECT_SKILLS_DIR / skill_name)
    if kind == "symlink":
        target.unlink()
        return True
    if kind == "copy":
        ensure_plain_tree(target)
        shutil.rmtree(target)
        return True
    return False
