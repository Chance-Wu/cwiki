"""GitVersionControl 测试。"""

import asyncio
import subprocess

from packages.storage.git_version import GitVersionControl


async def test_log_on_repo_without_commits_returns_empty_list(tmp_path):
    vc = GitVersionControl(str(tmp_path))
    assert await vc.log() == []


async def test_log_returns_commits_after_first_commit(tmp_path):
    vc = GitVersionControl(str(tmp_path))
    (tmp_path / "note.md").write_text("hello")
    await vc.commit("first commit")

    commits = await vc.log()
    assert len(commits) == 1
    assert commits[0]["message"] == "first commit"
    assert commits[0]["hash"]
    assert commits[0]["date"]
    assert await vc.has_changes() is False


async def test_has_changes_on_repo_without_commits(tmp_path):
    vc = GitVersionControl(str(tmp_path))
    (tmp_path / "note.md").write_text("hello")
    assert await vc.has_changes() is True


async def test_nested_path_uses_parent_repo_without_creating_nested_repo(tmp_path):
    """没有自身仓库的嵌套路径绝不能凭空获得 .git。

    回归背景：API 在 ``cwiki-data`` 上实例化 GitVersionControl 时，旧实现
    会在每次全新导入时触发 ``git init``，复活一个过期的嵌套仓库。
    自动初始化只应发生在任何 work tree 之外；cwiki-data 自带仓库的
    标准分离布局由下一个测试覆盖。
    """
    outer = tmp_path / "outer"
    outer.mkdir()
    root_vc = GitVersionControl(str(outer))
    (outer / "code.py").write_text("print('hi')")
    await root_vc.commit("root commit")

    data = outer / "data"
    data.mkdir()
    nested_vc = GitVersionControl(str(data))
    assert not (data / ".git").exists()

    # 嵌套路径的版本历史只覆盖该目录的子树。
    assert await nested_vc.log() == []
    (data / "note.md").write_text("hello")
    await nested_vc.commit("nested commit")
    assert [c["message"] for c in await nested_vc.log()] == ["nested commit"]

    # 父仓库包含两个提交。
    assert len(await root_vc.log()) == 2

    # 嵌套目录之外的变化不由它上报。
    (outer / "code.py").write_text("print('changed')")
    assert await nested_vc.has_changes() is False
    assert await root_vc.has_changes() is True


async def test_nested_path_with_own_repo_uses_that_repo(tmp_path):
    """自带仓库的 cwiki-data（分离布局）按原样使用。"""
    outer = tmp_path / "outer"
    outer.mkdir()
    root_vc = GitVersionControl(str(outer))
    (outer / "code.py").write_text("print('hi')")
    await root_vc.commit("root commit")

    data = outer / "data"
    data.mkdir()
    await asyncio.to_thread(
        subprocess.run, ["git", "init", "-q", "-b", "master"], cwd=data, check=True
    )

    data_vc = GitVersionControl(str(data))
    assert (data / ".git").exists()
    (data / "cwiki.db").write_text("data")
    await data_vc.commit("data commit")

    # 嵌套仓库拥有自己的历史…
    assert [c["message"] for c in await data_vc.log()] == ["data commit"]
    assert await data_vc.has_changes() is False
    # …而父仓库不参与其中。
    assert [c["message"] for c in await root_vc.log()] == ["root commit"]
