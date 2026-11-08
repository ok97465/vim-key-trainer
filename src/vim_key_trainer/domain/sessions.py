"""세션 상태, 입력 판정, 최종 결과."""

# Standard library imports
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

# Local imports
from vim_key_trainer.domain.activities import ActivitySpec, BonusObjectiveResult
from vim_key_trainer.domain.challenge import ChallengeSummary
from vim_key_trainer.domain.commands import CommandSpec
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.game_rules import objective_bonus_points
from vim_key_trainer.domain.keys import KeyToken


class SessionState(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


class InputResult(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class SessionResult:
    attempt_id: str
    spec: PracticeSpec
    target: str
    state: SessionState
    correct: int
    incorrect: int
    elapsed_seconds: float
    accuracy: float | None
    cpm: float | None
    max_combo: int
    stars: int
    errors: Mapping[str, int]
    keypad_errors: int
    pause_count: int
    reaction_times: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class CommandTiming:
    item_id: str
    display: str
    seconds: float


@dataclass(frozen=True, slots=True)
class CommandSessionResult:
    attempt_id: str
    spec: CommandSpec
    target: tuple[KeyToken, ...]
    state: SessionState
    correct: int
    incorrect: int
    elapsed_seconds: float
    accuracy: float | None
    cpm: float | None
    max_combo: int
    stars: int
    errors: Mapping[str, int]
    keypad_errors: int
    pause_count: int
    reaction_times: tuple[tuple[str, float], ...]
    lesson_signature: str
    item_ids: tuple[str, ...]
    display_count: int
    completed_commands: int
    command_times: tuple[tuple[str, float], ...]
    commands_per_minute: float | None
    transcript_digest: str = ""
    command_samples: tuple[CommandTiming, ...] = ()


@dataclass(frozen=True, slots=True)
class EditingSessionResult:
    attempt_id: str
    lesson_id: str
    lesson_signature: str
    mode: EditMode
    state: SessionState
    key_count: int
    baseline_keys: int
    elapsed_seconds: float
    correct: int | None
    incorrect: int | None
    accuracy: float | None
    max_combo: int | None
    stars: int
    extra_hints: int
    step_returns: int
    pause_count: int
    guide_level: str
    practice_spec: EditPracticeSpec | None = None
    document_spec: DocumentPracticeSpec | None = None
    challenge: ChallengeSummary | None = None
    activity: ActivitySpec | None = None
    bonus_objectives: tuple[BonusObjectiveResult, ...] = ()
    code_source_id: str | None = None

    @property
    def bonus_points(self) -> int:
        """선택 목표는 기본 정답·별과 별개이며 전체 완료에만 보상을 준다."""
        return objective_bonus_points(
            objectives=self.bonus_objectives,
            completion_eligible=self.completion_eligible,
        )

    @property
    def completion_eligible(self) -> bool:
        """자동 복구·부분 실패·복수전은 문서 전체 완료 보상을 만들지 않는다."""
        return self.state == SessionState.COMPLETED and (
            self.challenge is None
            or (self.challenge.full_clear and self.challenge.revenge_of is None)
        )

    @property
    def efficiency_eligible(self) -> bool:
        """시스템이 만든 문서 변경은 사용자 입력 효율·속도 기록에서 제외한다."""
        return self.challenge is None or (
            self.challenge.full_clear
            and not self.challenge.timeout_count
            and not self.challenge.auto_repair_count
            and self.challenge.revenge_of is None
        )

    @property
    def delta(self) -> int:
        return self.key_count - self.baseline_keys


StoredResult = SessionResult | CommandSessionResult | EditingSessionResult
