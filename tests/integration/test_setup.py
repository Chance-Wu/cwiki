import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts import setup


def test_remove_settings_mcp_preserves_other_servers() -> None:
    other_server = {"command": "other-mcp"}
    settings = {
        "mcpServers": {"cwiki": {"env": {"CWIKI_AGENT_TOKEN": "secret"}}, "other": other_server},
        "custom": True,
    }
    setup.remove_settings_mcp(settings, "qoder")
    assert settings["mcpServers"] == {"other": other_server}
    assert settings["custom"] is True
    assert "CWIKI_AGENT_TOKEN" not in json.dumps(settings)


def test_remove_settings_mcp_deletes_empty_mcp_servers() -> None:
    settings = {"mcpServers": {"cwiki": {"command": "python"}}, "custom": True}
    setup.remove_settings_mcp(settings, "qoder")
    assert "mcpServers" not in settings
    assert settings["custom"] is True


def test_patch_plugin_mcp_injects_cwd_and_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_cache = (
        tmp_path / "plugins" / "cache" / "local" / setup.PLUGIN_NAME / setup.plugin_version()
    )
    plugin_cache.mkdir(parents=True)
    mcp_json = plugin_cache / ".mcp.json"
    mcp_json.write_text(
        json.dumps({"mcpServers": {"cwiki": {"args": ["-m", setup.MCP_MODULE]}}}),
        encoding="utf-8",
    )
    root = tmp_path / "中文 项目"
    root.mkdir()
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(setup, "PROJECT_ROOT", root)

    setup.patch_plugin_mcp("qoder")

    server = json.loads(mcp_json.read_text(encoding="utf-8"))["mcpServers"]["cwiki"]
    assert server["command"] == setup.sys.executable
    assert server["cwd"] == str(root)
    assert server["env"]["PYTHONPATH"] == str(root)
    assert server["args"] == ["-m", setup.MCP_MODULE]


def test_patch_plugin_mcp_skips_missing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")
    setup.patch_plugin_mcp("qoder")
    assert "跳过修补" in capsys.readouterr().out


