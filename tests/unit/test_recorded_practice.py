"""저장된 조건·서명으로만 복수전을 재구성하고 변조된 기록을 거부한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.services.activity_problem_factory import create_boss_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.recorded_practice import create_recorded_revenge
from vim_key_trainer.services.result_codec import decode_result, encode_result


def test_recorded_revenge_rebuilds_failed_only_without_original_memory() -> None:
    clock = [0]
    lesson = create_boss_problem(23, objectives=("all_direct",))
    original = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: clock[0]
    )
    first = lesson.segments[0]
    for step in lesson.guide[first.start_step : first.end_step]:
        for key in step.keys:
            assert original.submit(key) == InputResult.ACCEPTED
    clock[0] += 100_000_000_000
    original.check_deadline()
    while original.state != SessionState.COMPLETED:
        assert original.submit(original.expected_token) == InputResult.ACCEPTED
    result = original.result
    assert result is not None and result.challenge is not None
    saved = decode_result(encode_result(result))
    original.release_transient()
    del original
    revenge = create_recorded_revenge(saved, clock_ns=lambda: clock[0])
    assert revenge.attempt_id != result.attempt_id
    assert revenge.lesson.signature == result.lesson_signature
    assert len(revenge.segments) == 1
    assert revenge.revenge_segments == (lesson.segments[1].id,)
    assert revenge.engine.state.lines == lesson.guide[first.end_step - 1].expected.lines
    while revenge.state != SessionState.COMPLETED:
        assert revenge.submit(revenge.expected_token) == InputResult.ACCEPTED
    assert revenge.result is not None and revenge.result.stars == 0
    assert revenge.result.challenge is not None and revenge.result.challenge.full_clear
    assert saved == result


def test_recorded_revenge_rejects_altered_problem_signature() -> None:
    clock = [0]
    session = EditingSession(
        create_boss_problem(23),
        challenge=ChallengeOptions("bomb"),
        clock_ns=lambda: clock[0],
    )
    session.submit(KeyToken("char", "Q"))
    clock[0] += 100_000_000_000
    session.check_deadline()
    session.abort()
    assert session.result is not None
    tampered = replace(session.result, lesson_signature="0" * 64)
    with pytest.raises(ValueError, match="문제 서명"):
        create_recorded_revenge(tampered)
