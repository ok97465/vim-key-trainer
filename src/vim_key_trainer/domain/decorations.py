"""저장된 성취에서 꾸미기를 계산한다. 반복·재저장으로 보상을 쌓지 않는다."""

# Standard library imports
from collections.abc import Iterable
from dataclasses import dataclass

# Local imports
from vim_key_trainer.domain.preferences import AppearanceSettings
from vim_key_trainer.domain.sessions import EditingSessionResult, StoredResult

DECORATION_RULE_VERSION = 2
_REQUIRED_COMPLETIONS = {
    ("mascot", "classic"): 0,
    ("mascot", "cat"): 3,
    ("fuse", "mint"): 0,
    ("fuse", "peach"): 1,
    ("fuse", "lilac"): 3,
    ("stamp", "check"): 0,
    ("stamp", "star"): 3,
    ("stamp", "flower"): 6,
}


@dataclass(frozen=True, slots=True)
class DecorationProgress:
    completed_lessons: int
    direct_repairs: int

    def allows(self, category: str, choice: str) -> bool:
        required = _REQUIRED_COMPLETIONS.get((category, choice))
        return required is not None and self.completed_lessons >= required

    def effective(self, settings: AppearanceSettings) -> AppearanceSettings:
        return AppearanceSettings(
            mascot=settings.mascot
            if self.allows("mascot", settings.mascot)
            else "classic",
            fuse=settings.fuse if self.allows("fuse", settings.fuse) else "mint",
            stamp=settings.stamp if self.allows("stamp", settings.stamp) else "check",
            decorations=settings.decorations,
        )


def summarize_decorations(results: Iterable[StoredResult]) -> DecorationProgress:
    """같은 레슨·원문에서 가장 큰 직접 성공 수만 보존한다."""
    lessons: dict[tuple[str, str | None], int] = {}
    attempts: set[str] = set()
    for result in results:
        if (
            not isinstance(result, EditingSessionResult)
            or not result.completion_eligible
            or result.attempt_id in attempts
        ):
            continue
        attempts.add(result.attempt_id)
        count = result.challenge.direct_count if result.challenge is not None else 0
        key = result.lesson_id, result.code_source_id
        lessons[key] = max(lessons.get(key, 0), count)
    return DecorationProgress(len(lessons), sum(lessons.values()))
