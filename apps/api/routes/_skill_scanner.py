"""Skill 扫描逻辑——从项目、Agent 目录与插件源中发现 skills。

架构：SkillIndex 是由单次文件系统遍历构建的统一只读索引，所有关系
查询（provided_by / available_to / publishable_to）均直接从缓存索引
应答，避免重复 I/O。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from packages.domain.config import skills_config

PROJECT_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
SOURCE_MARKER = ".cwiki-source.json"
# 与 dsh（@deepseek-ai/dsh-skill 的 SKILL_NAME）同款 kebab 语法：不允许
# 前导/连续/尾随连字符——这类名字会被 dsh 以 invalid skill name 静默忽略。
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# --------------- 文件系统辅助函数 ---------------


def is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def normalized_source(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def read_marker_text(marker: Path) -> str:
    return marker.read_text(encoding="utf-8")


def parse_skill_md(path: Path) -> dict[str, Any] | None:
    """解析 SKILL.md frontmatter，返回含 name/description/body 的 dict，失败返回 None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    try:
        meta = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None

    if not isinstance(meta, dict) or not isinstance(meta.get("name"), str) or not meta["name"]:
        return None

    body = text[end + 3 :].strip()
    return {
        "name": meta["name"],
        "description": meta.get("description", ""),
        "body": body,
    }


def build_skill_md(name: str, description: str, body_text: str) -> str:
    """生成带 YAML 安全 frontmatter 的 SKILL.md 内容。"""
    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        default_flow_style=False,
        allow_unicode=True,
    ).rstrip()
    return f"---\n{frontmatter}\n---\n\n{body_text}\n"


_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "src",
        "tests",
        "docs",
        "scripts",
        "templates",
        "references",
        "models",
        "datasets",
        "vendor",
        "agents",
        "commands",
        "hooks",
        "runtime",
        "canvases",
        "examples",
        "shared",
        "bin",
        "resources",
        "dist",
        "lib",
        "tools",
    }
)


def _walk_skill_mds(root: Path) -> list[Path]:
    """查找 root 下的 SKILL.md 文件。

    跳过已知不含 skill 的大目录（node_modules、src、tests 等），
    避免遍历无意义的大子树。
    """
    result: list[Path] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            if "SKILL.md" in filenames:
                result.append(Path(dirpath) / "SKILL.md")
    except OSError:
        pass
    return result


def publication_kind(path: Path, source: Path) -> str | None:
    """判定目标归属：仅精确指向 source 的链接或带来源标记的副本算 cwiki 托管。"""
    if any(is_link(parent) for parent in path.parents) or (
        hasattr(path, "is_junction") and path.is_junction()
    ):
        return None
    if path.is_symlink():
        try:
            if path.is_dir() and normalized_source(path) == normalized_source(source):
                return "symlink"
        except (OSError, RuntimeError):
            pass
        return None
    if not path.is_dir():
        return None
    marker = path / SOURCE_MARKER
    if is_link(marker):
        return None
    try:
        data = json.loads(read_marker_text(marker))
        if isinstance(data, dict) and data.get("source") == normalized_source(source):
            return "copy"
    except (OSError, ValueError, RuntimeError):
        pass
    return None


# --------------- SkillIndex ---------------