def test_patch_plugin_mcp_derives_cache_version_from_plugin_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    (source / ".qoder-plugin").mkdir(parents=True)
    (source / ".qoder-plugin" / "plugin.json").write_text(
        json.dumps({"name": setup.PLUGIN_NAME, "version": "9.9.9"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "PLUGIN_SOURCE_DIR", source)
    plugins = tmp_path / "plugins"
    plugin_cache = plugins / "cache" / "local" / setup.PLUGIN_NAME / "9.9.9"
    plugin_cache.mkdir(parents=True)
    mcp_json = plugin_cache / ".mcp.json"
    mcp_json.write_text(json.dumps({"mcpServers": {"cwiki": {}}}), encoding="utf-8")
    monkeypatch.setattr(setup, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path / "root")

    setup.patch_plugin_mcp("qoder")

    server = json.loads(mcp_json.read_text(encoding="utf-8"))["mcpServers"]["cwiki"]
    assert server["command"] == setup.sys.executable


def test_ensure_global_mcp_json_injects_and_preserves_other_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cwiki": {
                        "type": "stdio",
                        "command": "python",
                        "args": ["-m", setup.MCP_MODULE],
                        "env": {"PYTHONPATH": "."},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "项目根"
    root.mkdir()
    config_dir = tmp_path / "home" / ".qoder"
    config_dir.mkdir(parents=True)
    existing = {"mcpServers": {"chrome-devtools": {"command": "npx.cmd"}}}
    (config_dir / "mcp.json").write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setattr(setup, "PLUGIN_SOURCE_DIR", source)
    monkeypatch.setattr(setup, "PROJECT_ROOT", root)
    monkeypatch.setitem(
        setup.AGENTS,
        "qoder",
        {**setup.AGENTS["qoder"], "config_dir": config_dir},
    )

    setup.ensure_global_mcp_json()

    global_mcp = config_dir / "mcp.json"
    data = json.loads(global_mcp.read_text(encoding="utf-8"))
    assert "chrome-devtools" in data["mcpServers"]
    server = data["mcpServers"]["cwiki"]
    assert server["command"] == setup.sys.executable
    assert server["cwd"] == str(root)
    assert server["env"]["PYTHONPATH"] == str(root)
    assert server["args"] == ["-m", setup.MCP_MODULE]


def test_ensure_global_mcp_json_skips_missing_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir = tmp_path / "home" / ".qoder"
    config_dir.mkdir(parents=True)
    monkeypatch.setitem(
        setup.AGENTS,
        "qoder",
        {**setup.AGENTS["qoder"], "config_dir": config_dir},
    )
    monkeypatch.setattr(setup, "PLUGIN_SOURCE_DIR", tmp_path / "不存在")
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path / "项目根")
    setup.ensure_global_mcp_json()
    assert "跳过" in capsys.readouterr().out


def _write_hook_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "source"
    (source / ".qoder-plugin").mkdir(parents=True)
    (source / ".qoder-plugin" / "plugin.json").write_text(
        json.dumps({"name": setup.PLUGIN_NAME, "version": "9.9.9"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "PLUGIN_SOURCE_DIR", source)
    return source


def test_patch_plugin_hooks_injects_python_and_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_hook_source(tmp_path, monkeypatch)
    plugins = tmp_path / "plugins"
    hooks_dir = plugins / "cache" / "local" / setup.PLUGIN_NAME / "9.9.9" / "hooks"
    hooks_dir.mkdir(parents=True)
    hooks_json = hooks_dir / "hooks.json"
    hooks_json.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python -m adapters.qoder.hooks session-start",
                                    "env": {"PYTHONPATH": "."},
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(setup, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(setup, "PROJECT_ROOT", root)

    setup.patch_plugin_hooks("qoder")

    hook = json.loads(hooks_json.read_text(encoding="utf-8"))["hooks"]["SessionStart"][0]["hooks"][
        0
    ]
    assert hook["command"] == (f"{setup.sys.executable} -m adapters.qoder.hooks session-start")
    assert hook["env"]["PYTHONPATH"] == str(root)


def test_patch_plugin_hooks_skips_missing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)
    setup.patch_plugin_hooks("qoder")
    assert "跳过修补" in capsys.readouterr().out


def test_ensure_plugin_installed_skips_when_cache_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plugins = tmp_path / "plugins"
    plugin_cache = plugins / "cache" / "local" / setup.PLUGIN_NAME / setup.plugin_version()
    plugin_cache.mkdir(parents=True)
    (plugin_cache / ".mcp.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(setup, "PLUGINS_DIR", plugins)

    with (
        patch.object(setup.shutil, "which") as which,
        patch.object(setup, "run") as run,
    ):
        setup.ensure_plugin_installed("qoder")

    which.assert_not_called()
    run.assert_not_called()
    assert "已安装" in capsys.readouterr().out


def test_ensure_plugin_installed_invokes_qodercli_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plugins = tmp_path / "plugins"
    monkeypatch.setattr(setup, "PLUGINS_DIR", plugins)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> int:
        calls.append(cmd)
        cache = plugins / "cache" / "local" / setup.PLUGIN_NAME / setup.plugin_version()
        cache.mkdir(parents=True, exist_ok=True)
        (cache / ".mcp.json").write_text("{}", encoding="utf-8")
        return 0

    with (
        patch.object(setup.shutil, "which", return_value="/usr/local/bin/qodercli"),
        patch.object(setup, "run", side_effect=fake_run),
    ):
        setup.ensure_plugin_installed("qoder")

    assert calls == [
        ["/usr/local/bin/qodercli", "plugins", "install", str(setup.PLUGIN_SOURCE_DIR)]
    ]
    assert "已安装" in capsys.readouterr().out


def test_ensure_plugin_installed_warns_without_qodercli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")

    with (
        patch.object(setup.shutil, "which", return_value=None),
        patch.object(setup, "run") as run,
    ):
        setup.ensure_plugin_installed("qoder")

    run.assert_not_called()
    out = capsys.readouterr().out
    assert "qodercli" in out
    assert "plugins install" in out


def test_ensure_plugin_installed_warns_when_qodercli_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")

    with (
        patch.object(setup.shutil, "which", return_value="/usr/local/bin/qodercli"),
        patch.object(setup, "run", return_value=1),
    ):
        setup.ensure_plugin_installed("qoder")

    assert "手动运行" in capsys.readouterr().out


def _write_sync_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "source"
    (source / "skills" / "memory-recall").mkdir(parents=True)
    (source / "skills" / "memory-recall" / "SKILL.md").write_text("new skill", encoding="utf-8")
    (source / "README.md").write_text("same readme", encoding="utf-8")
    (source / ".qoder-plugin").mkdir(parents=True)
    (source / ".qoder-plugin" / "plugin.json").write_text(
        json.dumps({"name": setup.PLUGIN_NAME, "version": "9.9.9"}), encoding="utf-8"
    )
    (source / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    (source / "hooks").mkdir()
    (source / "hooks" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    monkeypatch.setattr(setup, "PLUGIN_SOURCE_DIR", source)
    plugins = tmp_path / "plugins"
    monkeypatch.setattr(setup, "PLUGINS_DIR", plugins)
    return plugins / "cache" / "local" / setup.PLUGIN_NAME / "9.9.9"


def test_sync_plugin_cache_updates_stale_content_and_seeds_missing_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = _write_sync_source(tmp_path, monkeypatch)
    (cache / "skills" / "memory-recall").mkdir(parents=True)
    (cache / "skills" / "memory-recall" / "SKILL.md").write_text("old skill", encoding="utf-8")
    (cache / "README.md").write_text("same readme", encoding="utf-8")
    (cache / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"cwiki": {"command": "patched-python"}}}), encoding="utf-8"
    )

    setup.sync_plugin_cache("qoder")

    assert (cache / "skills" / "memory-recall" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "new skill"
    assert (cache / ".qoder-plugin" / "plugin.json").read_bytes() == (
        setup.PLUGIN_SOURCE_DIR / ".qoder-plugin" / "plugin.json"
    ).read_bytes()
    # 已存在的 .mcp.json 不被模板覆盖（绝对路径注入保持有效）
    assert "patched-python" in (cache / ".mcp.json").read_text(encoding="utf-8")
    # 缺失的 hooks 目录从模板补齐
    assert (cache / "hooks" / "hooks.json").read_text(encoding="utf-8") == '{"hooks": {}}'
    out = capsys.readouterr().out
    assert "更新 2 个文件" in out
    assert "补齐 1 项" in out


def test_sync_plugin_cache_repeat_run_reports_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = _write_sync_source(tmp_path, monkeypatch)
    cache.mkdir(parents=True)
    setup.sync_plugin_cache("qoder")
    capsys.readouterr()
    snapshot = {p.relative_to(cache): p.read_bytes() for p in cache.rglob("*") if p.is_file()}

    setup.sync_plugin_cache("qoder")

    assert "已是最新" in capsys.readouterr().out
    assert {
        p.relative_to(cache): p.read_bytes() for p in cache.rglob("*") if p.is_file()
    } == snapshot


def test_sync_plugin_cache_skips_missing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    (source / ".qoder-plugin").mkdir(parents=True)
    (source / ".qoder-plugin" / "plugin.json").write_text(
        json.dumps({"name": setup.PLUGIN_NAME, "version": "9.9.9"}), encoding="utf-8"
    )
    monkeypatch.setattr(setup, "PLUGIN_SOURCE_DIR", source)
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")

    setup.sync_plugin_cache("qoder")

    assert "跳过内容同步" in capsys.readouterr().out
    assert not (tmp_path / "plugins").exists()


def test_ensure_plugin_enabled_cleans_stale_keys_and_sets_local(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings: dict[str, Any] = {
        "enabledPlugins": {
            setup.PLUGIN_NAME: True,
            f"{setup.PLUGIN_NAME}@qoder-marketplace": True,
            "other-plugin": True,
        }
    }
    setup.ensure_plugin_enabled(settings, "qoder")

    assert settings["enabledPlugins"] == {
        f"{setup.PLUGIN_NAME}@local": True,
        "other-plugin": True,
    }
    assert "残留条目" in capsys.readouterr().out


@pytest.fixture
def agents_md_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "home" / ".qoder"
    agents_md = config_dir / "AGENTS.md"
    monkeypatch.setitem(
        setup.AGENTS,
        "qoder",
        {**setup.AGENTS["qoder"], "config_dir": config_dir, "agents_md": agents_md},
    )
    return agents_md


def _cwiki_agents_block() -> str:
    return f"{setup.CWIKI_AGENTS_START}\n{setup.CWIKI_AGENTS_MD}{setup.CWIKI_AGENTS_END}"


@pytest.mark.parametrize("config_dir_exists", [False, True])
def test_agents_md_new_file_uses_global_defaults(
    agents_md_path: Path, config_dir_exists: bool
) -> None:
    if config_dir_exists:
        agents_md_path.parent.mkdir(parents=True)

    setup.ensure_agents_md("qoder")

    content = agents_md_path.read_text(encoding="utf-8")
    assert content == setup.GLOBAL_AGENTS_MD
    assert content.count(setup.CWIKI_AGENTS_START) == 1
    assert content.count(setup.CWIKI_AGENTS_END) == 1
    assert _cwiki_agents_block() in content
    assert "按需" in content
    assert "memory_search" in content
    assert "memory_save" in content
    assert "memory_update" in content
    assert "无真实信号就跳过" in content
    assert "workspace_name" in content
    assert "mwk_agent_" not in content
    assert "candidate_id" in content
    assert "标题可选" not in content
    assert "至少 5 个字符" not in content
    assert not list(agents_md_path.parent.glob("AGENTS.md.cwiki-*.bak"))


@pytest.mark.parametrize(
    "existing",
    [
        "",
        "# 自定义指引\n保留用户原文和末尾空格。  ",
        "# 自定义指引\n保留单个换行。\n",
        "# 自定义指引\n保留多个换行。\n\n\n",
        "个人笔记中提及 cwiki，但这不是托管区块。\n",
        "## cwiki 使用心得\n这个章节属于用户。\n",
        "### cwiki 记忆系统\n三级标题不属于旧版二级章节。\n",
        "## cwiki 记忆系统参考\n相似标题不应被替换。\n",
    ],
    ids=["empty", "no_newline", "newline", "blank_lines", "mention", "custom_h2", "h3", "similar"],
)
def test_agents_md_appends_block_without_replacing_custom_content(
    agents_md_path: Path, existing: str
) -> None:
    agents_md_path.parent.mkdir(parents=True)
    agents_md_path.write_text(existing, encoding="utf-8")

    setup.ensure_agents_md("qoder")

    updated = agents_md_path.read_text(encoding="utf-8")
    assert updated.startswith(existing)
    assert updated[len(existing) :].lstrip("\n") == _cwiki_agents_block() + "\n"
    assert not list(agents_md_path.parent.glob("AGENTS.md.cwiki-*.bak"))


@pytest.mark.parametrize("old_body", ["", "\n## cwiki 记忆系统\n旧版工具契约。\n"])
@pytest.mark.parametrize(
    "prefix, suffix",
    [
        ("", ""),
        ("# 我的指引\n仅维护自己的偏好。\n\n", "\n\n## 个人规则\n保留末尾空格。  \n"),
    ],
    ids=["block_only", "custom_surroundings"],
)
def test_agents_md_updates_only_the_managed_block(
    agents_md_path: Path, old_body: str, prefix: str, suffix: str
) -> None:
    agents_md_path.parent.mkdir(parents=True)
    agents_md_path.write_text(
        prefix + setup.CWIKI_AGENTS_START + old_body + setup.CWIKI_AGENTS_END + suffix,
        encoding="utf-8",
    )

    setup.ensure_agents_md("qoder")

    assert agents_md_path.read_text(encoding="utf-8") == prefix + _cwiki_agents_block() + suffix
    assert not list(agents_md_path.parent.glob("AGENTS.md.cwiki-*.bak"))


@pytest.mark.parametrize(
    "markers",
    [
        ("start",),
        ("end",),
        ("end", "start"),
        ("start", "end", "start", "end"),
        ("start", "start", "end"),
        ("start", "end", "end"),
        ("start", "start", "end", "end"),
    ],
    ids=["start_only", "end_only", "reversed", "two_pairs", "two_starts", "two_ends", "nested"],
)
def test_agents_md_rejects_ambiguous_markers_without_writing(
    agents_md_path: Path, markers: tuple[str, ...]
) -> None:
    delimiters = {"start": setup.CWIKI_AGENTS_START, "end": setup.CWIKI_AGENTS_END}
    original = (
        "# 个人指引\n保留原文。\n\n## cwiki 记忆系统\n旧版正文。\n"
        + "\n".join(delimiters[marker] for marker in markers)
        + "\n## 自定义规则\n禁止丢失本段。\n"
    ).encode()
    agents_md_path.parent.mkdir(parents=True)
    agents_md_path.write_bytes(original)

    with patch.object(Path, "write_text") as write, pytest.raises(SystemExit) as exc:
        setup.ensure_agents_md("qoder")

    assert exc.value.code == 1
    write.assert_not_called()
    assert agents_md_path.read_bytes() == original
    assert not list(agents_md_path.parent.glob("AGENTS.md.cwiki-*.bak"))


@pytest.mark.parametrize("heading", ["## cwiki 记忆系统\n", "## cwiki 记忆系统 \t\n"])
@pytest.mark.parametrize(
    "suffix",
    ["", "# 个人规则\n保留一级章节。\n", "## 个人规则\n保留二级章节。  \n"],
    ids=["end_of_file", "next_h1", "next_h2"],
)
def test_agents_md_migrates_legacy_section_with_original_backup(
    agents_md_path: Path, heading: str, suffix: str
) -> None:
    prefix = "# 个人指引\n这里也提到了 cwiki，但不属于旧章节。\n\n"
    legacy_body = "旧工具契约。\n\n### 旧规则\n旧版三级章节。\n\n#### 旧细节\n旧版四级章节。\n\n"
    original = prefix + heading + legacy_body + suffix
    agents_md_path.parent.mkdir(parents=True)
    agents_md_path.write_text(original, encoding="utf-8")
    original_bytes = agents_md_path.read_bytes()
    write_text = Path.write_text

    def write_after_backup(path: Path, data: str, **kwargs: str) -> int:
        if path == agents_md_path:
            backups = list(path.parent.glob("AGENTS.md.cwiki-*.bak"))
            assert len(backups) == 1
            assert backups[0].read_bytes() == original_bytes
        return write_text(path, data, **kwargs)

    with patch.object(Path, "write_text", new=write_after_backup):
        setup.ensure_agents_md("qoder")

    updated = agents_md_path.read_text(encoding="utf-8")
    assert updated == prefix + _cwiki_agents_block() + "\n\n" + suffix
    backups = list(agents_md_path.parent.glob("AGENTS.md.cwiki-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original_bytes


@pytest.mark.parametrize("failure_stage", ["create_backup", "copy_backup"])
def test_agents_md_backup_failure_keeps_original_untouched(
    agents_md_path: Path, failure_stage: str
) -> None:
    agents_md_path.parent.mkdir(parents=True)
    original = "# 个人指引\n自定义内容。\n\n## cwiki 记忆系统\n旧版正文。\n".encode()
    agents_md_path.write_bytes(original)
    target, method = (
        (setup.tempfile, "mkstemp") if failure_stage == "create_backup" else (setup.shutil, "copy2")
    )

    with (
        patch.object(target, method, side_effect=PermissionError("backup unavailable")) as backup,
        patch.object(Path, "write_text") as write,
        pytest.raises((OSError, SystemExit)),
    ):
        setup.ensure_agents_md("qoder")

    backup.assert_called_once()
    write.assert_not_called()
    assert agents_md_path.read_bytes() == original


@pytest.mark.parametrize("initial_state", ["missing", "custom", "managed", "current", "legacy"])
def test_agents_md_repeat_install_does_not_write_or_create_another_backup(
    agents_md_path: Path, initial_state: str
) -> None:
    if initial_state != "missing":
        initial_content = {
            "custom": "# 个人指引\n保留自定义配置。\n",
            "managed": f"{setup.CWIKI_AGENTS_START}\n过时正文。\n{setup.CWIKI_AGENTS_END}\n",
            "current": setup.GLOBAL_AGENTS_MD,
            "legacy": "# 个人指引\n\n## cwiki 记忆系统\n旧版内容。\n",
        }[initial_state]
        agents_md_path.parent.mkdir(parents=True)
        agents_md_path.write_text(initial_content, encoding="utf-8")
    setup.ensure_agents_md("qoder")
    snapshot = {path.name: path.read_bytes() for path in agents_md_path.parent.iterdir()}

    with patch.object(Path, "write_text") as write:
        setup.ensure_agents_md("qoder")

    write.assert_not_called()
    assert {path.name: path.read_bytes() for path in agents_md_path.parent.iterdir()} == snapshot


@pytest.fixture
def skill_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    source_dir = tmp_path / "repo" / "skills" / "cwiki-save"
    source_dir.mkdir(parents=True)
    (source_dir / "SKILL.md").write_text("name: cwiki-save\n", encoding="utf-8")
    skills_dir = tmp_path / "home" / ".qoder" / "skills"
    monkeypatch.setitem(
        setup.AGENTS,
        "qoder",
        {**setup.AGENTS["qoder"], "skill_source": source_dir, "skills_dir": skills_dir},
    )
    return source_dir, skills_dir


@pytest.fixture
def symlinks_available(tmp_path: Path) -> None:
    target = tmp_path / "symlink-target"
    target.mkdir()
    try:
        (tmp_path / "symlink-probe").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this system")


def test_configured_skill_source_exists() -> None:
    source_dir = setup.AGENTS["qoder"]["skill_source"]
    assert source_dir == setup.PROJECT_ROOT / "skills" / "cwiki-save"
    assert (source_dir / "SKILL.md").is_file()


def test_installs_skill_symlink_without_touching_old_directory(
    skill_paths: tuple[Path, Path], symlinks_available: None
) -> None:
    source_dir, skills_dir = skill_paths
    old_dir = skills_dir / "cwiki"
    old_dir.mkdir(parents=True)
    old_file = old_dir / "SKILL.md"
    old_file.write_text("user content", encoding="utf-8")

    setup.ensure_skill("qoder")

    installed = skills_dir / "cwiki-save"
    assert installed.is_symlink()
    assert installed.resolve() == source_dir.resolve()
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == "name: cwiki-save\n"
    assert old_file.read_text(encoding="utf-8") == "user content"

    (source_dir / "SKILL.md").write_text("updated content", encoding="utf-8")
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == "updated content"


def test_existing_correct_symlink_is_reused(
    skill_paths: tuple[Path, Path], symlinks_available: None
) -> None:
    source_dir, skills_dir = skill_paths
    skills_dir.mkdir(parents=True)
    installed = skills_dir / "cwiki-save"
    installed.symlink_to(source_dir, target_is_directory=True)

    with patch.object(setup.os, "symlink") as create_link:
        setup.ensure_skill("qoder")

    create_link.assert_not_called()
    assert installed.is_symlink()
    assert installed.resolve() == source_dir.resolve()


def test_copies_skill_when_symlinks_are_unavailable(
    skill_paths: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir, skills_dir = skill_paths

    with patch.object(setup.os, "symlink", side_effect=OSError("Symlinks unavailable")) as link:
        setup.ensure_skill("qoder")

    link.assert_called_once_with(source_dir, skills_dir / "cwiki-save", target_is_directory=True)
    installed = skills_dir / "cwiki-save"
    assert not installed.is_symlink()
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == "name: cwiki-save\n"
    assert not (skills_dir / "cwiki").exists()
    assert "修改源文件后需重新运行" in capsys.readouterr().out


def test_reinstall_updates_copied_skill(skill_paths: tuple[Path, Path]) -> None:
    source_dir, skills_dir = skill_paths

    with patch.object(setup.os, "symlink", side_effect=OSError("Symlinks unavailable")):
        setup.ensure_skill("qoder")
        (source_dir / "SKILL.md").write_text("updated content", encoding="utf-8")
        setup.ensure_skill("qoder")

    installed = skills_dir / "cwiki-save" / "SKILL.md"
    assert installed.read_text(encoding="utf-8") == "updated content"


@pytest.mark.parametrize("invalid_source", ["missing_directory", "missing_file", "directory"])
@pytest.mark.parametrize("existing_install", [False, True])
def test_invalid_source_fails_before_changing_installation(
    skill_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invalid_source: str,
    existing_install: bool,
) -> None:
    source_dir, skills_dir = skill_paths
    invalid_dir = source_dir.parent / "unavailable" / "cwiki-save"
    if invalid_source != "missing_directory":
        invalid_dir.mkdir(parents=True)
    if invalid_source == "directory":
        (invalid_dir / "SKILL.md").mkdir()
    monkeypatch.setitem(setup.AGENTS["qoder"], "skill_source", invalid_dir)
    installed = skills_dir / "cwiki-save"
    if existing_install:
        installed.mkdir(parents=True)
        (installed / "SKILL.md").write_text("existing content", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        setup.ensure_skill("qoder")

    assert exc.value.code == 1
    assert str(invalid_dir / "SKILL.md") in capsys.readouterr().out
    if existing_install:
        assert (installed / "SKILL.md").read_text(encoding="utf-8") == "existing content"
    else:
        assert not skills_dir.exists()


@pytest.mark.parametrize("command", ["init_db", "serve"])
def test_database_and_serve_use_system_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    root = tmp_path / "中文 项目"
    monkeypatch.setattr(setup, "PROJECT_ROOT", root)
    monkeypatch.chdir(tmp_path)
    with (
        patch.object(setup.subprocess, "call", return_value=0) as invoke,
        patch.object(setup.shutil, "which", return_value="/tools/git"),
    ):
        getattr(setup, command)()
    args = (
        ["-m", "alembic", "upgrade", "head"]
        if command == "init_db"
        else ["-m", "uvicorn", "apps.api.main:app", "--reload", "--port", "5172"]
    )
    invoke.assert_called_once_with([setup.sys.executable, *args], cwd=str(root))


@pytest.mark.parametrize("encoding", ["ascii", "gbk", "cp1252", "utf-8"])
def test_messages_handle_non_utf8_stdout(monkeypatch: pytest.MonkeyPatch, encoding: str) -> None:
    buffer = io.BytesIO()
    with io.TextIOWrapper(buffer, encoding=encoding, errors="strict") as output:
        with monkeypatch.context() as context:
            context.setattr(setup.sys, "stdout", output)
            setup.info("中文配置成功")
            setup.warn("中文配置警告")
            setup.print_message("╔══ cwiki 配置向导 ══╗")
            with pytest.raises(SystemExit) as exc:
                setup.fail("中文配置失败")
        assert exc.value.code == 1
        output.flush()
        text = buffer.getvalue().decode(encoding)
        assert "cwiki" in text
        if encoding in ("gbk", "utf-8"):
            assert "中文配置成功" in text
            assert "中文配置失败" in text


@pytest.mark.parametrize("stale_skill", [False, True])
def test_check_installation_is_read_only_and_never_claims_host_loaded(
    agents_md_path: Path,
    skill_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stale_skill: bool,
) -> None:
    source_dir, skills_dir = skill_paths
    setup.ensure_agents_md("qoder")
    installed = skills_dir / "cwiki-save" / "SKILL.md"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"old" if stale_skill else (source_dir / "SKILL.md").read_bytes())
    settings_file = agents_md_path.parent / "settings.json"
    token = "test-token-must-not-appear-in-output"
    settings_file.write_text(
        json.dumps({"enabledPlugins": {f"{setup.PLUGIN_NAME}@local": True}}),
        encoding="utf-8",
    )
    monkeypatch.setitem(setup.AGENTS["qoder"], "settings_file", settings_file)
    plugin_cache = (
        tmp_path / "plugins" / "cache" / "local" / setup.PLUGIN_NAME / setup.plugin_version()
    )
    plugin_cache.mkdir(parents=True)
    (plugin_cache / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cwiki": {
                        "command": setup.sys.executable,
                        "args": ["-m", setup.MCP_MODULE],
                        "env": {"CWIKI_AGENT_TOKEN": token},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")
    project_root = tmp_path / "不存在的项目"
    project_root.mkdir(parents=True)
    config_dir = tmp_path / ".qoder"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cwiki": {
                        "command": setup.sys.executable,
                        "args": ["-m", setup.MCP_MODULE],
                        "cwd": str(project_root),
                        "env": {"PYTHONPATH": str(project_root)},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(setup.AGENTS["qoder"], "config_dir", config_dir)
    monkeypatch.setattr(setup, "PROJECT_ROOT", project_root)
    with (
        patch.object(Path, "write_text") as write_text,
        patch.object(Path, "write_bytes") as write_bytes,
        patch.object(setup.subprocess, "call") as invoke,
        patch.object(
            setup,
            "probe_mcp_discovery",
            return_value={"ok": True, "total_seconds": 0.5, "tools_count": 10, "error": None},
        ) as probe,
    ):
        report = setup.check_installation("qoder")
    write_text.assert_not_called()
    write_bytes.assert_not_called()
    invoke.assert_not_called()
    probe.assert_called_once()
    assert report["status"] == ("attention_required" if stale_skill else "ok")
    assert report["skill_current"] is not stale_skill
    assert report["mcp_configured"] is True
    assert report["host_verified"] is False
    assert report["scope"] == "disk_and_spawn_probe"
    assert report["warnings"] == []
    assert token not in json.dumps(report)


@pytest.mark.parametrize("settings_exist", [False, True])
def test_sync_instructions_mode_syncs_plugin_content_without_database(
    monkeypatch, tmp_path: Path, settings_exist: bool
) -> None:
    settings_file = tmp_path / "settings.json"
    settings = {
        "mcpServers": {
            "cwiki": {
                "command": setup.sys.executable,
                "args": ["-m", setup.MCP_MODULE],
            }
        },
        "enabledPlugins": {"cwiki-qoder": False, "other-plugin": True},
        "custom": "preserved",
    }
    if settings_exist:
        settings_file.write_text(json.dumps(settings), encoding="utf-8")
    config_dir = tmp_path / ".qoder"
    monkeypatch.setitem(
        setup.AGENTS,
        "qoder",
        {**setup.AGENTS["qoder"], "settings_file": settings_file, "config_dir": config_dir},
    )
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(setup.sys, "argv", ["setup.py", "--sync-instructions"])
    with (
        patch.object(setup, "ensure_agents_md") as agents,
        patch.object(setup, "ensure_skill") as skill,
        patch.object(setup, "ensure_plugin_installed") as install,
        patch.object(setup, "sync_plugin_cache") as sync_cache,
        patch.object(setup, "patch_plugin_mcp") as patch_mcp,
        patch.object(setup, "patch_plugin_hooks") as patch_hooks,
        patch.object(setup, "init_db") as database,
    ):
        setup.main()
    agents.assert_called_once_with("qoder")
    skill.assert_called_once_with("qoder")
    install.assert_called_once_with("qoder")
    sync_cache.assert_called_once_with("qoder")
    patch_mcp.assert_called_once_with("qoder")
    patch_hooks.assert_called_once_with("qoder")
    database.assert_not_called()
    # 全局 mcp.json 必须写入隔离的 config_dir，而不是真实 ~/.qoder
    global_mcp = json.loads((config_dir / "mcp.json").read_text(encoding="utf-8"))
    server = global_mcp["mcpServers"]["cwiki"]
    assert server["command"] == setup.sys.executable
    assert server["cwd"] == str(tmp_path)
    assert server["env"]["PYTHONPATH"] == str(tmp_path)
    if settings_exist:
        synced = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "mcpServers" not in synced
        assert synced["enabledPlugins"] == {"cwiki-qoder@local": True, "other-plugin": True}
        assert synced["custom"] == "preserved"
    else:
        assert not settings_file.exists()


@pytest.mark.parametrize("settings_content", ["not json", "[]", "null", '{"mcpServers": null}'])
def test_check_installation_reports_invalid_configuration(
    agents_md_path: Path, skill_paths: tuple[Path, Path], monkeypatch, settings_content: str
) -> None:
    agents_md_path.parent.mkdir(parents=True, exist_ok=True)
    settings_file = agents_md_path.parent / "settings.json"
    settings_file.write_text(settings_content, encoding="utf-8")
    monkeypatch.setitem(setup.AGENTS["qoder"], "settings_file", settings_file)
    with patch.object(
        setup,
        "probe_mcp_discovery",
        return_value={"ok": True, "total_seconds": 0.5, "tools_count": 10, "error": None},
    ):
        result = setup.check_installation("qoder")
    assert result["status"] == "attention_required"
    assert "无法解析 Qoder MCP 配置" in result["errors"]


class _FakeProc:
    """模拟 probe_mcp_discovery spawn 的子进程：按预置行输出，立即 EOF。"""

    def __init__(self, stdout_lines: list[str], stderr_text: str = "") -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(stdout_lines))
        self.stderr = io.StringIO(stderr_text)
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = 0


def _initialize_response() -> str:
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "cwiki", "version": "0.1.0"},
                },
            }
        )
        + "\n"
    )


def _tools_response(count: int = 3) -> str:
    tools = [{"name": f"tool_{i}", "description": "d", "inputSchema": {}} for i in range(count)]
    return json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}}) + "\n"


