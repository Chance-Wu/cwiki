"""填空出题与判分：与前端 cloze 规则一致，答案归一后多重集匹配。"""

from __future__ import annotations

from packages.memory.quiz import ClozeQuiz, build_cloze_quiz, score_cloze_quiz


def test_build_cloze_masks_first_non_code_occurrence() -> None:
    content = (
        "ThreadPool 必须设置 max_workers，否则任务会排队。\n\n"
        "```python\nThreadPool(max_workers=4)\n```\n"
    )

    quiz = build_cloze_quiz("`ThreadPool` 配置", content, ["python", "并发"])

    assert quiz is not None
    assert quiz.terms == ["ThreadPool"]
    assert quiz.prompt.startswith("____ 必须设置 max_workers")
    # 代码块中的同名标识符不能被挖空
    assert "```python\nThreadPool(max_workers=4)\n```" in quiz.prompt


def test_no_usable_terms_returns_none() -> None:
    assert build_cloze_quiz("短标题", "没有标签也没有英文标识符。", []) is None


def test_scoring_is_case_whitespace_and_punctuation_insensitive() -> None:
    quiz = ClozeQuiz(prompt="____ ____", terms=["ThreadPool", "max_workers"])

    score = score_cloze_quiz(quiz, [" thread pool ", "MAX-WORKERS"])

    assert score.correct is True
    assert score.matched == 2
    assert score.quality == 5


def test_scoring_partial_maps_to_quality_three() -> None:
    quiz = ClozeQuiz(prompt="____ ____", terms=["alpha", "beta"])

    score = score_cloze_quiz(quiz, ["alpha", ""])

    assert score.correct is False
    assert score.matched == 1
    assert score.quality == 3


def test_scoring_all_wrong_maps_to_quality_one() -> None:
    quiz = ClozeQuiz(prompt="____", terms=["alpha"])

    score = score_cloze_quiz(quiz, ["wrong"])

    assert score.correct is False
    assert score.matched == 0
    assert score.quality == 1


def test_duplicate_answers_do_not_overcount() -> None:
    quiz = ClozeQuiz(prompt="____ ____", terms=["alpha", "beta"])

    score = score_cloze_quiz(quiz, ["alpha", "alpha"])

    assert score.matched == 1
    assert score.quality == 3
