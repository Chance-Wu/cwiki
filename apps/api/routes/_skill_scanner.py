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
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from packages.domain.config import skills_config

PROJECT_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
SOURCE_MARKER = ".cwiki-source.json"
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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
        """单趟扫描：项目 → Agent skills_dir → Agent plugins_dir。"""
        main_skills: dict[str, dict[str, Any]] = {}
        unrelated_skills: list[dict[str, Any]] = []
        plugin_pairs: set[tuple[str, str]] = set()
        avail: dict[str, set[str]] = {a: set() for a in skills_config.agents}
        unrelated_agents: dict[str, set[str]] = {}
        unrelated_pairs: set[tuple[str, str]] = set()

        # 解析缓存：Path → 解析结果（避免重复读盘与重复解析）
        _parsed_cache: dict[Path, dict[str, Any] | None] = {}

        def _cached_parse(p: Path) -> dict[str, Any] | None:
            if p not in _parsed_cache:
                _parsed_cache[p] = parse_skill_md(p)
            return _parsed_cache[p]

        # publication_kind 缓存：(path, source) → 判定结果
        _pub_cache: dict[tuple[Path, Path], str | None] = {}

        def _cached_pub_kind(path: Path, source: Path) -> str | None:
            key = (path, source)
            if key not in _pub_cache:
                _pub_cache[key] = publication_kind(path, source)
            return _pub_cache[key]

        # 阶段 1：项目 skills
        if PROJECT_SKILLS_DIR.is_dir():
            for entry in PROJECT_SKILLS_DIR.iterdir():
                if entry.name.startswith("."):
                    continue
                if not SKILL_NAME_RE.fullmatch(entry.name):
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                parsed = _cached_parse(skill_md)
                if not parsed:
                    continue
                s: dict[str, Any] = {
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
                main_skills[s["name"]] = s

        # 阶段 2：预扫描各 Agent 目录（每个目录只读一次，解析走缓存）
        agent_skills_map: dict[str, dict[str, Path]] = {}
        agent_plugins_map: dict[str, dict[str, Path]] = {}

        for agent_name, config in skills_config.agents.items():
            skills_dir = config["skills_dir"]
            if skills_dir.is_dir():
                smap: dict[str, Path] = {}
                for e in skills_dir.iterdir():
                    if not e.name.startswith(".") and (e / "SKILL.md").is_file():
                        smap[e.name] = e
                agent_skills_map[agent_name] = smap

            plugins_dir = config.get("plugins_dir")
            if plugins_dir and plugins_dir.is_dir():
                pmap: dict[str, Path] = {}
                for skill_md in _walk_skill_mds(plugins_dir):
                    parsed = _cached_parse(skill_md)
                    if parsed and parsed["name"] not in pmap:
                        pmap[parsed["name"]] = skill_md
                agent_plugins_map[agent_name] = pmap

        # 阶段 3：Agent 内置 skills（复用解析缓存）
        for agent_name in skills_config.agents:
            for name, entry_dir in agent_skills_map.get(agent_name, {}).items():
                skill_md = entry_dir / "SKILL.md"
                parsed = _cached_parse(skill_md)
                if not parsed:
                    continue

                avail.setdefault(name, set()).add(agent_name)
                existing = main_skills.get(name)

                if existing is not None:
                    if existing["source"] == "project":
                        if not _cached_pub_kind(entry_dir, PROJECT_SKILLS_DIR / name):
                            s = _make_entry(
                                parsed,
                                source=agent_name,
                                agents=[agent_name],
                                builtin=True,
                                editable=False,
                                provided_by=[agent_name],
                                path=skill_md,
                            )
                            unrelated_skills.append(s)
                            unrelated_agents.setdefault(name, set()).add(agent_name)
                            unrelated_pairs.add((agent_name, name))
                            continue
                        if agent_name not in existing["provided_by"]:
                            existing["provided_by"].append(agent_name)
                    elif agent_name not in existing["agents"]:
                        existing["agents"].append(agent_name)
                        if agent_name not in existing.get("provided_by", []):
                            existing.setdefault("provided_by", []).append(agent_name)
                else:
                    s = _make_entry(
                        parsed,
                        source=agent_name,
                        agents=[agent_name],
                        builtin=True,
                        editable=False,
                        provided_by=[agent_name],
                        path=skill_md,
                    )
                    main_skills[name] = s

        # 阶段 4：插件 skills（复用解析缓存）
        seen_plugin_unrelated: set[str] = set()
        for agent_name in skills_config.agents:
            for name, skill_md_path in agent_plugins_map.get(agent_name, {}).items():
                parsed = _cached_parse(skill_md_path)
                if not parsed:
                    continue

                plugin_pairs.add((agent_name, name))
                avail.setdefault(name, set()).add(agent_name)
                existing = main_skills.get(name)

                if existing is not None:
                    if existing["source"] == "project":
                        if not _cached_pub_kind(
                            Path(skill_md_path).parent, PROJECT_SKILLS_DIR / name
                        ):
                            if name not in seen_plugin_unrelated:
                                seen_plugin_unrelated.add(name)
                                s = _make_entry(
                                    parsed,
                                    source="plugin",
                                    agents=[agent_name],
                                    builtin=True,
                                    editable=False,
                                    provided_by=[agent_name],
                                    path=skill_md_path,
                                )
                                unrelated_skills.append(s)
                                unrelated_agents.setdefault(name, set()).add(agent_name)
                                unrelated_pairs.add((agent_name, name))
                            else:
                                unrelated_agents.setdefault(name, set()).add(agent_name)
                                unrelated_pairs.add((agent_name, name))
                            continue
                        if agent_name not in existing["provided_by"]:
                            existing["provided_by"].append(agent_name)
                    elif agent_name not in existing["agents"]:
                        existing["agents"].append(agent_name)
                        if agent_name not in existing.get("provided_by", []):
                            existing.setdefault("provided_by", []).append(agent_name)
                else:
                    s = _make_entry(
                        parsed,
                        source="plugin",
                        agents=[agent_name],
                        builtin=True,
                        editable=False,
                        provided_by=[agent_name],
                        path=skill_md_path,
                    )
                    main_skills[name] = s

        # 阶段 5：标注发布/可用关系（复用 publication_kind 缓存）
        for s in list(main_skills.values()) + unrelated_skills:
            for a in s.get("agents", []):
                avail.setdefault(s["name"], set()).add(a)

        for s in list(main_skills.values()) + unrelated_skills:
            name = s["name"]
            if s.get("source") == "project":
                pub_agents: list[str] = []
                source = PROJECT_SKILLS_DIR / name
                for agent_name, config in skills_config.agents.items():
                    if _cached_pub_kind(config["skills_dir"] / name, source):
                        pub_agents.append(agent_name)
                s["agents"] = pub_agents
                for a in pub_agents:
                    avail.setdefault(name, set()).add(a)

            s["publishable_to"] = sorted(
                a for a in skills_config.agents if (a, name) not in plugin_pairs
            )

            uref_agents = unrelated_agents.get(name, set())
            uref_pair = unrelated_pairs

            if s.get("source") not in ("project",) and name in unrelated_agents:
                s["available_to"] = sorted(s.get("agents", []))
            else:
                s["available_to"] = sorted(
                    a
                    for a in avail.get(name, set())
                    if a not in uref_agents and (a, name) not in uref_pair
                )

        return cls(
            skills=list(main_skills.values()) + unrelated_skills,
            plugin_pairs=plugin_pairs,
            unrelated_agents=unrelated_agents,
            unrelated_pairs=unrelated_pairs,
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