def test_probe_mcp_discovery_success() -> None:
    fake = _FakeProc([_initialize_response(), _tools_response(10)])
    server = {"command": "python", "args": ["-m", setup.MCP_MODULE], "env": {"PYTHONPATH": "."}}

    with patch.object(setup.subprocess, "Popen", return_value=fake) as popen:
        probe = setup.probe_mcp_discovery(server)

    assert probe["ok"] is True
    assert probe["tools_count"] == 10
    assert probe["error"] is None
    assert probe["total_seconds"] is not None
    _, kwargs = popen.call_args
    assert kwargs["cwd"] == str(setup.PROJECT_ROOT)
    assert kwargs["env"]["PYTHONPATH"] == "."
    sent = [json.loads(line) for line in fake.stdin.getvalue().splitlines() if line.strip()]
    assert [message["method"] for message in sent] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "exit",
    ]


def test_probe_mcp_discovery_spawn_failure() -> None:
    with patch.object(setup.subprocess, "Popen", side_effect=FileNotFoundError("找不到命令")):
        probe = setup.probe_mcp_discovery({"command": "missing-python", "args": []})

    assert probe["ok"] is False
    assert probe["tools_count"] is None
    assert "找不到命令" in probe["error"]


def test_probe_mcp_discovery_server_exits_without_response() -> None:
    fake = _FakeProc([])
    with patch.object(setup.subprocess, "Popen", return_value=fake):
        probe = setup.probe_mcp_discovery({"command": "python", "args": []})

    assert probe["ok"] is False
    assert "退出" in probe["error"]


