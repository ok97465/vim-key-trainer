"""입력 통계와 별을 분리해 계산하는 순수 함수."""

GAME_RULES_VERSION = 1


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
