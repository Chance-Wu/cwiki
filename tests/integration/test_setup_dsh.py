"""DeepSeek Harness（dsh）接入写入测试。

dsh 只经 profile 的 cordis.patch.yml + @deepseek-ai/dsh-mcp-client 连外部
MCP；本测试锁住三件实测得来的契约：写入位置、`- insert:` 包裹、transport 字段。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import setup_dsh as sd


def _fake_profile(home: Path, name: str = "web", patch: str | None = None) -> Path:
    profile = home / "profiles" / name
    profile.mkdir(parents=True)
    (profile / "package.json").write_text('{"name": "dsh-profile-web"}', encoding="utf-8")
    if patch is not None:
        (profile / "cordis.patch.yml").write_text(patch, encoding="utf-8")
    return profile


def test_workspace_for_rejects_derived_junk_names():
    assert sd.workspace_for(Path("/x/cwiki")) == "cwiki"
    assert sd.workspace_for(Path("/x/my.proj-2")) == "my.proj-2"
    assert sd.workspace_for(Path("/x/--Users-chenyang--")) is None  # 宿主路径编码形态
    assert sd.workspace_for(Path("/x/1a2b3c4d")) is None  # 8 位哈希名
    # 清洗后为空/非法的名字一律拒绝，绝不落到垃圾工作区
    assert sd.workspace_for(Path("/x/纯中文项目")) is None
    assert sd.workspace_for(Path("/x/-")) is None


def test_resolve_profile_prefers_env_then_web(tmp_path, monkeypatch):
    home = tmp_path / "dsh"
    _fake_profile(home, "web")
    _fake_profile(home, "tui")
    monkeypatch.delenv("DSH_PROFILE", raising=False)
    name, path = sd.resolve_profile(home, None)
    assert name == "web" and path.name == "web"

    monkeypatch.setenv("DSH_PROFILE", "tui")
    assert sd.resolve_profile(home, None)[0] == "tui"
    assert sd.resolve_profile(home, "web")[0] == "web"


def test_resolve_profile_errors_without_profiles(tmp_path):
    with pytest.raises(SystemExit):
        sd.resolve_profile(tmp_path / "dsh", None)


def test_patch_writes_insert_wrapped_stdio_entry_and_is_idempotent(tmp_path):
    home = tmp_path / "dsh"
    profile = _fake_profile(
        home, "web", patch="- id: ui-theme\n  name: '@x/y'\n  config:\n    fontSize: 15\n"
    )
    project = tmp_path / "proj-a"
    project.mkdir()

    block = sd.build_block("proj-a", project)
    patch_file = profile / "cordis.patch.yml"
    sd.patch_cordis(patch_file, block, dry_run=False)
    sd.patch_cordis(patch_file, block, dry_run=False)  # 幂等

    text = patch_file.read_text(encoding="utf-8")
    assert text.count(sd.BEGIN) == 1 and text.count(sd.END) == 1
    # 用户已有行保留
    assert "fontSize: 15" in text
    assert text.count("- insert:") == 1

    loaded = yaml.safe_load(text)
    rows = [r for item in loaded if isinstance(item, dict) for r in (item.get("insert") or [])]
    entry = next(r for r in rows if r.get("id") == sd.ENTRY_ID)
    assert entry["name"] == sd.PLUGIN_NAME
    cfg = entry["config"]
    assert cfg["transport"] == "stdio"  # 不是 Claude/Codex 的 type
    assert "type" not in cfg
    assert cfg["serverName"] == "cwiki"
    assert cfg["cwd"] == str(sd.ROOT)
    assert cfg["args"] == ["-m", "adapters.mcp"]
    assert cfg["env"]["CWIKI_HOST"] == "dsh"
    assert cfg["env"]["CWIKI_WORKSPACE"] == "proj-a"
    assert cfg["env"]["CWIKI_WORKSPACE_DIR"] == str(project)
    assert cfg["env"]["PYTHONPATH"] == str(sd.ROOT)


def test_patch_replaces_block_when_project_changes(tmp_path):
    home = tmp_path / "dsh"
    profile = _fake_profile(home, "web", patch="- id: a\n")
    patch_file = profile / "cordis.patch.yml"
    p1, p2 = tmp_path / "one", tmp_path / "two"
    p1.mkdir()
    p2.mkdir()
    sd.patch_cordis(patch_file, sd.build_block("one", p1), dry_run=False)
    sd.patch_cordis(patch_file, sd.build_block("two", p2), dry_run=False)

    text = patch_file.read_text(encoding="utf-8")
    assert text.count("- insert:") == 1
    assert 'CWIKI_WORKSPACE: "two"' in text
    assert "one" not in text
    loaded = yaml.safe_load(text)
    assert loaded[0] == {"id": "a"}  # 原有行顺序不变


def test_patch_aborts_on_broken_markers(tmp_path):
    home = tmp_path / "dsh"
    profile = _fake_profile(home, "web", patch="# cwiki:begin\nx\n# cwiki:begin\n")
    with pytest.raises(SystemExit, match="不配对"):
        sd.patch_cordis(profile / "cordis.patch.yml", sd.build_block("p", tmp_path), dry_run=False)


def test_assert_patch_valid_rejects_bare_entry(tmp_path):
    # 顶层裸条目（缺 insert 包裹）必须被自检拦下
    bad = f"{sd.BEGIN}\n- id: {sd.ENTRY_ID}\n  name: '@x/y'\n{sd.END}\n"
    with pytest.raises(SystemExit, match="insert"):
        sd._assert_patch_valid(bad, tmp_path / "cordis.patch.yml")


def test_install_skill_targets_dsh_discovered_path(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    target = sd.install_skill(project, dry_run=False)
    assert target == project / ".dsh" / "skills" / "cwiki-save"
    assert (target / "SKILL.md").exists()
    # 幂等：重复安装不报错、不套娃
    sd.install_skill(project, dry_run=False)
    assert (sd.install_skill(project, dry_run=False) / "SKILL.md").exists()


def test_dsh_home_defaults_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "custom-dsh"))
    assert sd.dsh_home() == (tmp_path / "custom-dsh").resolve()
    assert sd.dsh_home(tmp_path / "explicit") == (tmp_path / "explicit").resolve()