def test_probe_mcp_discovery_jsonrpc_error_response() -> None:
    error_line = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad params"}})
        + "\n"
    )
    fake = _FakeProc([error_line])
    with patch.object(setup.subprocess, "Popen", return_value=fake):
        probe = setup.probe_mcp_discovery({"command": "python", "args": []})

    assert probe["ok"] is False
    assert "bad params" in probe["error"]


def test_probe_mcp_discovery_step_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup, "DISCOVERY_STEP_TIMEOUT_SECONDS", 0.0)
    fake = _FakeProc([_initialize_response(), _tools_response()])
    with patch.object(setup.subprocess, "Popen", return_value=fake):
        probe = setup.probe_mcp_discovery({"command": "python", "args": []})

    assert probe["ok"] is False
    assert "超时" in probe["error"]


def test_probe_mcp_discovery_redacts_env_secrets_from_error() -> None:
    fake = _FakeProc([], stderr_text="启动失败 token=test-secret-token 无法连接\n")
    server = {
        "command": "python",
        "args": [],
        "env": {"CWIKI_AGENT_TOKEN": "test-secret-token"},
    }
    with patch.object(setup.subprocess, "Popen", return_value=fake):
        probe = setup.probe_mcp_discovery(server)

    assert probe["ok"] is False
    assert "test-secret-token" not in probe["error"]
    assert "***" in probe["error"]


