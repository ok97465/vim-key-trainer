"""저장소 공통 계약과 Qt에 독립적인 기록 비교·메모리 캐시."""

# Standard library imports
from typing import Protocol

# Local imports
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.game_rules import GAME_RULES_VERSION
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

    def best_stars(
        self, exercise_id: str, game_rules_version: int = GAME_RULES_VERSION
    ) -> int: ...

    def best_command_stars(
        self,
        lesson_id: str,
        content_version: int,
        game_rules_version: int = GAME_RULES_VERSION,
    ) -> int: ...

    def best_edit_stars(
        self,
        lesson_id: str,
        content_version: int,
        mode: EditMode,
        guide_level: str | None = None,
        game_rules_version: int = GAME_RULES_VERSION,
    ) -> int: ...


class MemoryResultRepository:
    def __init__(self) -> None:
        self._results: dict[str, StoredResult] = {}
        self._bests: dict[ComparisonKey, StoredResult] = {}
        self._stars: dict[tuple[str, int], int] = {}
        self._command_stars: dict[tuple[str, int, int], int] = {}
        self._edit_stars: dict[tuple[str, int, EditMode, str, int], int] = {}
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
        return self._bests.get(comparison_key(result))

    def best_edit_stars(
        self,
        lesson_id: str,
        content_version: int,
        mode: EditMode,
        guide_level: str | None = None,
        game_rules_version: int = GAME_RULES_VERSION,
    ) -> int:
        level = guide_level or ("step" if mode == "guided" else "none")
        return self._edit_stars.get(
            (lesson_id, content_version, mode, level, game_rules_version), 0
        )

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
                result.content_version,
                result.mode,
                result.guide_level,
                result.game_rules_version,
            )
            self._edit_stars[edit_star_key] = max(
                self.best_edit_stars(*edit_star_key), result.stars
            )
        elif isinstance(result, CommandSessionResult):
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
        key = comparison_key(result)
        previous = self._bests.get(key)
        if previous is None or is_better_result(result, previous):
            self._bests[key] = result
            return True
        return False
