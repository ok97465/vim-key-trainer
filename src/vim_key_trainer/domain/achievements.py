"""미션 완료 결과에서 수집 진행도와 배지를 계산하는 순수 함수.

한 미션의 최고 별만 더하므로 같은 문제를 반복하거나 시도를 재저장해도
수집 보상이 중복되지 않는다. 속도 경쟁 없이 여러 풀이 방식을 장려한다.
"""

# Standard library imports
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# Local imports
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    SessionState,
    StoredResult,
)


@dataclass(frozen=True, slots=True)
class Badge:
    id: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class LearningSummary:
    total_missions: int
    completed_missions: int
    mastery_missions: int
    total_stars: int
    completed_ids: frozenset[str]
    badges: tuple[Badge, ...]


def summarize_learning(
    results: Iterable[StoredResult],
    mission_ids: Iterable[str],
    content_versions: Mapping[str, int] | None = None,
) -> LearningSummary:
    """현재 카탈로그의 버전에 해당하는 완료 미션만 수집 진행도에 반영한다."""
    available = frozenset(mission_ids)
    attempts: dict[str, EditingSessionResult] = {}
    for result in results:
        if (
            isinstance(result, EditingSessionResult)
            and result.state == SessionState.COMPLETED
            and result.lesson_id in available
            and (
                content_versions is None
                or content_versions.get(result.lesson_id) == result.content_version
            )
        ):
            attempts.setdefault(result.attempt_id, result)
    best_stars: dict[str, int] = {}
    for result in attempts.values():
        best_stars[result.lesson_id] = max(
            best_stars.get(result.lesson_id, 0), result.stars
        )
    completed = frozenset(best_stars)
    mastered = sum(stars == 3 for stars in best_stars.values())
    badges: list[Badge] = []
    milestones = (
        (1, "first_repair", "첫 복구", "실제 문서 미션 하나를 완성했어요."),
        (3, "three_documents", "문서 탐험가", "서로 다른 문서 미션 3개를 복구했어요."),
        (6, "six_documents", "꼼꼼한 정비사", "서로 다른 문서 미션 6개를 복구했어요."),
        (
            12,
            "twelve_documents",
            "문서 도서관장",
            "서로 다른 문서 미션 12개를 복구했어요.",
        ),
    )
    for required, badge_id, title, description in milestones:
        if len(completed) >= required:
            badges.append(Badge(badge_id, title, description))
    if available and len(available) >= 3 and completed == available:
        badges.append(
            Badge(
                "collection_complete",
                "컬렉션 완성",
                "이 문서 모음의 미션을 모두 복구했어요.",
            )
        )
    if mastered >= 3:
        badges.append(
            Badge(
                "three_masterpieces",
                "별빛 수집가",
                "서로 다른 미션 3개에서 별 3개를 모았어요.",
            )
        )
    if any(
        result.mode == "guided"
        and result.incorrect == 0
        and result.extra_hints == 0
        and result.step_returns == 0
        for result in attempts.values()
    ):
        badges.append(
            Badge(
                "steady_guide",
                "정확한 길잡이",
                "가이드 미션을 오타·단계 복귀 없이 완성했어요.",
            )
        )
    if any(
        result.mode == "free"
        and result.extra_hints == 0
        and result.step_returns == 0
        and result.key_count < result.baseline_keys
        for result in attempts.values()
    ):
        badges.append(
            Badge(
                "own_shortcut",
                "나만의 지름길",
                "추가 힌트 없이 기준보다 짧은 자유 풀이를 찾았어요.",
            )
        )
    if any(
        result.mode == "free" and result.extra_hints == 0 and result.step_returns == 0
        for result in attempts.values()
    ):
        badges.append(
            Badge(
                "independent_repair",
                "스스로 복구",
                "가이드를 펼치지 않고 자유 풀이를 완성했어요.",
            )
        )
    return LearningSummary(
        total_missions=len(available),
        completed_missions=len(completed),
        mastery_missions=mastered,
        total_stars=sum(best_stars.values()),
        completed_ids=completed,
        badges=tuple(badges),
    )