@pytest.fixture
def doctor_environment(
    agents_md_path: Path,
    skill_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir, skills_dir = skill_paths
    setup.ensure_agents_md("qoder")
    installed = skills_dir / "cwiki-save" / "SKILL.md"
    installed.parent.mkdir(parents=True)
    installed.write_bytes((source_dir / "SKILL.md").read_bytes())
    settings_file = agents_md_path.parent / "settings.json"
    settings_file.write_text(
        json.dumps({"enabledPlugins": {f"{setup.PLUGIN_NAME}@local": True}}), encoding="utf-8"
    )
    monkeypatch.setitem(setup.AGENTS["qoder"], "settings_file", settings_file)
    plugin_cache = (
        tmp_path / "plugins" / "cache" / "local" / setup.PLUGIN_NAME / setup.plugin_version()
    )
    plugin_cache.mkdir(parents=True)
    (plugin_cache / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cwiki": {"command": setup.sys.executable, "args": ["-m", setup.MCP_MODULE]}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "PLUGINS_DIR", tmp_path / "plugins")
    project_root = tmp_path / "不存在的项目"
    project_root.mkdir(parents=True)
    config_dir = tmp_path / ".qoder"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cwiki": {
                        "command": setup.sys.executable,
                        "args": ["-m", setup.MCP_MODULE],
                        "cwd": str(project_root),
                        "env": {"PYTHONPATH": str(project_root)},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(setup.AGENTS["qoder"], "config_dir", config_dir)
    monkeypatch.setattr(setup, "PROJECT_ROOT", project_root)


@pytest.mark.parametrize(
    "probe_result, expected_status, expected_fragment, report_key",
    [
        (
            {"ok": True, "total_seconds": 0.5, "tools_count": 10, "error": None},
            "ok",
            None,
            None,
        ),
        (
            {"ok": True, "total_seconds": 12.3, "tools_count": 10, "error": None},
            "ok",
            "Defender",
            "warnings",
        ),
        (
            {"ok": False, "total_seconds": 1.0, "tools_count": None, "error": "spawn 失败"},
            "ok",
            "发现自检失败",
            "warnings",
        ),
    ],
    ids=["fast_ok", "slow_warning", "failure_error"],
)
def test_check_installation_reports_discovery_probe(
    doctor_environment: None,
    probe_result: dict[str, Any],
    expected_status: str,
    expected_fragment: str | None,
    report_key: str | None,
) -> None:
    with patch.object(setup, "probe_mcp_discovery", return_value=probe_result) as probe:
        report = setup.check_installation("qoder")

    probe.assert_called_once()
    assert report["discovery"] == probe_result
    assert report["status"] == expected_status
    if expected_fragment is not None and report_key is not None:
        assert any(expected_fragment in item for item in report[report_key])
    else:
        assert report["warnings"] == []


def test_check_installation_skips_probe_when_command_unavailable(
    doctor_environment: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_cache = (
        tmp_path / "plugins" / "cache" / "local" / setup.PLUGIN_NAME / setup.plugin_version()
    )
    (plugin_cache / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cwiki": {"command": "missing-python-x", "args": ["-m", setup.MCP_MODULE]}
                }
            }
        ),
        encoding="utf-8",
    )
    with patch.object(setup, "probe_mcp_discovery") as probe:
        report = setup.check_installation("qoder")

    probe.assert_not_called()
    assert "discovery" not in report
    assert any("Python 解释器不可用" in item for item in report["warnings"])
