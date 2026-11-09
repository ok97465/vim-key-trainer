"""임시 기록 검증에 쓰는 숫자·명령·편집의 유효한 완료 결과를 만든다."""

# Standard library imports
from uuid import uuid4

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.commands import CommandSpec
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    CommandTiming,
    EditingSessionResult,
    SessionResult,
    SessionState,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.session_service import PracticeSession


def typing_result(
    *, seed: int = 0, mistakes: int = 0, seconds: float = 3
) -> SessionResult:
    clock = [0]
    session = PracticeSession(
        PracticeSpec(seed=seed, target_length=2), clock_ns=lambda: clock[0]
    )
    for _ in range(mistakes):
        session.submit(KeyToken("char", "a"))
    session.submit(KeyToken("char", session.target[0]))
    clock[0] = round(seconds * 1_000_000_000)
    session.submit(KeyToken("char", session.target[1]))
    assert session.result is not None
    return session.result


def command_result() -> CommandSessionResult:
    return CommandSessionResult(
        attempt_id=str(uuid4()),
        spec=CommandSpec("test_commands", seed=44),
        target=(KeyToken("char", "h"), KeyToken("chord", "ctrl+r")),
        state=SessionState.COMPLETED,
        correct=2,
        incorrect=1,
        elapsed_seconds=4,
        accuracy=200 / 3,
        cpm=30,
        max_combo=2,
        stars=1,
        errors={"h": 1},
        keypad_errors=0,
        pause_count=1,
        reaction_times=(("h", 0.2),),
        lesson_signature="command-condition",
        item_ids=("one",),
        display_count=10,
        completed_commands=1,
        command_times=(("one", 4.0),),
        commands_per_minute=15,
        transcript_digest="digest",
        command_samples=(CommandTiming("one", "h<C-r>", 4.0),),
    )


def editing_result() -> EditingSessionResult:
    session = EditingSession(get_edit_lesson("editing_numbers"))
    for step in session.lesson.guide:
        for key in step.keys:
            session.submit(key)
    assert session.result is not None
    return session.result
