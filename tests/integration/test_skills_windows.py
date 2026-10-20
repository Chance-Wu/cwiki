"""隔离的技能发布回归测试，含 Windows 复制回退路径。"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # 本机索引上没有 types-PyYAML
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent
from apps.api.routes import _skill_publisher, _skill_scanner, skills
from packages.domain.config import skills_config

_REAL_SYMLINK_TO = Path.symlink_to


@pytest.fixture(autouse=True)
def skill_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    project = tmp_path / "project" / "skills"
    qoder = tmp_path / "agents" / "qoder"
    codex = tmp_path / "agents" / "codex"
    for path in (project, qoder, codex):
        path.mkdir(parents=True)
    monkeypatch.setattr(skills, "PROJECT_SKILLS_DIR", project)
    monkeypatch.setattr(_skill_scanner, "PROJECT_SKILLS_DIR", project)
    monkeypatch.setattr(_skill_publisher, "PROJECT_SKILLS_DIR", project)
    monkeypatch.setattr(
        skills_config,
        "agents",
        {"qoder": {"skills_dir": qoder}, "codex": {"skills_dir": codex}},
    )
    # 测试间清空内存中的扫描缓存。
    skills._invalidate_skills_cache()
    return project, qoder, codex


@pytest.fixture
def skill_client(skill_paths: tuple[Path, Path, Path]) -> Iterator[TestClient]:
    # 不使用应用 lifespan、数据库、worker 或真实 agent 配置。
    app = FastAPI()
    app.include_router(skills.router)
    app.dependency_overrides[get_current_agent] = lambda: AgentIdentity(
        agent_id="test-agent",
        workspace_id="default",
        scopes={"skills:read", "skills:write"},
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def force_copy(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls = []

    def denied(self: Path, target: Path, target_is_directory: bool = False) -> None:
        assert target_is_directory is True
        assert Path(target).is_absolute()
        calls.append(self)
        raise OSError("Windows symlink privilege is unavailable")

    monkeypatch.setattr(Path, "symlink_to", denied)
    return calls


def _write_skill(directory: Path, name: Any = "demo", body: str = "original") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    metadata = yaml.safe_dump({"name": name, "description": "test skill"})
    (directory / "SKILL.md").write_text(f"---\n{metadata}---\n\n{body}\n", encoding="utf-8")
    return directory


def _mark(target: Path, source: Path) -> None:
    (target / skills.SOURCE_MARKER).write_text(
        json.dumps({"source": os.path.normcase(str(source.resolve()))}), encoding="utf-8"
    )


def _link(target: Path, source: Path, directory: bool = True) -> None:
    try:
        _REAL_SYMLINK_TO(target, source, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"This host cannot create test symlinks: {exc}")


def test_create_edit_and_republish_refresh_copy_and_resources(
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    force_copy: list[Path],
) -> None:
    project, qoder, _ = skill_paths
    response = skill_client.post(
        "/v1/skills",
        json={"name": "demo", "description": "first", "body": "original", "agents": ["qoder"]},
    )
    assert response.status_code == 201
    assert response.json()["agents"] == ["qoder"]
    source, target = project / "demo", qoder / "demo"
    assert force_copy == [target]
    assert not target.is_symlink()
    marker = json.loads((target / skills.SOURCE_MARKER).read_text(encoding="utf-8"))
    assert marker == {"source": os.path.normcase(str(source.resolve()))}
    assert not (source / skills.SOURCE_MARKER).exists()

    assets = source / "assets"
    assets.mkdir()
    (assets / "payload.bin").write_bytes(b"\x00\xfforiginal")
    response = skill_client.patch(
        "/v1/skills/demo", json={"description": "edited", "body": "updated body"}
    )
    assert response.status_code == 200
    assert response.json()["agents"] == ["qoder"]
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert (target / "assets" / "payload.bin").read_bytes() == b"\x00\xfforiginal"

    (assets / "payload.bin").write_bytes(b"changed resource")
    assert skill_client.patch("/v1/skills/demo", json={"body": "second edit"}).status_code == 200
    assert (target / "assets" / "payload.bin").read_bytes() == b"changed resource"

    (assets / "payload.bin").unlink()
    (assets / "nested").mkdir()
    (assets / "nested" / "new.txt").write_text("new resource", encoding="utf-8")
    (target / "obsolete.txt").write_text("stale copy", encoding="utf-8")
    (source / "SKILL.md").write_text(
        "---\nname: demo\ndescription: republished\n---\n\nlatest\n", encoding="utf-8"
    )
    response = skill_client.post("/v1/skills/demo/publish")
    assert response.status_code == 200
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert not (target / "assets" / "payload.bin").exists()
    assert not (target / "obsolete.txt").exists()
    assert (target / "assets" / "nested" / "new.txt").read_text() == "new resource"
    assert skills._get_agents_for_skill("demo") == ["qoder"]
    assert len(force_copy) == 1  # 已有副本走刷新而非重建链接。
    listed = skill_client.get("/v1/skills").json()
    assert len(listed) == 1
    assert listed[0]["source"] == "project"
    assert listed[0]["agents"] == ["qoder"]


@pytest.mark.parametrize(
    "marker_kind", ["missing", "other-source", "invalid-json", "list", "relative"]
)
def test_unowned_copy_conflict_and_scan_preserve_independent_skill(
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    force_copy: list[Path],
    marker_kind: str,
) -> None:
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    target = _write_skill(qoder / "demo", body="independent skill")
    marker = target / skills.SOURCE_MARKER
    if marker_kind == "other-source":
        _mark(target, project / "other")
    elif marker_kind == "invalid-json":
        marker.write_text("{invalid", encoding="utf-8")
    elif marker_kind == "list":
        marker.write_text("[]", encoding="utf-8")
    elif marker_kind == "relative":
        marker.write_text('{"source": "demo"}', encoding="utf-8")
    original = {path.name: path.read_bytes() for path in target.iterdir()}

    response = skill_client.post("/v1/skills/demo/publish")
    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()
    assert skills._get_agents_for_skill("demo") == []
    listed = skill_client.get("/v1/skills").json()
    assert next(s for s in listed if s["source"] == "project")["agents"] == []
    independent = next(s for s in listed if s["source"] == "qoder")
    assert independent["agents"] == ["qoder"]
    assert independent["body"] == "independent skill"

    assert skill_client.patch("/v1/skills/demo", json={"body": "edited"}).status_code == 200
    assert skill_client.post("/v1/skills/demo/unpublish").json()["agents"] == []
    assert skill_client.delete("/v1/skills/demo").status_code == 204
    assert not source.exists()
    assert {path.name: path.read_bytes() for path in target.iterdir()} == original
    assert force_copy == []


def test_creation_conflict_does_not_adopt_existing_agent_copy(
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    force_copy: list[Path],
) -> None:
    project, qoder, _ = skill_paths
    target = _write_skill(qoder / "demo", body="not ours")
    original = (target / "SKILL.md").read_bytes()
    response = skill_client.post(
        "/v1/skills",
        json={"name": "demo", "description": "test", "body": "new", "agents": ["qoder"]},
    )
    assert response.status_code == 409
    assert (target / "SKILL.md").read_bytes() == original
    assert not (target / skills.SOURCE_MARKER).exists()
    assert not (project / "demo").exists()


@pytest.mark.parametrize("operation", ["unpublish", "delete"])
def test_remove_only_managed_copies(
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    force_copy: list[Path],
    operation: str,
) -> None:
    project, qoder, codex = skill_paths
    source = _write_skill(project / "demo")
    independent = _write_skill(codex / "demo", body="independent")
    assert skill_client.post("/v1/skills/demo/publish").status_code == 200
    if operation == "unpublish":
        response = skill_client.post("/v1/skills/demo/unpublish")
        assert response.status_code == 200
        assert response.json()["agents"] == []
        assert source.is_dir()
        assert skill_client.post("/v1/skills/demo/unpublish").status_code == 200
    else:
        assert skill_client.delete("/v1/skills/demo").status_code == 204
        assert not source.exists()
    assert not (qoder / "demo").exists()
    parsed = skills._parse_skill_md(independent / "SKILL.md")
    assert parsed is not None and parsed["body"] == "independent"


def test_new_publication_uses_directory_symlink_when_available(
    tmp_path: Path,
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    probe = tmp_path / "symlink-probe"
    _link(probe, source)
    probe.unlink()
    calls = []

    def create_link(self: Path, target: Path, target_is_directory: bool = False) -> None:
        calls.append((target, target_is_directory))
        _REAL_SYMLINK_TO(self, target, target_is_directory=target_is_directory)

    monkeypatch.setattr(Path, "symlink_to", create_link)
    assert skill_client.post("/v1/skills/demo/publish").status_code == 200
    assert calls == [(source.resolve(), True)]
    assert (qoder / "demo").is_symlink()
    assert not (source / skills.SOURCE_MARKER).exists()


def test_managed_root_symlink_is_recognized_and_only_link_is_removed(
    skill_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    target = qoder / "demo"
    _link(target, Path(os.path.relpath(source, qoder)))
    assert skills._get_agents_for_skill("demo") == ["qoder"]
    assert skill_client.post("/v1/skills/demo/publish").status_code == 200
    assert target.is_symlink()
    assert skill_client.patch("/v1/skills/demo", json={"body": "live edit"}).status_code == 200
    parsed = skills._parse_skill_md(target / "SKILL.md")
    assert parsed is not None and parsed["body"] == "live edit"
    assert len(skill_client.get("/v1/skills").json()) == 1
    assert skill_client.post("/v1/skills/demo/unpublish").status_code == 200
    assert not target.is_symlink()
    assert source.is_dir()
    parsed = skills._parse_skill_md(source / "SKILL.md")
    assert parsed is not None and parsed["body"] == "live edit"


@pytest.mark.parametrize("kind", ["symlink", "dangling-symlink", "file"])
def test_unrelated_root_target_is_never_overwritten_or_removed(
    tmp_path: Path,
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    kind: str,
) -> None:
    project, qoder, _ = skill_paths
    _write_skill(project / "demo")
    external = tmp_path / "independent"
    target = qoder / "demo"
    if kind == "file":
        target.write_text("unrelated file", encoding="utf-8")
    else:
        if kind == "symlink":
            _write_skill(external, body="external")
        _link(target, external)
    response = skill_client.post("/v1/skills/demo/publish")
    assert response.status_code == 409
    assert skills._get_agents_for_skill("demo") == []
    if kind == "symlink":
        listed = skill_client.get("/v1/skills").json()
        assert next(s for s in listed if s["source"] == "project")["agents"] == []
        assert next(s for s in listed if s["source"] == "qoder")["body"] == "external"
    assert skill_client.post("/v1/skills/demo/unpublish").status_code == 200
    assert skill_client.delete("/v1/skills/demo").status_code == 204
    if kind == "file":
        assert target.read_text() == "unrelated file"
    else:
        assert target.is_symlink()
        if kind == "symlink":
            parsed = skills._parse_skill_md(external / "SKILL.md")
            assert parsed is not None and parsed["body"] == "external"


@pytest.mark.parametrize("operation", ["publish", "update", "unpublish"])
@pytest.mark.parametrize("kind", ["file", "directory", "dangling"])
def test_managed_copy_with_nested_symlink_conflicts_without_touching_files(
    tmp_path: Path,
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    force_copy: list[Path],
    operation: str,
    kind: str,
) -> None:
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    assert skill_client.post("/v1/skills/demo/publish").status_code == 200
    target = qoder / "demo"
    external = _write_skill(tmp_path / "external", body="external")
    if kind == "file":
        link = target / "SKILL.md"
        link.unlink()
        _link(link, external / "SKILL.md", directory=False)
    else:
        link = target / "resources"
        _link(link, external if kind == "directory" else tmp_path / "missing")
    source_before = (source / "SKILL.md").read_bytes()
    external_before = (external / "SKILL.md").read_bytes()
    if operation == "update":
        response = skill_client.patch("/v1/skills/demo", json={"body": "must not write"})
    else:
        response = skill_client.post(f"/v1/skills/demo/{operation}")
    assert response.status_code == 409
    assert link.is_symlink()
    assert (source / "SKILL.md").read_bytes() == source_before
    assert (external / "SKILL.md").read_bytes() == external_before
    assert (target / skills.SOURCE_MARKER).is_file()


def test_failed_symlink_does_not_overwrite_target_created_during_attempt(
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, qoder, _ = skill_paths
    _write_skill(project / "demo")

    def target_appeared(self: Path, target: Path, target_is_directory: bool = False) -> None:
        _write_skill(self, body="appeared during publication")
        raise OSError("Target already exists")

    monkeypatch.setattr(Path, "symlink_to", target_appeared)
    assert skill_client.post("/v1/skills/demo/publish").status_code == 409
    parsed = skills._parse_skill_md(qoder / "demo" / "SKILL.md")
    assert parsed is not None and parsed["body"] == "appeared during publication"
    assert not (qoder / "demo" / skills.SOURCE_MARKER).exists()


def test_symlink_marker_cannot_claim_ownership(
    tmp_path: Path,
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
) -> None:
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    target = _write_skill(qoder / "demo", body="unowned")
    external = tmp_path / "marker.json"
    external.write_text(json.dumps({"source": str(source.resolve())}), encoding="utf-8")
    marker = target / skills.SOURCE_MARKER
    _link(marker, external, directory=False)
    assert skills._get_agents_for_skill("demo") == []
    assert skill_client.post("/v1/skills/demo/publish").status_code == 409
    assert skill_client.post("/v1/skills/demo/unpublish").status_code == 200
    assert marker.is_symlink()
    parsed = skills._parse_skill_md(target / "SKILL.md")
    assert parsed is not None and parsed["body"] == "unowned"


@pytest.mark.parametrize("location", ["root", "nested", "parent"])
def test_junction_targets_are_not_followed(
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    target = _write_skill(qoder / "demo")
    _mark(target, source)
    junction = {"root": target, "nested": target / "assets", "parent": qoder}[location]
    junction.mkdir(exist_ok=True)
    original_is_junction = Path.is_junction
    monkeypatch.setattr(
        Path, "is_junction", lambda self: self == junction or original_is_junction(self)
    )
    response = skill_client.post("/v1/skills/demo/publish")
    assert response.status_code == 409
    response = skill_client.post("/v1/skills/demo/unpublish")
    assert response.status_code == (409 if location == "nested" else 200)
    if location == "nested":
        response = skill_client.patch("/v1/skills/demo", json={"body": "must not write"})
        assert response.status_code == 409
    else:
        assert skills._get_agents_for_skill("demo") == []
    assert target.is_dir()
    parsed = skills._parse_skill_md(source / "SKILL.md")
    assert parsed is not None and parsed["body"] == "original"


def test_publication_kind_returns_none_on_marker_permission_error(
    tmp_path: Path,
    skill_paths: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """标记文件读取出现 PermissionError 时由 _publication_kind 的 OSError 处理捕获并返回 None。"""
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    target = qoder / "demo"
    target.mkdir()
    (target / "SKILL.md").write_text("placeholder", encoding="utf-8")
    _mark(target, source)

    def denied(self: Path, *args: Any, **kwargs: Any) -> str:
        raise PermissionError("held by filter driver")

    monkeypatch.setattr(Path, "read_text", denied)
    assert skills._publication_kind(target, source) is None


DANGEROUS_NAMES = [
    "../escape",
    "..",
    "/absolute",
    "folder/name",
    "folder\\name",
    "C:\\escape",
    "con",
    "nul",
    "aux",
    "prn",
    "com1",
    "lpt9",
    "CON.txt",
    "trailing.",
    "trailing ",
    "safe\n",
    "bad\x00name",
    "a" * 256,
    "MixedCase",
    "under_score",
    "",
    123,
    True,
    None,
    ["demo"],
    {"name": "demo"},
]

# dsh（@deepseek-ai/dsh-skill 的 SKILL_NAME）不接受前导/连续/尾随连字符，
# 这类名字会被 dsh 以 invalid skill name 静默忽略，因此创建时必须拒绝。
DSH_INVALID_NAMES = ["-leading", "trailing-", "double--hyphen", "UPPER", "under_score", "-", "--"]


@pytest.fixture
def dsh_paths(
    skill_paths: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    """在既有 qoder/codex 夹具之上追加 dsh 目标目录。"""
    project, qoder, codex = skill_paths
    dsh = tmp_path / "agents" / "dsh"
    dsh.mkdir(parents=True)
    monkeypatch.setattr(
        skills_config,
        "agents",
        {
            "qoder": {"skills_dir": qoder},
            "codex": {"skills_dir": codex},
            "dsh": {"skills_dir": dsh},
        },
    )
    skills._invalidate_skills_cache()
    return project, qoder, dsh


def test_agents_endpoint_includes_dsh(
    dsh_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    """配置了 dsh 后，agents 端点必须把它列为一等发布目标。"""
    agents = skill_client.get("/v1/skills/agents").json()
    assert "dsh" in agents
    assert set(agents) == {"qoder", "codex", "dsh"}


def test_publish_and_unpublish_roundtrip_to_dsh(
    dsh_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    """发布到 dsh：symlink 落到 ~/.dsh/skills/<name>，dsh 会解引用跟随该链接。"""
    project, _, dsh = dsh_paths
    source = _write_skill(project / "demo")

    response = skill_client.post("/v1/skills/demo/publish", json={"agents": ["dsh"]})
    assert response.status_code == 200
    assert response.json()["agents"] == ["dsh"]

    target = dsh / "demo"
    assert target.is_symlink()
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert skills._get_agents_for_skill("demo") == ["dsh"]

    listed = skill_client.get("/v1/skills").json()
    entry = next(s for s in listed if s["source"] == "project")
    assert entry["agents"] == ["dsh"]
    assert entry["publishable_to"] == ["codex", "dsh", "qoder"]
    assert entry["available_to"] == ["dsh"]
    assert not (source / skills.SOURCE_MARKER).exists()

    response = skill_client.post("/v1/skills/demo/unpublish", json={"agents": ["dsh"]})
    assert response.status_code == 200
    assert response.json()["agents"] == []
    assert not target.exists()
    assert source.is_dir()


def test_dsh_copy_fallback_when_symlink_unavailable(
    dsh_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    force_copy: list[Path],
) -> None:
    """Windows/无 symlink 权限时回退带标记的副本，dsh 目标同样可用。"""
    project, _, dsh = dsh_paths
    source = _write_skill(project / "demo")

    assert skill_client.post("/v1/skills/demo/publish", json={"agents": ["dsh"]}).status_code == 200
    target = dsh / "demo"
    assert not target.is_symlink()
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert (target / skills.SOURCE_MARKER).is_file()
    assert force_copy == [dsh / "demo"]

    # 源变更后重新发布应刷新副本而非重建。
    _write_skill(source, body="updated body")
    assert skill_client.post("/v1/skills/demo/publish", json={"agents": ["dsh"]}).status_code == 200
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert len(force_copy) == 1

    assert skill_client.delete("/v1/skills/demo").status_code == 204
    assert not target.exists()
    assert not source.exists()


def test_dsh_publish_creates_missing_skills_root(
    dsh_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    """~/.dsh/skills 尚未创建时，发布应自动建出该根目录。"""
    project, _, dsh = dsh_paths
    dsh.rmdir()
    assert not dsh.exists()
    _write_skill(project / "demo")

    assert skill_client.post("/v1/skills/demo/publish", json={"agents": ["dsh"]}).status_code == 200
    assert dsh.is_dir()
    assert (dsh / "demo" / "SKILL.md").is_file()


def test_dsh_unmanaged_target_conflict_is_preserved(
    dsh_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    """dsh 目录下已有的非托管技能不得被覆盖或删除。"""
    project, _, dsh = dsh_paths
    _write_skill(project / "demo")
    target = _write_skill(dsh / "demo", body="independent dsh skill")
    original = (target / "SKILL.md").read_bytes()

    response = skill_client.post("/v1/skills/demo/publish", json={"agents": ["dsh"]})
    assert response.status_code == 409
    assert (target / "SKILL.md").read_bytes() == original
    assert skills._get_agents_for_skill("demo") == []

    # dsh 侧独立技能仍以 builtin 形式出现。
    listed = skill_client.get("/v1/skills").json()
    independent = next(s for s in listed if s["source"] == "dsh")
    assert independent["body"] == "independent dsh skill"
    assert independent["editable"] is False

    assert (
        skill_client.post("/v1/skills/demo/unpublish", json={"agents": ["dsh"]}).status_code == 200
    )
    assert (target / "SKILL.md").read_bytes() == original


def test_dsh_only_publish_does_not_touch_other_agents(
    dsh_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    """显式只发布 dsh 时，不得顺带发布到 qoder/codex。"""
    project, qoder, dsh = dsh_paths
    _write_skill(project / "demo")

    assert skill_client.post("/v1/skills/demo/publish", json={"agents": ["dsh"]}).status_code == 200
    assert (dsh / "demo").exists()
    assert not (qoder / "demo").exists()
    assert skills._get_agents_for_skill("demo") == ["dsh"]


@pytest.mark.parametrize("name", DSH_INVALID_NAMES)
def test_create_rejects_names_dsh_cannot_load(
    dsh_paths: tuple[Path, Path, Path], skill_client: TestClient, name: str
) -> None:
    """前导/连续/尾随连字符与非 kebab 名字必须在创建阶段被拒绝。"""
    project, _, dsh = dsh_paths
    response = skill_client.post(
        "/v1/skills",
        json={"name": name, "description": "test", "body": "test", "agents": ["dsh"]},
    )
    assert response.status_code == 422
    for directory in (project, dsh):
        assert list(directory.iterdir()) == []


def test_project_scan_ignores_non_kebab_directories(
    dsh_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    """项目 skills 下不合 dsh 语法的目录名不得进入索引。"""
    project, _, _ = dsh_paths
    _write_skill(project / "bad--name", name="bad--name")
    _write_skill(project / "trailing-", name="trailing-")
    _write_skill(project / "good-name", name="good-name")

    names = sorted(s["name"] for s in skill_client.get("/v1/skills").json())
    assert names == ["good-name"]


@pytest.mark.parametrize("name", DANGEROUS_NAMES)
def test_create_rejects_unsafe_names_without_writing(
    skill_paths: tuple[Path, Path, Path], skill_client: TestClient, name: Any
) -> None:
    project, qoder, codex = skill_paths
    response = skill_client.post(
        "/v1/skills",
        json={"name": name, "description": "test", "body": "test", "agents": ["qoder"]},
    )
    assert response.status_code == 422
    for directory in (project, qoder, codex):
        assert list(directory.iterdir()) == []


@pytest.mark.parametrize("name", DANGEROUS_NAMES)
def test_import_rejects_unsafe_parsed_names_without_writing(
    tmp_path: Path,
    skill_paths: tuple[Path, Path, Path],
    skill_client: TestClient,
    name: Any,
) -> None:
    project, qoder, codex = skill_paths
    source = _write_skill(tmp_path / "import", name=name)
    response = skill_client.post("/v1/skills/import", json={"source_path": str(source)})
    assert response.status_code == 400
    for directory in (project, qoder, codex):
        assert list(directory.iterdir()) == []


def test_import_valid_name_and_resources(
    tmp_path: Path, skill_paths: tuple[Path, Path, Path], skill_client: TestClient
) -> None:
    project, _, _ = skill_paths
    source = _write_skill(tmp_path / "import", name="portable-skill-1")
    (source / "resource.txt").write_text("portable resource", encoding="utf-8")
    response = skill_client.post(
        "/v1/skills/import", json={"source_path": str(source / "SKILL.md")}
    )
    assert response.status_code == 201
    assert (project / "portable-skill-1" / "resource.txt").read_text() == "portable resource"
    assert response.json()["agents"] == []


@pytest.mark.parametrize("name", ["../outside", "..\\outside", "/absolute", "con", "safe\n"])
@pytest.mark.parametrize(
    "operation", ["update_skill", "delete_skill", "publish_skill", "unpublish_skill"]
)
async def test_path_route_names_validated_before_filesystem_access(
    skill_paths: tuple[Path, Path, Path], operation: str, name: str
) -> None:
    kwargs = (
        {"body": skills.SkillUpdate(body="must not write")} if operation == "update_skill" else {}
    )
    with pytest.raises(HTTPException) as error:
        await getattr(skills, operation)(name, **kwargs)
    assert error.value.status_code == 422
    for directory in skill_paths:
        assert list(directory.iterdir()) == []


@pytest.mark.parametrize("name", ["con", "safe%0A", "..%5Coutside"])
def test_http_path_name_errors_are_422(skill_client: TestClient, name: str) -> None:
    assert skill_client.get(f"/v1/skills/{name}").status_code == 404
    assert skill_client.patch(f"/v1/skills/{name}", json={"body": "no"}).status_code == 422
    assert skill_client.delete(f"/v1/skills/{name}").status_code == 422
    assert skill_client.post(f"/v1/skills/{name}/publish").status_code == 422
    assert skill_client.post(f"/v1/skills/{name}/unpublish").status_code == 422


@pytest.mark.parametrize("name", ["Builtin_Skill", "plugin:skill"])
def test_builtin_detail_does_not_require_project_naming_rules(
    skill_paths: tuple[Path, Path, Path], skill_client: TestClient, name: str
) -> None:
    _, qoder, _ = skill_paths
    _write_skill(qoder / "builtin", name=name, body="builtin body")
    response = skill_client.get(f"/v1/skills/{name}")
    assert response.status_code == 200
    assert response.json()["body"] == "builtin body"
    assert response.json()["editable"] is False


@pytest.mark.parametrize("failure", ["copy", "backup", "install", "rollback"])
def test_failed_refresh_preserves_previous_copy(
    skill_paths: tuple[Path, Path, Path],
    force_copy: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    project, qoder, _ = skill_paths
    source = _write_skill(project / "demo")
    skills._publish_to_agent("demo", "qoder")
    target = qoder / "demo"
    original = (target / "SKILL.md").read_bytes()
    _write_skill(source, body="new content")
    real_rename = Path.rename

    def rename(path: Path, destination: Path) -> Path:
        if (
            (failure == "backup" and path == target)
            or (failure in {"install", "rollback"} and path.name == "copy")
            or (failure == "rollback" and path.name == "previous")
        ):
            raise PermissionError("File in use")
        return real_rename(path, destination)

    def fail_copy(*args: Any, **kwargs: Any) -> None:
        raise OSError("Cannot copy source")

    monkeypatch.setattr(Path, "rename", rename)
    if failure == "copy":
        monkeypatch.setattr(shutil, "copytree", fail_copy)
    with pytest.raises(OSError):
        skills._publish_to_agent("demo", "qoder")
    if failure == "rollback":
        backups = list(qoder.glob(".cwiki-skill-*/previous"))
        assert len(backups) == 1
        assert (backups[0] / "SKILL.md").read_bytes() == original
    else:
        assert (target / "SKILL.md").read_bytes() == original
        assert skills._publication_kind(target, source) == "copy"
        assert not list(qoder.glob(".cwiki-skill-*"))
