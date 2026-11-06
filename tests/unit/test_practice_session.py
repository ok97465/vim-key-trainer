# Standard library imports
from dataclasses import dataclass

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.exercises import (
    EXERCISES,
    Exercise,
    PracticeSpec,
    generate_target,
)
from vim_key_trainer.domain.game_rules import typing_stars
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.services.session_service import PracticeSession


@dataclass
class Clock:
    seconds: float = 0

    def __call__(self) -> int:
        return round(self.seconds * 1_000_000_000)


def press(session: PracticeSession, character: str) -> InputResult:
    return session.submit(KeyToken("char", character))


@pytest.mark.parametrize("exercise", EXERCISES, ids=lambda exercise: exercise.id)
def test_all_lessons_complete_without_block_confirmation(exercise: Exercise) -> None:
    session = PracticeSession(PracticeSpec(exercise_id=exercise.id, seed=43))
    assert len(session.target) == 100
    for index, character in enumerate(session.target):
        assert press(session, character) == InputResult.ACCEPTED
        assert session.position == index + 1
    assert session.state == SessionState.COMPLETED
    assert session.result is not None
    assert session.result.correct == 100
    assert session.result.stars == 3
    assert session.result.max_combo == 100
    assert len(session.result.reaction_times) == 99
    assert session.submit(KeyToken("char", "1")) == InputResult.IGNORED
    assert session.position == 100


def test_seed_and_retry_reproduce_problem_but_get_new_attempt_ids() -> None:
    spec = PracticeSpec(seed=15)
    first = PracticeSession(spec)
    retry = PracticeSession(spec)
    assert retry.target == first.target == generate_target(spec)
    assert retry.attempt_id != first.attempt_id
    assert generate_target(PracticeSpec(seed=16)) != first.target


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_length": 0},
        {"target_length": 10_001},
        {"display_width": 0},
        {"display_width": 81},
        {"exercise_id": "unknown"},
    ],
)
def test_invalid_problem_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PracticeSpec(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "12", "한", "\n"])
def test_character_token_requires_one_printable_ascii_character(value: str) -> None:
    with pytest.raises(ValueError):
        KeyToken("char", value)


def test_ignored_input_does_not_start_timer_or_change_combo() -> None:
    clock = Clock(10)
    session = PracticeSession(PracticeSpec(target_length=2), clock_ns=clock)
    assert session.submit(None) == InputResult.IGNORED
    assert session.submit(KeyToken("special", "backspace")) == InputResult.IGNORED
    clock.seconds = 50
    assert session.state == SessionState.READY
    assert session.elapsed_seconds == 0
    assert session.accuracy is None
    assert session.cpm is None
    press(session, session.target[0])
    assert session.submit(None) == InputResult.IGNORED
    assert session.submit(KeyToken("special", "backspace")) == InputResult.IGNORED
    assert session.position == session.combo == 1
    assert session.incorrect == 0


def test_mistake_stays_on_target_and_cannot_be_erased_by_backspace() -> None:
    session = PracticeSession(PracticeSpec(target_length=3))
    press(session, session.target[0])
    press(session, "a")
    assert session.position == 1
    assert session.combo == 0
    assert session.max_combo == 1
    assert session.errors == {session.target[1]: 1}
    session.submit(KeyToken("special", "backspace"))
    assert session.incorrect == 1
    assert session.position == 1
    press(session, session.target[1])
    assert session.combo == 1
    assert session.accuracy == pytest.approx(200 / 3)
    copied_errors = session.errors
    copied_errors.clear()
    assert session.errors


def test_keypad_digit_is_a_distinct_position_error() -> None:
    clock = Clock()
    session = PracticeSession(PracticeSpec(target_length=2), clock_ns=clock)
    assert (
        session.submit(KeyToken("char", session.target[0]), keypad=True)
        == InputResult.REJECTED
    )
    assert session.state == SessionState.RUNNING
    assert session.position == 0
    assert session.keypad_errors == 1
    assert session.incorrect == 1
    assert session.errors == {}
    press(session, session.target[0])
    assert session.accuracy == 50


