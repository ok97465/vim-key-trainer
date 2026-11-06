"""현재 실행 중에만 기록을 유지하는 메모리 저장소."""

# Local imports
from vim_key_trainer.domain.sessions import SessionResult, SessionState

ComparisonKey = tuple[str, int, int, int, str, bool, int]


def _comparison_key(result: SessionResult) -> ComparisonKey:
    spec = result.spec
    return (
        spec.exercise_id,
        spec.seed,
        spec.target_length,
        spec.display_width,
        result.target,
        result.pause_count > 0,
        result.game_rules_version,
    )


def _is_better(candidate: SessionResult, previous: SessionResult) -> bool:
    # 완료 시도끼리 비교하므로 correct는 양수다. 반올림 전 정수 비율로 비교한다.
    candidate_ratio = candidate.correct * (previous.correct + previous.incorrect)
    previous_ratio = previous.correct * (candidate.correct + candidate.incorrect)
    if candidate_ratio != previous_ratio:
        return candidate_ratio > previous_ratio
    return (
        candidate.elapsed_seconds > 0
        and previous.elapsed_seconds > 0
        and candidate.elapsed_seconds < previous.elapsed_seconds
    )


class MemoryResultRepository:
    def __init__(self) -> None:
        self._results: dict[str, SessionResult] = {}
        self._bests: dict[ComparisonKey, SessionResult] = {}
        self._stars: dict[str, int] = {}

    @property
    def results(self) -> tuple[SessionResult, ...]:
        return tuple(self._results.values())

    @property
    def completed_count(self) -> int:
        return sum(
            result.state == SessionState.COMPLETED for result in self._results.values()
        )

    def best_stars(self, exercise_id: str) -> int:
        return self._stars.get(exercise_id, 0)

    def best_for(self, result: SessionResult) -> SessionResult | None:
        return self._bests.get(_comparison_key(result))

    def save(self, result: SessionResult) -> bool:
        if result.attempt_id in self._results:
            return False
        self._results[result.attempt_id] = result
        if result.state != SessionState.COMPLETED:
            return False
        exercise_id = result.spec.exercise_id
        self._stars[exercise_id] = max(self.best_stars(exercise_id), result.stars)
        key = _comparison_key(result)
        previous = self._bests.get(key)
        if previous is None or _is_better(result, previous):
            self._bests[key] = result
            return True
        return False
