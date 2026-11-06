"""세션 상태, 입력 판정, 최종 결과."""

# Standard library imports
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

# Local imports
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.game_rules import GAME_RULES_VERSION


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