@dataclass
class _BuildContext:
    """SkillIndex.build() 的上下文，管理构建过程中的所有状态。"""

    main_skills: dict[str, dict[str, Any]] = field(default_factory=dict)
    unrelated_skills: list[dict[str, Any]] = field(default_factory=list)
    plugin_pairs: set[tuple[str, str]] = field(default_factory=set)
    avail: dict[str, set[str]] = field(default_factory=dict)
    unrelated_agents: dict[str, set[str]] = field(default_factory=dict)
    unrelated_pairs: set[tuple[str, str]] = field(default_factory=set)
    parsed_cache: dict[Path, dict[str, Any] | None] = field(default_factory=dict)
    pub_cache: dict[tuple[Path, Path], str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """初始化 avail 字典，为每个 agent 创建空集合。"""
        self.avail = {a: set() for a in skills_config.agents}

    def cached_parse(self, path: Path) -> dict[str, Any] | None:
        """带缓存的 parse_skill_md。"""
        if path not in self.parsed_cache:
            self.parsed_cache[path] = parse_skill_md(path)
        return self.parsed_cache[path]

    def cached_pub_kind(self, path: Path, source: Path) -> str | None:
        """带缓存的 publication_kind。"""
        key = (path, source)
        if key not in self.pub_cache:
            self.pub_cache[key] = publication_kind(path, source)
        return self.pub_cache[key]


class SkillIndex:
    """由单次文件系统遍历构建的只读 skill 索引。

    预先计算全部关系（provided_by / available_to / publishable_to）。
    通过 ``SkillIndex.build()`` 构建，不要直接实例化。
    """

    __slots__ = (
        "_plugin_pairs",
        "_skills",
        "_unrelated_agents",
        "_unrelated_pairs",
    )

    def __init__(
        self,
        skills: list[dict[str, Any]],
        plugin_pairs: set[tuple[str, str]],
        unrelated_agents: dict[str, set[str]],
        unrelated_pairs: set[tuple[str, str]],
    ) -> None:
        self._skills = skills
        self._plugin_pairs = plugin_pairs
        self._unrelated_agents = unrelated_agents
        self._unrelated_pairs = unrelated_pairs

    @property
    def skills(self) -> list[dict[str, Any]]:
        return self._skills

    def publishable_to(self, name: str) -> list[str]:
        return sorted(a for a in skills_config.agents if (a, name) not in self._plugin_pairs)

    # ---- 构建器 ----

    @classmethod
    def build(cls) -> SkillIndex:
        """单趟扫描：项目 → Agent skills_dir → Agent plugins_dir。

        分为 5 个阶段：
        1. 扫描项目 skills
        2. 预扫描各 Agent 目录
        3. 处理 Agent 内置 skills
        4. 处理插件 skills
        5. 标注发布/可用关系
        """
        ctx = _BuildContext()

        # 阶段 1：扫描项目 skills
        cls._scan_project_skills(ctx)

        # 阶段 2：预扫描各 Agent 目录
        agent_skills_map, agent_plugins_map = cls._prescan_agent_directories(ctx)

        # 阶段 3：处理 Agent 内置 skills
        cls._process_agent_builtin_skills(ctx, agent_skills_map)

        # 阶段 4：处理插件 skills
        cls._process_plugin_skills(ctx, agent_plugins_map)

        # 阶段 5：标注发布/可用关系
        cls._annotate_relationships(ctx)

        return cls(
            skills=list(ctx.main_skills.values()) + ctx.unrelated_skills,
            plugin_pairs=ctx.plugin_pairs,
            unrelated_agents=ctx.unrelated_agents,
            unrelated_pairs=ctx.unrelated_pairs,
        )

    @classmethod
    def _scan_project_skills(cls, ctx: _BuildContext) -> None:
        """阶段 1：扫描项目 skills 目录。"""
        if not PROJECT_SKILLS_DIR.is_dir():
            return

        for entry in PROJECT_SKILLS_DIR.iterdir():
            if entry.name.startswith(".") or not SKILL_NAME_RE.fullmatch(entry.name):
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            parsed = ctx.cached_parse(skill_md)
            if not parsed:
                continue
            skill_entry: dict[str, Any] = {
                **parsed,
                "source": "project",
                "agents": [],
                "builtin": False,
                "editable": True,
                "path": str(skill_md),
                "provided_by": [],
                "publishable_to": [],
                "available_to": [],
            }
            ctx.main_skills[skill_entry["name"]] = skill_entry

    @classmethod
    def _prescan_agent_directories(
        cls, ctx: _BuildContext
    ) -> tuple[dict[str, dict[str, Path]], dict[str, dict[str, Path]]]:
        """阶段 2：预扫描各 Agent 目录（每个目录只读一次，解析走缓存）。"""
        agent_skills_map: dict[str, dict[str, Path]] = {}
        agent_plugins_map: dict[str, dict[str, Path]] = {}

        for agent_name, config in skills_config.agents.items():
            # 扫描 skills_dir
            skills_dir = config["skills_dir"]
            if skills_dir.is_dir():
                smap: dict[str, Path] = {}
                for entry in skills_dir.iterdir():
                    if not entry.name.startswith(".") and (entry / "SKILL.md").is_file():
                        smap[entry.name] = entry
                agent_skills_map[agent_name] = smap

            # 扫描 plugins_dir
            plugins_dir = config.get("plugins_dir")
            if plugins_dir and plugins_dir.is_dir():
                pmap: dict[str, Path] = {}
                for skill_md in _walk_skill_mds(plugins_dir):
                    parsed = ctx.cached_parse(skill_md)
                    if parsed and parsed["name"] not in pmap:
                        pmap[parsed["name"]] = skill_md
                agent_plugins_map[agent_name] = pmap

        return agent_skills_map, agent_plugins_map

    @classmethod
    def _process_agent_builtin_skills(
        cls, ctx: _BuildContext, agent_skills_map: dict[str, dict[str, Path]]
    ) -> None:
        """阶段 3：处理 Agent 内置 skills（复用解析缓存）。"""
        for agent_name in skills_config.agents:
            for name, entry_dir in agent_skills_map.get(agent_name, {}).items():
                skill_md = entry_dir / "SKILL.md"
                parsed = ctx.cached_parse(skill_md)
                if not parsed:
                    continue

                ctx.avail.setdefault(name, set()).add(agent_name)
                existing = ctx.main_skills.get(name)

                if existing is not None:
                    if existing["source"] == "project":
                        if not ctx.cached_pub_kind(entry_dir, PROJECT_SKILLS_DIR / name):
                            # 非项目发布的副本，作为独立条目
                            skill_entry = _make_entry(
                                parsed,
                                source=agent_name,
                                agents=[agent_name],
                                builtin=True,
                                editable=False,
                                provided_by=[agent_name],
                                path=skill_md,
                            )
                            ctx.unrelated_skills.append(skill_entry)
                            ctx.unrelated_agents.setdefault(name, set()).add(agent_name)
                            ctx.unrelated_pairs.add((agent_name, name))
                            continue
                        # 项目发布的副本，更新 provided_by
                        if agent_name not in existing["provided_by"]:
                            existing["provided_by"].append(agent_name)
                    elif agent_name not in existing["agents"]:
                        # 非项目来源，更新 agents 列表
                        existing["agents"].append(agent_name)
                        if agent_name not in existing.get("provided_by", []):
                            existing.setdefault("provided_by", []).append(agent_name)
                else:
                    # 新条目
                    skill_entry = _make_entry(
                        parsed,
                        source=agent_name,
                        agents=[agent_name],
                        builtin=True,
                        editable=False,
                        provided_by=[agent_name],
                        path=skill_md,
                    )
                    ctx.main_skills[name] = skill_entry

    @classmethod
    def _process_plugin_skills(
        cls, ctx: _BuildContext, agent_plugins_map: dict[str, dict[str, Path]]
    ) -> None:
        """阶段 4：处理插件 skills（复用解析缓存）。"""
        seen_plugin_unrelated: set[str] = set()
        for agent_name in skills_config.agents:
            for name, skill_md_path in agent_plugins_map.get(agent_name, {}).items():
                parsed = ctx.cached_parse(skill_md_path)
                if not parsed:
                    continue

                ctx.plugin_pairs.add((agent_name, name))
                ctx.avail.setdefault(name, set()).add(agent_name)
                existing = ctx.main_skills.get(name)

                if existing is not None:
                    if existing["source"] == "project":
                        if not ctx.cached_pub_kind(
                            Path(skill_md_path).parent, PROJECT_SKILLS_DIR / name
                        ):
                            # 非项目发布的插件副本
                            if name not in seen_plugin_unrelated:
                                seen_plugin_unrelated.add(name)
                                skill_entry = _make_entry(
                                    parsed,
                                    source="plugin",
                                    agents=[agent_name],
                                    builtin=True,
                                    editable=False,
                                    provided_by=[agent_name],
                                    path=skill_md_path,
                                )
                                ctx.unrelated_skills.append(skill_entry)
                                ctx.unrelated_agents.setdefault(name, set()).add(agent_name)
                                ctx.unrelated_pairs.add((agent_name, name))
                            else:
                                ctx.unrelated_agents.setdefault(name, set()).add(agent_name)
                                ctx.unrelated_pairs.add((agent_name, name))
                            continue
                        # 项目发布的插件，更新 provided_by
                        if agent_name not in existing["provided_by"]:
                            existing["provided_by"].append(agent_name)
                    elif agent_name not in existing["agents"]:
                        # 非项目来源，更新 agents 列表
                        existing["agents"].append(agent_name)
                        if agent_name not in existing.get("provided_by", []):
                            existing.setdefault("provided_by", []).append(agent_name)
                else:
                    # 新条目
                    skill_entry = _make_entry(
                        parsed,
                        source="plugin",
                        agents=[agent_name],
                        builtin=True,
                        editable=False,
                        provided_by=[agent_name],
                        path=skill_md_path,
                    )
                    ctx.main_skills[name] = skill_entry

    @classmethod
    def _annotate_relationships(cls, ctx: _BuildContext) -> None:
        """阶段 5：标注发布/可用关系（复用 publication_kind 缓存）。"""
        # 收集所有 agents 关系
        all_skills = list(ctx.main_skills.values()) + ctx.unrelated_skills
        for skill_entry in all_skills:
            for agent in skill_entry.get("agents", []):
                ctx.avail.setdefault(skill_entry["name"], set()).add(agent)

        # 标注 publishable_to 和 available_to
        for skill_entry in all_skills:
            name = skill_entry["name"]
            # 项目 skills：计算可发布的 agents
            if skill_entry.get("source") == "project":
                pub_agents: list[str] = []
                source = PROJECT_SKILLS_DIR / name
                for agent_name, config in skills_config.agents.items():
                    if ctx.cached_pub_kind(config["skills_dir"] / name, source):
                        pub_agents.append(agent_name)
                skill_entry["agents"] = pub_agents
                for agent in pub_agents:
                    ctx.avail.setdefault(name, set()).add(agent)

            # 计算 publishable_to（排除已有插件的 agents）
            skill_entry["publishable_to"] = sorted(
                a for a in skills_config.agents if (a, name) not in ctx.plugin_pairs
            )

            # 计算 available_to
            uref_agents = ctx.unrelated_agents.get(name, set())
            uref_pairs = ctx.unrelated_pairs

            if skill_entry.get("source") not in ("project",) and name in ctx.unrelated_agents:
                skill_entry["available_to"] = sorted(skill_entry.get("agents", []))
            else:
                skill_entry["available_to"] = sorted(
                    a
                    for a in ctx.avail.get(name, set())
                    if a not in uref_agents and (a, name) not in uref_pairs
                )


def _make_entry(
    parsed: dict[str, Any],
    *,
    source: str,
    agents: list[str],
    builtin: bool,
    editable: bool,
    provided_by: list[str],
    path: Path | str,
) -> dict[str, Any]:
    return {
        **parsed,
        "source": source,
        "agents": agents,
        "builtin": builtin,
        "editable": editable,
        "path": str(path),
        "provided_by": list(provided_by),
        "publishable_to": [],
        "available_to": [],
    }


# --------------- 单源懒扫描 ---------------


def _scan_project_skills() -> list[dict[str, Any]]:
    """快速扫描：仅项目 skills（不遍历插件目录）。"""
    result: list[dict[str, Any]] = []
    if not PROJECT_SKILLS_DIR.is_dir():
        return result
    for entry in PROJECT_SKILLS_DIR.iterdir():
        if entry.name.startswith(".") or not SKILL_NAME_RE.fullmatch(entry.name):
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        parsed = parse_skill_md(skill_md)
        if not parsed:
            continue
        pub_agents: list[str] = []
        for agent_name, config in skills_config.agents.items():
            if publication_kind(config["skills_dir"] / entry.name, entry) is not None:
                pub_agents.append(agent_name)
        result.append(
            {
                **parsed,
                "source": "project",
                "agents": pub_agents,
                "builtin": False,
                "editable": True,
                "path": str(skill_md),
                "provided_by": [],
                "publishable_to": sorted(skills_config.agents.keys()),
                "available_to": pub_agents,
            }
        )
    return result


def _scan_agent_skills(agent_name: str) -> list[dict[str, Any]]:
    """扫描单个 Agent 的内置 + 插件 skills。"""
    config = skills_config.agents.get(agent_name)
    if not config:
        return []
    by_name: dict[str, dict[str, Any]] = {}

    skills_dir = config["skills_dir"]
    if skills_dir.is_dir():
        for entry in skills_dir.iterdir():
            if entry.name.startswith("."):
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            parsed = parse_skill_md(skill_md)
            if not parsed:
                continue
            by_name[parsed["name"]] = {
                **parsed,
                "source": agent_name,
                "agents": [agent_name],
                "builtin": True,
                "editable": False,
                "path": str(skill_md),
                "provided_by": [agent_name],
                "publishable_to": [],
                "available_to": [agent_name],
            }

    plugins_dir = config.get("plugins_dir")
    if plugins_dir and plugins_dir.is_dir():
        for skill_md in _walk_skill_mds(plugins_dir):
            parsed = parse_skill_md(skill_md)
            if not parsed or parsed["name"] in by_name:
                continue
            by_name[parsed["name"]] = {
                **parsed,
                "source": "plugin",
                "agents": [agent_name],
                "builtin": True,
                "editable": False,
                "path": str(skill_md),
                "provided_by": [agent_name],
                "publishable_to": [],
                "available_to": [agent_name],
            }

    return list(by_name.values())


# --------------- 模块级缓存 ---------------

_INDEX_CACHE_TTL = 10.0
_index_cache: tuple[float, SkillIndex] | None = None
_source_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def invalidate_skills_cache() -> None:
    global _index_cache
    _index_cache = None
    _source_cache.clear()


def _get_source_skills(source: str) -> list[dict[str, Any]]:
    """返回单个来源的缓存 skills，未命中时现场扫描。"""
    now = time.monotonic()
    cached = _source_cache.get(source)
    if cached and (now - cached[0]) < _INDEX_CACHE_TTL:
        return cached[1]
    if source == "project":
        skills = _scan_project_skills()
    else:
        skills = _scan_agent_skills(source)
    _source_cache[source] = (now, skills)
    return skills


def get_cached_index() -> SkillIndex:
    global _index_cache
    now = time.monotonic()
    if _index_cache is not None and (now - _index_cache[0]) < _INDEX_CACHE_TTL:
        return _index_cache[1]
    index = SkillIndex.build()
    _index_cache = (now, index)
    return index


def get_cached_skills(source: str | None = None) -> list[dict[str, Any]]:
    if source:
        return _get_source_skills(source)
    return get_cached_index().skills


def scan_all_skills() -> list[dict[str, Any]]:
    return SkillIndex.build().skills


# --------------- 旧版辅助函数（保持向后兼容） ---------------


def _agent_builtin_names(agent_name: str) -> set[str]:
    config = skills_config.agents.get(agent_name)
    if not config:
        return set()
    names: set[str] = set()
    skills_dir = config["skills_dir"]
    if skills_dir.is_dir():
        for entry in skills_dir.iterdir():
            if not entry.name.startswith(".") and (entry / "SKILL.md").is_file():
                names.add(entry.name)
    plugins_dir = config.get("plugins_dir")
    if plugins_dir and plugins_dir.is_dir():
        for skill_md in _walk_skill_mds(plugins_dir):
            parsed = parse_skill_md(skill_md)
            if parsed:
                names.add(parsed["name"])
    return names


def _agent_plugin_names(agent_name: str) -> set[str]:
    config = skills_config.agents.get(agent_name)
    if not config:
        return set()
    names: set[str] = set()
    plugins_dir = config.get("plugins_dir")
    if plugins_dir and plugins_dir.is_dir():
        for skill_md in _walk_skill_mds(plugins_dir):
            parsed = parse_skill_md(skill_md)
            if parsed:
                names.add(parsed["name"])
    return names


__all__ = [
    "PROJECT_SKILLS_DIR",
    "SKILL_NAME_RE",
    "SOURCE_MARKER",
    "SkillIndex",
    "_agent_builtin_names",
    "_agent_plugin_names",
    "build_skill_md",
    "get_cached_index",
    "get_cached_skills",
    "invalidate_skills_cache",
    "is_link",
    "normalized_source",
    "parse_skill_md",
    "publication_kind",
    "scan_all_skills",
]
