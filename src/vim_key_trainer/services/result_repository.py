"""저장소 공통 계약과 Qt에 독립적인 기록 비교·메모리 캐시."""

# Standard library imports
from typing import Protocol

# Local imports
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    EditingSessionResult,
    SessionState,
    StoredResult,
)
from vim_key_trainer.services.result_codec import decode_result, encode_result
from vim_key_trainer.services.result_comparison import (
    ComparisonKey,
    comparison_key,
    is_better_result,
)


class ResultRepository(Protocol):
    @property
    def results(self) -> tuple[StoredResult, ...]: ...

    @property
    def completed_count(self) -> int: ...

    @property
    def persistence_error(self) -> str | None: ...

    def save(self, result: StoredResult) -> bool: ...

    def retry_pending(self) -> int: ...

    def best_for(self, result: StoredResult) -> StoredResult | None: ...

    def best_stars(self, exercise_id: str) -> int: ...

    def best_command_stars(self, lesson_id: str) -> int: ...

    def best_edit_stars(
        self, lesson_id: str, mode: EditMode, guide_level: str | None = None
    ) -> int: ...


class MemoryResultRepository:
    def __init__(self) -> None:
        self._results: dict[str, StoredResult] = {}
        self._bests: dict[ComparisonKey, StoredResult] = {}
        self._stars: dict[str, int] = {}
        self._command_stars: dict[str, int] = {}
        self._edit_stars: dict[tuple[str, EditMode, str], int] = {}
        self._completed_count = 0

    @property
    def persistence_error(self) -> str | None:
        return None

    def retry_pending(self) -> int:
        return 0

    @property
    def results(self) -> tuple[StoredResult, ...]:
        return tuple(self._results.values())

    @property
    def completed_count(self) -> int:
        return self._completed_count

    def best_stars(self, exercise_id: str) -> int:
        return self._stars.get(exercise_id, 0)

    def best_command_stars(self, lesson_id: str) -> int:
        return self._command_stars.get(lesson_id, 0)

    def best_for(self, result: StoredResult) -> StoredResult | None:
        return self._bests.get(comparison_key(result))

    def best_edit_stars(
        self, lesson_id: str, mode: EditMode, guide_level: str | None = None
    ) -> int:
        level = guide_level or ("step" if mode == "guided" else "none")
        return self._edit_stars.get((lesson_id, mode, level), 0)

    def save(self, result: StoredResult) -> bool:
        if result.attempt_id in self._results:
            return False
        result = decode_result(encode_result(result))
        return self._record_result(result)

    def _record_result(self, result: StoredResult) -> bool:
        """검증한 결과를 한 번만 메모리 진행도와 개인 기록에 반영한다."""
        self._results[result.attempt_id] = result
        if result.state != SessionState.COMPLETED:
            return False
        self._completed_count += 1
        if isinstance(result, EditingSessionResult):
            edit_star_key = (
                result.lesson_id,
                result.mode,
                result.guide_level,
            )
            self._edit_stars[edit_star_key] = max(
                self.best_edit_stars(*edit_star_key), result.stars
            )
        elif isinstance(result, CommandSessionResult):
            lesson_id = result.spec.lesson_id
            self._command_stars[lesson_id] = max(
                self.best_command_stars(lesson_id), result.stars
            )
        else:
            exercise_id = result.spec.exercise_id
            self._stars[exercise_id] = max(self.best_stars(exercise_id), result.stars)
        key = comparison_key(result)
        previous = self._bests.get(key)
        if previous is None or is_better_result(result, previous):
            self._bests[key] = result
            return True
        return False
