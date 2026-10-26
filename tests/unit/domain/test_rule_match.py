"""matches_fields 的专项测试：覆盖各维度的匹配语义与边界条件。"""

from __future__ import annotations

import pytest

from packages.domain.rule_match import matches_fields


def _match(**overrides: object) -> bool:
    defaults = dict(
        workspaces=[],
        types=[],
        tags=[],
        keywords=[],
        workspace_name="cwiki",
        workspace_id="ws-1",
        memory_type="fact",
        memory_tags=[],
        title="",
        content="",
    )
    defaults.update(overrides)
    return matches_fields(**defaults)  # type: ignore[arg-type]


class TestEmptyFilters:
    """空过滤列表不限制该维度。"""

    def test_all_empty_returns_true(self):
        assert _match() is True

    def test_empty_workspaces_skips_workspace_check(self):
        assert _match(workspaces=[], workspace_name="anything") is True

    def test_empty_types_skips_type_check(self):
        assert _match(types=[], memory_type="unknown") is True

    def test_empty_tags_skips_tags_check(self):
        assert _match(tags=[], memory_tags=[]) is True

    def test_empty_keywords_skips_keyword_check(self):
        assert _match(keywords=[], content="") is True


class TestWorkspaceMatching:
    def test_matches_workspace_name(self):
        assert _match(workspaces=["cwiki"]) is True

    def test_matches_workspace_id(self):
        assert _match(workspaces=["ws-1"]) is True

    def test_case_insensitive(self):
        assert _match(workspaces=["CWiki"]) is True

    def test_no_match_returns_false(self):
        assert _match(workspaces=["other"]) is False

    def test_multiple_workspaces_or_semantics(self):
        assert _match(workspaces=["other", "cwiki"]) is True

    def test_empty_workspace_name_and_id(self):
        assert _match(workspaces=["cwiki"], workspace_name="", workspace_id="") is False

    def test_whitespace_only_workspace(self):
        assert _match(workspaces=["cwiki"], workspace_name="  ", workspace_id="") is False


class TestTypeMatching:
    def test_matches_type(self):
        assert _match(types=["fact"]) is True

    def test_case_insensitive(self):
        assert _match(types=["Fact", "FACT"]) is True

    def test_no_match_returns_false(self):
        assert _match(types=["decision"]) is False

    def test_multiple_types_or_semantics(self):
        assert _match(types=["decision", "fact"]) is True


class TestTagsMatching:
    def test_all_tags_must_exist(self):
        assert _match(tags=["a", "b"], memory_tags=["a", "b", "c"]) is True

    def test_missing_tag_returns_false(self):
        assert _match(tags=["a", "x"], memory_tags=["a", "b"]) is False

    def test_case_insensitive(self):
        assert _match(tags=["Pinned"], memory_tags=["pinned"]) is True

    def test_empty_memory_tags_with_required_tags(self):
        assert _match(tags=["a"], memory_tags=[]) is False


class TestKeywordMatching:
    def test_keyword_in_content(self):
        assert _match(keywords=["api_key"], content="leaked api_key=sk-xxx") is True

    def test_keyword_in_title(self):
        assert _match(keywords=["部署"], title="部署约定") is True

    def test_keyword_across_title_and_content(self):
        assert _match(keywords=["约定"], title="部署", content="约定说明") is True

    def test_no_keyword_match_returns_false(self):
        assert _match(keywords=["missing"], content="some text") is False

    def test_multiple_keywords_or_semantics(self):
        assert _match(keywords=["a", "b"], content="has b only") is True

    def test_case_insensitive(self):
        assert _match(keywords=["Bearer"], content="bearer token here") is True

    def test_cross_boundary_no_false_match(self):
        """title 末尾 + content 开头拼接不应命中。"""
        assert _match(keywords=["部署约定"], title="部署", content="约定") is False

    def test_empty_title_and_content(self):
        assert _match(keywords=["test"], title="", content="") is False


class TestDefensiveGuards:
    """空值/空白防御：上游未过滤时不应误匹配。"""

    def test_empty_string_in_keywords_skipped(self):
        """空白关键词被过滤后无有效关键词，跳过该维度。"""
        assert _match(keywords=[""], content="anything") is True

    def test_whitespace_only_keyword_skipped(self):
        """纯空白关键词被过滤后跳过该维度。"""
        assert _match(keywords=["  "], content="anything") is True

    def test_empty_string_in_workspaces_does_not_match(self):
        assert _match(workspaces=[""], workspace_name="", workspace_id="") is False

    def test_empty_string_in_types_does_not_match(self):
        assert _match(types=[""], memory_type="") is False

    def test_empty_string_in_tags_skipped(self):
        """空白 tag 被过滤后无有效要求，应通过。"""
        assert _match(tags=[""], memory_tags=[]) is True

    def test_mixed_empty_and_valid_keywords(self):
        assert _match(keywords=["", "valid"], content="has valid keyword") is True

    def test_mixed_empty_and_valid_workspaces(self):
        assert _match(workspaces=["", "cwiki"], workspace_name="cwiki") is True


class TestCombinedFilters:
    """多维度 AND 语义。"""

    def test_all_fields_must_match(self):
        assert _match(
            workspaces=["cwiki"],
            types=["fact"],
            tags=["pinned"],
            keywords=["原理"],
            memory_tags=["pinned"],
            content="原理解析",
        ) is True

    def test_one_field_fails_returns_false(self):
        assert _match(
            workspaces=["cwiki"],
            types=["decision"],  # 不匹配
            content="some text",
        ) is False

    def test_workspace_and_type_match_but_keyword_fails(self):
        assert _match(
            workspaces=["cwiki"],
            types=["fact"],
            keywords=["missing"],
            content="some text",
        ) is False
