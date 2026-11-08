"""입력 통계와 별을 분리해 계산하는 순수 함수."""

# Standard library imports
from collections.abc import Iterable

# Local imports
from vim_key_trainer.domain.activities import BONUS_POINTS, BonusObjectiveResult
from vim_key_trainer.domain.challenge import SegmentResult

BOMB_BASE_SCORE = 1000
BOMB_TIME_BONUS = 500


def objective_bonus_points(
    *, objectives: Iterable[BonusObjectiveResult], completion_eligible: bool
) -> int:
    """선택 목표 보너스는 기본 별·폭탄 점수와 별도로 표시한다."""
    if not completion_eligible:
        return 0
    return sum(BONUS_POINTS[goal.id] for goal in objectives if goal.achieved)


def bomb_segment_score(
    *,
    verdict: str,
    elapsed_seconds: float,
    limit_seconds: float,
    extra_hints: int = 0,
    step_returns: int = 0,
) -> int:
    """직접 해체 기본점과 남은 시간 보너스를 계산한다. 실패는 0점이다."""
    if verdict != "direct":
        return 0
    if extra_hints or step_returns:
        return BOMB_BASE_SCORE
    # 시간원의 정수 ns로 되돌려 90% 경과 때 부동소수점 오차로 1점이
    # 빠지지 않게 한다. 제한시간 규칙의 ms와 원래 시간원은 모두 ns 정수다.
    limit_ns = round(limit_seconds * 1_000_000_000)
    remaining_ns = max(
        0, min(limit_ns, limit_ns - round(elapsed_seconds * 1_000_000_000))
    )
    return BOMB_BASE_SCORE + BOMB_TIME_BONUS * remaining_ns // limit_ns


def bomb_score(
    *,
    segments: Iterable[SegmentResult],
    extra_hints: int = 0,
    step_returns: int = 0,
) -> int:
    """구간별 보상은 결과에서 한 번 합산하며 복습은 추가 점수를 주지 않는다."""
    return sum(
        bomb_segment_score(
            verdict=segment.verdict,
            elapsed_seconds=segment.elapsed_seconds,
            limit_seconds=segment.limit_seconds,
            extra_hints=extra_hints,
            step_returns=step_returns,
        )
        for segment in segments
    )


def typing_stars(
    *,
    completed: bool,
    correct: int,
    incorrect: int,
    extra_hints: int = 0,
    step_returns: int = 0,
) -> int:
    if not completed:
        return 0
    if correct == 0 or step_returns:
        return 1
    if incorrect == 0 and extra_hints == 0:
        return 3
    # 정수 비율로 판정해 화면 표시의 반올림이 별의 경계를 바꾸지 않게 한다.
    if correct * 100 >= (correct + incorrect) * 95:
        return 2
    return 1


def editing_stars(
    *,
    completed: bool,
    key_count: int,
    baseline_keys: int,
    extra_hints: int = 0,
    step_returns: int = 0,
) -> int:
    """자유 풀이에는 타이핑 정확도 대신 검증한 기준 입력 수를 사용한다."""
    if not completed:
        return 0
    if key_count > baseline_keys:
        return 1
    if extra_hints or step_returns:
        return 2
    return 3
