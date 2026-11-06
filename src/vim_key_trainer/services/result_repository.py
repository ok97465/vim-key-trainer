"""현재 실행 중에만 기록을 유지하는 메모리 저장소."""

# Local imports
from vim_key_trainer.domain.game_rules import GAME_RULES_VERSION
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    SessionState,
    StoredResult,
)

ComparisonKey = tuple[object, ...]


def _comparison_key(result: StoredResult) -> ComparisonKey:
    if isinstance(result, CommandSessionResult):
        return (
            "commands",
            result.spec.lesson_id,
            result.spec.seed,
            result.lesson_version,
            result.lesson_signature,
            result.item_ids,
            result.display_count,
            result.target,
            result.generator_version,
            result.completed_commands,
            result.transcript_digest,
            result.pause_count > 0,
            result.game_rules_version,
        )
    spec = result.spec
    return (
        "symbols",
        spec.exercise_id,
        spec.seed,
        spec.target_length,
        spec.display_width,
        result.target,
        result.pause_count > 0,
        result.game_rules_version,
    )


def _is_better(candidate: StoredResult, previous: StoredResult) -> bool:
    # 완료 시도끼리 비교하므로 correct는 양수다. 반올림 전 정수 비율로 비교한다.
    candidate_ratio = candidate.correct * (previous.correct + previous.incorrect)
    previous_ratio = previous.correct * (candidate.correct + candidate.incorrect)
    if candidate_ratio != previous_ratio:
        return candidate_ratio > previous_ratio
    return candidate.elapsed_seconds > 0 and (
        previous.elapsed_seconds <= 0
        or candidate.elapsed_seconds < previous.elapsed_seconds
    )


class MemoryResultRepository:
    def __init__(self) -> None:
        self._results: dict[str, StoredResult] = {}
        self._bests: dict[ComparisonKey, StoredResult] = {}
        self._stars: dict[tuple[str, int], int] = {}
        self._command_stars: dict[tuple[str, int, int], int] = {}

    @property
    def results(self) -> tuple[StoredResult, ...]:
        return tuple(self._results.values())

    @property
    def completed_count(self) -> int:
        return sum(
            result.state == SessionState.COMPLETED for result in self._results.values()
        )

    def best_stars(
        self, exercise_id: str, game_rules_version: int = GAME_RULES_VERSION
    ) -> int:
        return self._stars.get((exercise_id, game_rules_version), 0)

    def best_command_stars(
        self,
        lesson_id: str,
        content_version: int,
        game_rules_version: int = GAME_RULES_VERSION,
    ) -> int:
        return self._command_stars.get(
            (lesson_id, content_version, game_rules_version), 0
        )

    def best_for(self, result: StoredResult) -> StoredResult | None:
        return self._bests.get(_comparison_key(result))

    def save(self, result: StoredResult) -> bool:
        if result.attempt_id in self._results:
            return False
        self._results[result.attempt_id] = result
        if result.state != SessionState.COMPLETED:
            return False
        if isinstance(result, CommandSessionResult):
            star_key = (
                result.spec.lesson_id,
                result.lesson_version,
                result.game_rules_version,
            )
            self._command_stars[star_key] = max(
                self.best_command_stars(*star_key), result.stars
            )
        else:
            symbol_star_key = (result.spec.exercise_id, result.game_rules_version)
            self._stars[symbol_star_key] = max(
                self.best_stars(*symbol_star_key), result.stars
            )
        key = _comparison_key(result)
        previous = self._bests.get(key)
        if previous is None or _is_better(result, previous):
            self._bests[key] = result
            return True
        return False
