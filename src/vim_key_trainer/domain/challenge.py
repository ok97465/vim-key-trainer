"""시간 도전의 불변 조건·시간 규칙·집계. Qt와 실제 시간원에 의존하지 않는다."""

from __future__ import annotations

# Standard library imports
from dataclasses import dataclass
from typing import Literal

# Local imports
from vim_key_trainer.domain.editing import EditLesson, EditMode, EditSegment
from vim_key_trainer.domain.keys import KeyToken

ChallengeKind = Literal["normal", "bomb"]
ChallengeDifficulty = Literal["relaxed", "normal", "challenge"]
SegmentVerdict = Literal["direct", "timeout", "pending"]
TIME_RULE_VERSION = 1


@dataclass(frozen=True, slots=True)
class ChallengeOptions:
    kind: ChallengeKind = "normal"
    difficulty: ChallengeDifficulty = "normal"
    auto_repair: bool = True

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"normal", "bomb"}:
            raise ValueError("지원하지 않는 도전 종류입니다.")
        if type(self.difficulty) is not str or self.difficulty not in {
            "relaxed",
            "normal",
            "challenge",
        }:
            raise ValueError("지원하지 않는 시간 난이도입니다.")
        if type(self.auto_repair) is not bool:
            raise ValueError("자동 수정 여부는 참/거짓이어야 합니다.")


@dataclass(frozen=True, slots=True)
class TimeRules:
    """정수 밀리초로 계산 후 0.1초 단위 올림. 사용자 입력은 계산에 쓰지 않는다."""

    version: int = TIME_RULE_VERSION
    thinking_ms: int = 4000
    per_key_ms: int = 650
    per_row_ms: int = 120
    maximum_row_allowance_ms: int = 8000
    per_search_ms: int = 1800
    minimum_ms: int = 6000
    maximum_ms: int = 90000
    free_maximum_ms: int = 900000
    rounding_ms: int = 100
    difficulty_percent: tuple[tuple[ChallengeDifficulty, int], ...] = (
        ("relaxed", 150),
        ("normal", 100),
        ("challenge", 75),
    )

    def __post_init__(self) -> None:
        values = (
            self.version,
            self.thinking_ms,
            self.per_key_ms,
            self.per_row_ms,
            self.maximum_row_allowance_ms,
            self.per_search_ms,
            self.minimum_ms,
            self.maximum_ms,
            self.free_maximum_ms,
            self.rounding_ms,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("시간 규칙은 양의 정수 밀리초여야 합니다.")
        if self.minimum_ms > self.maximum_ms or self.maximum_ms > self.free_maximum_ms:
            raise ValueError("최소·최대 제한시간 순서가 잘못되었습니다.")
        factors = dict(self.difficulty_percent)
        if set(factors) != {"relaxed", "normal", "challenge"} or any(
            type(value) is not int or value <= 0 for value in factors.values()
        ):
            raise ValueError("난이도 배수가 올바르지 않습니다.")

    def limit_seconds(
        self,
        *,
        key_count: int,
        row_distance: int,
        search_count: int,
        difficulty: ChallengeDifficulty,
        whole_document: bool = False,
    ) -> float:
        if any(
            type(value) is not int or value < 0
            for value in (key_count, row_distance, search_count)
        ) or difficulty not in dict(self.difficulty_percent):
            raise ValueError("시간 산정 입력이 올바르지 않습니다.")
        exploration = (
            min(self.maximum_row_allowance_ms, row_distance * self.per_row_ms)
            + min(search_count, 3) * self.per_search_ms
        )
        raw = self.thinking_ms + key_count * self.per_key_ms + exploration
        # 배수 적용 후 정수 0.1초 단위로 올림한다.
        numerator = raw * dict(self.difficulty_percent)[difficulty]
        unit = self.rounding_ms * 100
        rounded = ((numerator + unit - 1) // unit) * self.rounding_ms
        maximum = self.free_maximum_ms if whole_document else self.maximum_ms
        return min(maximum, max(self.minimum_ms, rounded)) / 1000


TIME_RULES = TimeRules()


@dataclass(frozen=True, slots=True)
class SegmentResult:
    segment_id: str
    verdict: SegmentVerdict
    elapsed_seconds: float
    limit_seconds: float
    auto_repaired: bool = False


@dataclass(frozen=True, slots=True)
class ChallengeSummary:
    options: ChallengeOptions
    time_rule_version: int
    segments: tuple[SegmentResult, ...]
    full_clear: bool
    score: int
    max_chain: int = 0
    revenge_of: str | None = None

    @property
    def direct_count(self) -> int:
        return sum(segment.verdict == "direct" for segment in self.segments)

    @property
    def timeout_count(self) -> int:
        return sum(segment.verdict == "timeout" for segment in self.segments)

    @property
    def auto_repair_count(self) -> int:
        return sum(segment.auto_repaired for segment in self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)


@dataclass(frozen=True, slots=True)
class TimerGuard:
    attempt_id: str
    segment_id: str
    generation: int


@dataclass(frozen=True, slots=True)
class RecoveryMark:
    segment_id: str
    row: int
    text: str = "시간 초과 · 자동 복구"


@dataclass(frozen=True, slots=True)
class SuccessMark:
    segment_id: str
    row: int
    text: str = "직접 해체 완료"


@dataclass(frozen=True, slots=True)
class FailureExample:
    segment_id: str
    before_lines: tuple[str, ...]
    goal_lines: tuple[str, ...]
    guide_keys: tuple[KeyToken, ...]


def bomb_unavailable_reason(
    lesson: EditLesson, mode: EditMode = "guided"
) -> str | None:
    if lesson.initial.lines == lesson.goal_lines or not lesson.free_enabled:
        return "실행 취소처럼 시작과 목표가 같은 과제는 폭탄 도전을 지원하지 않습니다."
    if not lesson.guide:
        return "검증된 기준 풀이가 없어 폭탄 도전을 지원하지 않습니다."
    return None


def challenge_segments(lesson: EditLesson, mode: EditMode) -> tuple[EditSegment, ...]:
    """고정 입문 과제는 전체 가이드를 하나로 묶고 생성 과제는 레시피 단위를 쓴다."""
    if mode == "free" or not lesson.segments:
        return (
            EditSegment(
                id="document",
                start_step=0,
                end_step=len(lesson.guide),
                target_start_row=0,
                target_end_row=len(lesson.goal_lines),
            ),
        )
    return lesson.segments
