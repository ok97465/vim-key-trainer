"""세션 상태, 입력 판정, 최종 결과."""

# Standard library imports
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

# Local imports
from vim_key_trainer.domain.commands import CommandSpec
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.game_rules import GAME_RULES_VERSION
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
    game_rules_version: int = GAME_RULES_VERSION


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
    lesson_version: int
    lesson_signature: str
    item_ids: tuple[str, ...]
    display_count: int
    completed_commands: int
    command_times: tuple[tuple[str, float], ...]
    commands_per_minute: float | None
    game_rules_version: int = GAME_RULES_VERSION
    generator_version: int = 0
    transcript_digest: str = ""
    command_samples: tuple[CommandTiming, ...] = ()


@dataclass(frozen=True, slots=True)
class EditingSessionResult:
    attempt_id: str
    lesson_id: str
    content_version: int
    lesson_signature: str
    baseline_version: int
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
    game_rules_version: int = GAME_RULES_VERSION
    practice_spec: EditPracticeSpec | None = None
    generator_version: int = 0
    document_spec: DocumentPracticeSpec | None = None

    @property
    def delta(self) -> int:
        return self.key_count - self.baseline_keys


StoredResult = SessionResult | CommandSessionResult | EditingSessionResult