def test_special_key_is_one_error_and_starts_timer() -> None:
    clock = Clock(20)
    session = PracticeSession(PracticeSpec(), clock_ns=clock)
    assert session.submit(KeyToken("special", "enter")) == InputResult.REJECTED
    clock.seconds = 21.5
    assert session.elapsed_seconds == 1.5
    assert session.incorrect == 1
    assert session.accuracy == 0


def test_accuracy_and_cpm_follow_documented_example_and_freeze_at_completion() -> None:
    clock = Clock(12)
    session = PracticeSession(PracticeSpec(seed=7), clock_ns=clock)
    for _ in range(10):
        press(session, "a")
    for index, character in enumerate(session.target):
        clock.seconds = 12 + (index + 1) * 0.6
        press(session, character)
    clock.seconds = 500
    assert session.elapsed_seconds == 60
    assert session.accuracy == pytest.approx(1000 / 11)
    assert session.cpm == 100
    assert session.result is not None
    assert session.result.elapsed_seconds == 60
    assert session.result.stars == 1


def test_zero_elapsed_time_does_not_invent_speed() -> None:
    session = PracticeSession(PracticeSpec(target_length=1), clock_ns=Clock())
    press(session, session.target[0])
    assert session.result is not None
    assert session.result.cpm is None
    assert session.result.accuracy == 100


def test_pause_excludes_time_and_preserves_combo_and_reaction_time() -> None:
    clock = Clock(100)
    session = PracticeSession(PracticeSpec(target_length=2), clock_ns=clock)
    press(session, session.target[0])
    clock.seconds = 102
    session.pause()
    session.pause()
    assert session.pause_count == 1
    clock.seconds = 200
    assert session.elapsed_seconds == 2
    assert press(session, session.target[1]) == InputResult.IGNORED
    assert session.position == session.combo == 1
    session.resume()
    clock.seconds = 203
    press(session, session.target[1])
    assert session.result is not None
    assert session.result.elapsed_seconds == 5
    assert session.result.reaction_times == ((session.target[1], 5),)
    assert session.result.max_combo == 2


def test_pause_before_first_input_resumes_to_ready_without_starting_timer() -> None:
    clock = Clock(3)
    session = PracticeSession(PracticeSpec(target_length=2), clock_ns=clock)
    session.pause()
    assert session.state == SessionState.PAUSED
    clock.seconds = 50
    session.resume()
    assert session.state == SessionState.READY
    clock.seconds = 100
    assert session.elapsed_seconds == 0
    press(session, session.target[0])
    clock.seconds = 102
    press(session, session.target[1])
    assert session.elapsed_seconds == 2


@pytest.mark.parametrize("pause", [False, True])
def test_abort_freezes_time_has_no_reward_and_rejects_future_input(pause: bool) -> None:
    clock = Clock()
    session = PracticeSession(PracticeSpec(target_length=2), clock_ns=clock)
    press(session, session.target[0])
    clock.seconds = 3
    if pause:
        session.pause()
        clock.seconds = 20
    session.abort()
    previous_result = session.result
    clock.seconds = 40
    assert session.state == SessionState.ABORTED
    assert session.elapsed_seconds == 3
    assert previous_result is not None
    assert previous_result.stars == 0
    session.abort()
    session.resume()
    assert press(session, session.target[1]) == InputResult.IGNORED
    assert session.result is previous_result


def test_ready_abort_does_not_start_timer() -> None:
    session = PracticeSession(PracticeSpec(), clock_ns=Clock(500))
    session.abort()
    assert session.result is not None
    assert session.result.elapsed_seconds == 0
    assert session.result.accuracy is None
    assert session.result.stars == 0


@pytest.mark.parametrize(
    ("correct", "incorrect", "expected_stars"),
    [(100, 0, 3), (19, 1, 2), (18, 1, 1), (100, 5, 2), (100, 6, 1)],
)
def test_stars_use_unrounded_accuracy_boundaries(
    correct: int, incorrect: int, expected_stars: int
) -> None:
    assert (
        typing_stars(completed=True, correct=correct, incorrect=incorrect)
        == expected_stars
    )
    assert typing_stars(completed=False, correct=correct, incorrect=incorrect) == 0


def test_assistance_limits_rewards() -> None:
    assert typing_stars(completed=True, correct=100, incorrect=0, step_returns=1) == 1
    assert typing_stars(completed=True, correct=100, incorrect=0, extra_hints=1) == 2
