"""SM-2 间隔重复算法单元测试。"""

from datetime import UTC, datetime, timedelta

from packages.memory.spaced_repetition import (
    ReviewResult,
    calculate_mastery_level,
    get_initial_schedule,
    sm2_algorithm,
)


class TestSM2Algorithm:
    """sm2_algorithm 函数测试。"""

    def test_quality_below_3_resets_progress(self):
        """quality 0-2 应将 repetitions 重置为 0、interval 重置为 1。"""
        for quality in [0, 1, 2]:
            result = sm2_algorithm(
                ease_factor=2.5,
                interval_days=10,
                repetitions=5,
                quality=quality,
            )
            assert result.repetitions == 0
            assert result.interval_days == 1

    def test_quality_3_increments_repetitions(self):
        """quality 3 应递增 repetitions。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=3,
        )
        assert result.repetitions == 4

    def test_quality_4_increments_repetitions(self):
        """quality 4 应递增 repetitions。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=4,
        )
        assert result.repetitions == 4

    def test_quality_5_increments_repetitions(self):
        """quality 5 应递增 repetitions。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=5,
        )
        assert result.repetitions == 4

    def test_first_review_interval_is_1(self):
        """首次成功复习（repetitions=0）应将 interval 设为 1。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=1,
            repetitions=0,
            quality=4,
        )
        assert result.interval_days == 1

    def test_second_review_interval_is_6(self):
        """第二次成功复习（repetitions=1）应将 interval 设为 6。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=1,
            repetitions=1,
            quality=4,
        )
        assert result.interval_days == 6

    def test_third_review_interval_grows_by_ease_factor(self):
        """第三次及以后应将 interval 乘以 ease factor。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=6,
            repetitions=2,
            quality=4,
        )
        # 6 * 2.5 = 15
        assert result.interval_days == 15

    def test_ease_factor_decreases_with_low_quality(self):
        """低质量评分应降低 ease factor。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=3,
        )
        # EF' = 2.5 + (0.1 - (5-3) * (0.08 + (5-3) * 0.02))
        # = 2.5 + (0.1 - 2 * 0.12)
        # = 2.5 + (0.1 - 0.24)
        # = 2.5 - 0.14
        # = 2.36
        assert result.ease_factor == 2.36

    def test_ease_factor_increases_with_high_quality(self):
        """高质量评分应提升 ease factor。"""
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=5,
        )
        # EF' = 2.5 + (0.1 - (5-5) * (0.08 + (5-5) * 0.02))
        # = 2.5 + 0.1
        # = 2.6
        assert result.ease_factor == 2.6

    def test_ease_factor_has_minimum_of_1_3(self):
        """ease factor 永不低于 1.3。"""
        # 连续施加大量低质量复习
        ef = 2.5
        for _ in range(20):
            result = sm2_algorithm(
                ease_factor=ef,
                interval_days=5,
                repetitions=3,
                quality=0,
            )
            ef = result.ease_factor
        assert ef >= 1.3

    def test_quality_is_clamped_to_valid_range(self):
        """quality 超出 0-5 时应被钳制。"""
        result_low = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=-5,
        )
        assert result_low.repetitions == 0  # 按 quality 0 处理

        result_high = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=10,
        )
        assert result_high.repetitions == 4  # 按 quality 5 处理

    def test_next_review_is_calculated_correctly(self):
        """next_review 应等于 review_time + interval_days。"""
        review_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=6,
            repetitions=2,
            quality=4,
            review_time=review_time,
        )
        expected = review_time + timedelta(days=result.interval_days)
        assert result.next_review == expected

    def test_review_time_defaults_to_now(self):
        """未提供 review_time 时应默认取当前时间。"""
        before = datetime.now(UTC)
        result = sm2_algorithm(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            quality=4,
        )
        after = datetime.now(UTC)
        # next_review 应约等于 now + interval（5 * 2.5 = 12 天）
        assert before + timedelta(days=12) <= result.next_review <= after + timedelta(days=12)


class TestGetInitialSchedule:
    """get_initial_schedule 函数测试。"""

    def test_default_values(self):
        """初始排期应有 SM-2 默认值。"""
        result = get_initial_schedule()
        assert result.ease_factor == 2.5
        assert result.interval_days == 1
        assert result.repetitions == 0

    def test_next_review_defaults_to_first_review_time(self):
        """初始排期的 next_review 应等于 first_review_time。"""
        review_time = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)
        result = get_initial_schedule(review_time)
        assert result.next_review == review_time

    def test_first_review_time_defaults_to_now(self):
        """first_review_time 应默认取当前时间。"""
        before = datetime.now(UTC)
        result = get_initial_schedule()
        after = datetime.now(UTC)
        assert before <= result.next_review <= after


class TestCalculateMasteryLevel:
    """calculate_mastery_level 函数测试。"""

    def test_new_level(self):
        """0 次 repetitions 应为 'new'。"""
        assert calculate_mastery_level(0, 2.5) == "new"

    def test_learning_level(self):
        """1-2 次 repetitions 应为 'learning'。"""
        assert calculate_mastery_level(1, 2.5) == "learning"
        assert calculate_mastery_level(2, 2.5) == "learning"

    def test_familiar_level(self):
        """3-5 次 repetitions 应为 'familiar'。"""
        assert calculate_mastery_level(3, 2.5) == "familiar"
        assert calculate_mastery_level(4, 2.5) == "familiar"
        assert calculate_mastery_level(5, 2.5) == "familiar"

    def test_proficient_level_by_repetitions(self):
        """6-10 次 repetitions 应为 'proficient'（无论 EF 多少）。"""
        assert calculate_mastery_level(6, 2.5) == "proficient"
        assert calculate_mastery_level(10, 2.5) == "proficient"
        assert calculate_mastery_level(8, 1.5) == "proficient"  # 低 EF

    def test_mastered_level(self):
        """10+ 次 repetitions 且 EF >= 2.5 应为 'mastered'。"""
        assert calculate_mastery_level(11, 2.5) == "mastered"
        assert calculate_mastery_level(20, 3.0) == "mastered"

    def test_proficient_when_high_reps_but_low_ef(self):
        """10+ 次 repetitions 但 EF < 2.5 应为 'proficient' 而非 'mastered'。"""
        assert calculate_mastery_level(15, 2.4) == "proficient"
        assert calculate_mastery_level(100, 1.3) == "proficient"

    def test_boundary_at_10_repetitions_with_high_ef(self):
        """恰好 10 次 repetitions 时即便 EF 很高也仍是 'proficient'。"""
        # 判定顺序：先 repetitions <= 10 归为 proficient，再按 ease_factor >= 2.5
        # 判 mastered。因此 10 次 repetitions 即使 EF 很高也会先命中
        # proficient 分支（代码中 elif 分支的先后顺序使然）。
        assert calculate_mastery_level(10, 3.0) == "proficient"

    def test_boundary_at_11_repetitions_with_high_ef(self):
        """11 次 repetitions 且 EF >= 2.5 应为 'mastered'。"""
        assert calculate_mastery_level(11, 2.5) == "mastered"


class TestReviewResult:
    """ReviewResult 数据类测试。"""

    def test_review_result_fields(self):
        """ReviewResult 应包含全部预期字段。"""
        result = ReviewResult(
            ease_factor=2.5,
            interval_days=5,
            repetitions=3,
            next_review=datetime(2024, 1, 10, tzinfo=UTC),
        )
        assert result.ease_factor == 2.5
        assert result.interval_days == 5
        assert result.repetitions == 3
        assert result.next_review == datetime(2024, 1, 10, tzinfo=UTC)
