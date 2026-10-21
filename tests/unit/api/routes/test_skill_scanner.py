"""SkillIndex 构建逻辑的单元测试。

覆盖 SkillIndex.build() 的 5 个阶段：
1. 扫描项目 skills
2. 预扫描各 Agent 目录
3. 处理 Agent 内置 skills
4. 处理插件 skills
5. 标注发布/可用关系
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from apps.api.routes._skill_scanner import (
    SkillIndex,
    _walk_skill_mds,
    parse_skill_md,
    publication_kind,
)
from packages.domain.config import skills_config


@pytest.fixture
def skill_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """创建隔离的 skill 目录结构。"""
    project = tmp_path / "project" / "skills"
    qoder_skills = tmp_path / "agents" / "qoder" / "skills"
    qoder_plugins = tmp_path / "agents" / "qoder" / "plugins"
    codex_skills = tmp_path / "agents" / "codex" / "skills"
    codex_plugins = tmp_path / "agents" / "codex" / "plugins"

    for path in [project, qoder_skills, qoder_plugins, codex_skills, codex_plugins]:
        path.mkdir(parents=True)

    monkeypatch.setattr("apps.api.routes._skill_scanner.PROJECT_SKILLS_DIR", project)
    monkeypatch.setattr(
        skills_config,
        "agents",
        {
            "qoder": {"skills_dir": qoder_skills, "plugins_dir": qoder_plugins},
            "codex": {"skills_dir": codex_skills, "plugins_dir": codex_plugins},
        },
    )

    return {
        "project": project,
        "qoder_skills": qoder_skills,
        "qoder_plugins": qoder_plugins,
        "codex_skills": codex_skills,
        "codex_plugins": codex_plugins,
    }


def _write_skill(directory: Path, name: str, description: str = "test") -> Path:
    """写入一个 SKILL.md 文件。"""
    directory.mkdir(parents=True, exist_ok=True)
    metadata = yaml.safe_dump({"name": name, "description": description})
    skill_md = directory / "SKILL.md"
    skill_md.write_text(f"---\n{metadata}---\n\nBody content\n", encoding="utf-8")
    return skill_md


def _mark_source(target: Path, source: Path) -> None:
    """写入 .cwiki-source.json 标记文件。"""
    marker = target / ".cwiki-source.json"
    marker.write_text(
        json.dumps({"source": os.path.normcase(str(source.resolve()))}),
        encoding="utf-8",
    )


class TestParseSkillMd:
    """parse_skill_md 函数测试。"""

    def test_valid_skill_md(self, tmp_path: Path) -> None:
        """有效的 SKILL.md 应正确解析。"""
        skill_md = _write_skill(tmp_path, "test-skill", "A test skill")
        result = parse_skill_md(skill_md)
        assert result is not None
        assert result["name"] == "test-skill"
        assert result["description"] == "A test skill"
        assert "Body content" in result["body"]

    def test_missing_file(self, tmp_path: Path) -> None:
        """不存在的文件应返回 None。"""
        result = parse_skill_md(tmp_path / "missing" / "SKILL.md")
        assert result is None

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """无效的 YAML 应返回 None。"""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\ninvalid: yaml: content\n---\n\nBody\n", encoding="utf-8")
        result = parse_skill_md(skill_md)
        assert result is None

    def test_missing_name(self, tmp_path: Path) -> None:
        """缺少 name 字段应返回 None。"""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\ndescription: no name\n---\n\nBody\n", encoding="utf-8")
        result = parse_skill_md(skill_md)
        assert result is None

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        """没有 frontmatter 应返回 None。"""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("Just body, no frontmatter\n", encoding="utf-8")
        result = parse_skill_md(skill_md)
        assert result is None


class TestWalkSkillMds:
    """_walk_skill_mds 函数测试。"""

    def test_finds_skill_mds(self, tmp_path: Path) -> None:
        """应找到所有 SKILL.md 文件。"""
        _write_skill(tmp_path / "skill1", "skill1")
        _write_skill(tmp_path / "nested" / "skill2", "skill2")
        _write_skill(tmp_path / "deep" / "nested" / "skill3", "skill3")

        results = _walk_skill_mds(tmp_path)
        names = {r.parent.name for r in results}
        assert names == {"skill1", "skill2", "skill3"}

    def test_skips_excluded_dirs(self, tmp_path: Path) -> None:
        """应跳过 node_modules、.git 等目录。"""
        _write_skill(tmp_path / "skill1", "skill1")
        _write_skill(tmp_path / "node_modules" / "skill2", "skill2")
        _write_skill(tmp_path / ".git" / "skill3", "skill3")
        _write_skill(tmp_path / "__pycache__" / "skill4", "skill4")

        results = _walk_skill_mds(tmp_path)
        names = {r.parent.name for r in results}
        assert names == {"skill1"}


class TestPublicationKind:
    """publication_kind 函数测试。"""

    def test_symlink_to_source(self, tmp_path: Path) -> None:
        """指向源的符号链接应返回 'symlink'。"""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        try:
            target.symlink_to(source)
        except OSError:
            pytest.skip("Cannot create symlinks on this system")

        result = publication_kind(target, source)
        assert result == "symlink"

    def test_copy_with_marker(self, tmp_path: Path) -> None:
        """带正确标记的副本应返回 'copy'。"""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        _mark_source(target, source)

        result = publication_kind(target, source)
        assert result == "copy"

    def test_copy_with_wrong_marker(self, tmp_path: Path) -> None:
        """带错误标记的副本应返回 None。"""
        source = tmp_path / "source"
        other = tmp_path / "other"
        target = tmp_path / "target"
        source.mkdir()
        other.mkdir()
        target.mkdir()
        _mark_source(target, other)  # 标记指向 other 而非 source

        result = publication_kind(target, source)
        assert result is None

    def test_unmarked_directory(self, tmp_path: Path) -> None:
        """无标记的目录应返回 None。"""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        result = publication_kind(target, source)
        assert result is None

    def test_nonexistent_target(self, tmp_path: Path) -> None:
        """不存在的目标应返回 None。"""
        source = tmp_path / "source"
        source.mkdir()

        result = publication_kind(tmp_path / "missing", source)
        assert result is None


class TestSkillIndexBuild:
    """SkillIndex.build() 核心逻辑测试。"""

    def test_empty_scan(self, skill_dirs: dict[str, Any]) -> None:
        """空目录应返回空索引。"""
        index = SkillIndex.build()
        assert index.skills == []

    def test_project_skills_only(self, skill_dirs: dict[str, Any]) -> None:
        """只有项目 skills 时应正确扫描。"""
        project = skill_dirs["project"]
        _write_skill(project / "skill1", "skill1", "Project skill 1")
        _write_skill(project / "skill2", "skill2", "Project skill 2")

        index = SkillIndex.build()
        assert len(index.skills) == 2
        names = {s["name"] for s in index.skills}
        assert names == {"skill1", "skill2"}
        for skill in index.skills:
            assert skill["source"] == "project"
            assert skill["editable"] is True

    def test_agent_builtin_skills(self, skill_dirs: dict[str, Any]) -> None:
        """Agent 内置 skills 应正确扫描。"""
        qoder_skills = skill_dirs["qoder_skills"]
        _write_skill(qoder_skills / "builtin1", "builtin1", "Qoder builtin")

        index = SkillIndex.build()
        assert len(index.skills) == 1
        skill = index.skills[0]
        assert skill["name"] == "builtin1"
        assert skill["source"] == "qoder"
        assert skill["builtin"] is True
        assert skill["editable"] is False
        assert "qoder" in skill["agents"]

    def test_plugin_skills(self, skill_dirs: dict[str, Any]) -> None:
        """插件 skills 应正确扫描。"""
        qoder_plugins = skill_dirs["qoder_plugins"]
        _write_skill(qoder_plugins / "plugin1", "plugin1", "Plugin skill")

        index = SkillIndex.build()
        assert len(index.skills) == 1
        skill = index.skills[0]
        assert skill["name"] == "plugin1"
        assert skill["source"] == "plugin"
        assert skill["builtin"] is True

    def test_project_skill_with_agent_copy(
        self, skill_dirs: dict[str, Any]
    ) -> None:
        """项目 skill 带 Agent 副本时应正确关联。"""
        project = skill_dirs["project"]
        qoder_skills = skill_dirs["qoder_skills"]
        source = project / "demo"
        target = qoder_skills / "demo"

        _write_skill(source, "demo", "Project skill")
        target.mkdir()
        _write_skill(target, "demo", "Copy")
        _mark_source(target, source)

        index = SkillIndex.build()
        assert len(index.skills) == 1
        skill = index.skills[0]
        assert skill["name"] == "demo"
        assert skill["source"] == "project"
        assert "qoder" in skill["provided_by"]

    def test_independent_agent_skill(
        self, skill_dirs: dict[str, Any]
    ) -> None:
        """Agent 独立 skill（无项目源）应作为独立条目。"""
        qoder_skills = skill_dirs["qoder_skills"]
        _write_skill(qoder_skills / "independent", "independent", "Independent")

        index = SkillIndex.build()
        assert len(index.skills) == 1
        skill = index.skills[0]
        assert skill["name"] == "independent"
        assert skill["source"] == "qoder"
        assert skill["provided_by"] == ["qoder"]

    def test_publishable_to_calculation(
        self, skill_dirs: dict[str, Any]
    ) -> None:
        """publishable_to 应正确计算。"""
        project = skill_dirs["project"]
        _write_skill(project / "demo", "demo", "Demo")

        index = SkillIndex.build()
        skill = index.skills[0]
        # 默认应可发布到所有 agents
        assert set(skill["publishable_to"]) == {"qoder", "codex"}

    def test_multiple_agents_same_skill(
        self, skill_dirs: dict[str, Any]
    ) -> None:
        """多个 Agent 有同名 skill 时应合并到一个条目。"""
        qoder_skills = skill_dirs["qoder_skills"]
        codex_skills = skill_dirs["codex_skills"]
        _write_skill(qoder_skills / "shared", "shared", "Qoder version")
        _write_skill(codex_skills / "shared", "shared", "Codex version")

        index = SkillIndex.build()
        # 应合并为一个条目
        assert len(index.skills) == 1
        skill = index.skills[0]
        assert skill["name"] == "shared"
        # agents 列表应包含两个 Agent
        assert set(skill["agents"]) == {"qoder", "codex"}

    def test_cache_reuse(self, skill_dirs: dict[str, Any]) -> None:
        """构建时应复用解析缓存（避免重复读盘）。"""
        project = skill_dirs["project"]
        _write_skill(project / "skill1", "skill1")

        # 第一次构建
        index1 = SkillIndex.build()
        # 第二次构建应使用缓存
        index2 = SkillIndex.build()

        assert len(index1.skills) == len(index2.skills) == 1


class TestSkillIndexRelationships:
    """SkillIndex 关系查询测试。"""

    def test_publishable_to_excludes_plugin_pairs(
        self, skill_dirs: dict[str, Any]
    ) -> None:
        """publishable_to 应排除已有插件的 agents。"""
        project = skill_dirs["project"]
        qoder_plugins = skill_dirs["qoder_plugins"]
        _write_skill(project / "demo", "demo", "Project")
        _write_skill(qoder_plugins / "demo", "demo", "Plugin")

        index = SkillIndex.build()
        project_skill = next(s for s in index.skills if s["source"] == "project")
        # qoder 已有插件版本，不应在 publishable_to 中
        assert "qoder" not in project_skill["publishable_to"]
        assert "codex" in project_skill["publishable_to"]

    def test_available_to_calculation(self, skill_dirs: dict[str, Any]) -> None:
        """available_to 应正确计算。"""
        project = skill_dirs["project"]
        qoder_skills = skill_dirs["qoder_skills"]
        source = project / "demo"
        target = qoder_skills / "demo"

        _write_skill(source, "demo", "Project")
        target.mkdir()
        _write_skill(target, "demo", "Copy")
        _mark_source(target, source)

        index = SkillIndex.build()
        skill = index.skills[0]
        assert "qoder" in skill["available_to"]
