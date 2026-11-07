"""편집 풀이의 경로 독립 완료·누적 입력·시간·단계 복귀 회귀 검증."""

# Standard library imports
from dataclasses import dataclass, replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.edit_loader import load_edit_lessons
from vim_key_trainer.domain.editing import EditLesson, GuideStep
from vim_key_trainer.domain.game_rules import editing_stars
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession

ESC = KeyToken("special", "esc")
BACKSPACE = KeyToken("special", "backspace")
REDO = KeyToken("chord", "ctrl+r")


def chars(text: str) -> tuple[KeyToken, ...]:
    return tuple(KeyToken("char", character) for character in text)


@dataclass
class Clock:
    seconds: float = 0

    def __call__(self) -> int:
        return round(self.seconds * 1_000_000_000)


def number_lesson() -> EditLesson:
    first = GuideStep(
        keys=chars("$x"),
        expected=EditorState(("n=",), column=1),
        text="마지막 숫자를 지웁니다.",
    )
    second = GuideStep(
        keys=chars("a2") + (ESC,),
        expected=EditorState(("n=2",), column=2),
        text="새 숫자를 입력하고 Normal 모드로 돌아옵니다.",
    )
    return EditLesson(
        schema_version=1,
        content_version=1,
        id="test_number",
        title="숫자 수정",
        description="1을 2로 바꾸세요.",
        initial=EditorState(("n=1",)),
        goal_lines=("n=2",),
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(first, second),
        baseline_version=1,
        baseline=first.keys + second.keys,
        baseline_keys=5,
    )


def play(session: EditingSession, keys: tuple[KeyToken, ...]) -> None:
    for key in keys:
        assert session.submit(key) == InputResult.ACCEPTED


def test_packaged_tasks_complete_in_both_available_modes() -> None:
    report = load_edit_lessons()
    assert not report.issues
    assert len(report.lessons) >= 5
    for lesson in report.lessons:
        guided = EditingSession(lesson)
        play(guided, tuple(key for step in lesson.guide for key in step.keys))
        assert guided.state == SessionState.COMPLETED
        assert guided.result is not None and guided.result.stars == 3
        if lesson.free_enabled:
            free = EditingSession(lesson, "free")
            play(free, lesson.baseline)
            assert free.state == SessionState.COMPLETED
            assert free.result is not None and free.result.stars == 3


def test_wrong_guided_keys_count_without_changing_document_or_pending_command() -> None:
    session = EditingSession(number_lesson())
    assert session.submit(KeyToken("char", "d")) == InputResult.REJECTED
    assert session.engine.state == session.lesson.initial
    assert session.submit(BACKSPACE) == InputResult.REJECTED
    assert session.key_count == session.incorrect == 2
    assert session.expected_token == KeyToken("char", "$")
    play(session, session.lesson.baseline)
    assert session.result is not None
    assert session.result.key_count == 7
    assert session.result.correct == 5
    assert session.result.incorrect == 2
    assert session.result.accuracy == pytest.approx(500 / 7)
    assert session.result.stars == 1


@pytest.mark.parametrize(
    ("keys", "expected_delta", "stars"),
    [
        (chars("A") + (BACKSPACE,) + chars("2") + (ESC,), -1, 3),
        (chars("lllxa2") + (ESC,), 2, 1),
    ],
)
def test_free_accepts_alternate_shorter_and_longer_solutions(
    keys: tuple[KeyToken, ...], expected_delta: int, stars: int
) -> None:
    session = EditingSession(number_lesson(), "free")
    play(session, keys)
    assert session.state == SessionState.COMPLETED
    assert session.result is not None
    assert session.result.delta == expected_delta
    assert session.result.stars == stars
    assert session.result.correct is None
    assert session.result.incorrect is None
    assert session.result.accuracy is None
    assert session.result.max_combo is None
    assert session.combo is None


def test_free_does_not_complete_in_insert_even_if_document_matches() -> None:
    session = EditingSession(number_lesson(), "free")
    play(session, chars("A") + (BACKSPACE,) + chars("2"))
    assert session.engine.state.lines == session.lesson.goal_lines
    assert session.engine.state.mode == "insert"
    assert session.state == SessionState.RUNNING
    assert session.result is None
    play(session, (ESC,))
    assert session.state == SessionState.COMPLETED


def test_goal_with_pending_command_cannot_complete() -> None:
    lesson = number_lesson()
    # 목표와 시작이 같은 직접 구성 과제도 대기 명령 중에는 완료할 수 없다.
    lesson = replace(lesson, goal_lines=lesson.initial.lines)
    session = EditingSession(lesson, "free")
    play(session, chars("d"))
    assert session.engine.state.pending
    assert session.state == SessionState.RUNNING
    play(session, (ESC,))
    assert session.state == SessionState.COMPLETED


def test_free_checks_cursor_only_when_requested() -> None:
    lesson = number_lesson()
    required = replace(lesson, goal_cursor=(0, 0))
    session = EditingSession(required, "free")
    play(session, lesson.baseline)
    assert session.engine.state.lines == lesson.goal_lines
    assert session.state == SessionState.RUNNING
    play(session, chars("0"))
    assert session.state == SessionState.COMPLETED


def test_guided_same_initial_goal_undo_task_requires_entire_guide() -> None:
    lesson = number_lesson()
    deletion = GuideStep(chars("x"), EditorState(("=1",)), "첫 글자를 지웁니다.")
    undo = GuideStep(chars("u"), lesson.initial, "되돌립니다.")
    lesson = replace(
        lesson,
        goal_lines=lesson.initial.lines,
        guide=(deletion, undo),
        baseline=chars("xu"),
        baseline_keys=2,
        free_enabled=False,
    )
    session = EditingSession(lesson)
    assert session.state == SessionState.READY
    assert session.submit(ESC) == InputResult.REJECTED
    assert session.state == SessionState.RUNNING
    play(session, chars("x"))
    assert session.result is None
    play(session, chars("u"))
    assert session.state == SessionState.COMPLETED
    with pytest.raises(ValueError, match="가이드"):
        EditingSession(lesson, "free")


def test_guided_matching_goal_before_remaining_guide_is_not_complete() -> None:
    lesson = number_lesson()
    final = lesson.guide[-1].expected
    lesson = replace(
        lesson,
        guide=lesson.guide
        + (GuideStep(chars("h"), replace(final, column=1), "왼쪽으로 이동합니다."),),
        baseline=lesson.baseline + chars("h"),
        baseline_keys=6,
    )
    session = EditingSession(lesson)
    play(session, lesson.baseline[:-1])
    assert session.engine.state.lines == lesson.goal_lines
    assert session.state == SessionState.RUNNING
    play(session, chars("h"))
    assert session.state == SessionState.COMPLETED


def test_step_return_restores_history_and_keeps_counters_and_time() -> None:
    clock = Clock(10)
    session = EditingSession(number_lesson(), clock_ns=clock)
    play(session, chars("$x"))
    assert session.step_index == 1
    play(session, chars("a2"))
    clock.seconds = 12
    assert session.return_to_step()
    assert session.engine.state.lines == ("n=",)
    assert session.engine.state.mode == "normal"
    assert session.token_index == 0
    assert session.key_count == session.correct == 4
    assert session.elapsed_seconds == 2
    assert session.combo == 0
    play(session, chars("a2") + (ESC,))
    assert session.result is not None
    assert session.result.key_count == 7
    assert session.result.step_returns == 1
    assert session.result.stars == 1
    # The resumed Insert group is one change, and the earlier x remains undoable.
    restored = EditingSession(number_lesson(), "free")
    restored.engine.restore(session.engine.snapshot())
    restored.engine.submit(KeyToken("char", "u"))
    assert restored.engine.state.lines == ("n=",)
    restored.engine.submit(KeyToken("char", "u"))
    assert restored.engine.state.lines == ("n=1",)


def test_step_return_from_boundary_restores_previous_step_and_redo_history() -> None:
    lesson = number_lesson()
    first = GuideStep(chars("xu"), lesson.initial, "삭제한 뒤 복원합니다.")
    second = GuideStep((REDO,), EditorState(("=1",)), "다시 적용합니다.")
    third = GuideStep(chars("iN") + (ESC,), EditorState(("N=1",)), "입력합니다.")
    lesson = replace(
        lesson,
        goal_lines=("N=1",),
        guide=(first, second, third),
        baseline=first.keys + second.keys + third.keys,
        baseline_keys=6,
    )
    session = EditingSession(lesson)
    play(session, first.keys + second.keys)
    assert session.step_index == 2
    assert session.return_to_step()
    assert session.step_index == 1
    assert session.engine.state.lines == ("n=1",)
    play(session, second.keys + third.keys)
    assert session.state == SessionState.COMPLETED


def test_step_return_restores_operator_waiting_for_its_motion() -> None:
    lesson = number_lesson()
    initial = EditorState(("one two",))
    operator = GuideStep(chars("d"), replace(initial, pending="d"), "삭제 대기")
    motion = GuideStep(chars("w"), EditorState(("two",)), "단어 삭제")
    append = GuideStep(
        chars("A!") + (ESC,), EditorState(("two!",), column=3), "느낌표 추가"
    )
    lesson = replace(
        lesson,
        initial=initial,
        goal_lines=("two!",),
        guide=(operator, motion, append),
        baseline=operator.keys + motion.keys + append.keys,
        baseline_keys=5,
    )
    session = EditingSession(lesson)
    play(session, operator.keys + motion.keys)
    assert session.return_to_step()
    assert session.engine.state.lines == initial.lines
    assert session.engine.state.pending == "d"
    assert session.expected_token == KeyToken("char", "w")
    play(session, motion.keys + append.keys)
    assert session.state == SessionState.COMPLETED


def test_free_counts_rejection_cancel_backspace_undo_redo_as_logical_keys() -> None:
    session = EditingSession(number_lesson(), "free")
    assert session.submit(KeyToken("char", "Q")) == InputResult.REJECTED
    assert session.submit(BACKSPACE) == InputResult.ACCEPTED
    play(session, chars("d") + (ESC,) + chars("xu") + (REDO,) + chars("u"))
    assert session.key_count == 8
    assert session.engine.state.lines == session.lesson.initial.lines
    assert session.submit(None) == InputResult.IGNORED
    assert session.key_count == 8
    play(session, session.lesson.baseline)
    assert session.result is not None and session.result.key_count == 13
    assert session.result.stars == 1


def test_hints_only_affect_free_rewards_and_do_not_start_time() -> None:
    clock = Clock(20)
    guided = EditingSession(number_lesson(), clock_ns=clock)
    guided.reveal_hint()
    assert guided.extra_hints == 0
    free = EditingSession(number_lesson(), "free", clock_ns=clock)
    free.reveal_hint()
    clock.seconds = 200
    assert free.extra_hints == 1
    assert free.elapsed_seconds == 0
    assert free.state == SessionState.READY
    play(free, free.lesson.baseline)
    assert free.result is not None and free.result.stars == 2


def test_pause_stops_time_ignores_input_and_requires_explicit_resume() -> None:
    clock = Clock(10)
    session = EditingSession(number_lesson(), clock_ns=clock)
    assert session.submit(KeyToken("char", "?")) == InputResult.REJECTED
    clock.seconds = 12
    session.pause()
    session.pause()
    clock.seconds = 100
    assert session.elapsed_seconds == 2
    assert session.submit(KeyToken("char", "$")) == InputResult.IGNORED
    assert session.key_count == 1
    session.resume()
    clock.seconds = 103
    play(session, session.lesson.baseline)
    clock.seconds = 500
    assert session.result is not None
    assert session.result.elapsed_seconds == session.elapsed_seconds == 5
    assert session.result.pause_count == 1


def test_pause_before_input_resumes_ready_and_restart_gets_new_attempt() -> None:
    clock = Clock(10)
    session = EditingSession(number_lesson(), clock_ns=clock)
    session.pause()
    clock.seconds = 100
    session.resume()
    assert session.state == SessionState.READY
    assert session.elapsed_seconds == 0
    retry = EditingSession(session.lesson, session.mode, clock_ns=clock)
    assert retry.attempt_id != session.attempt_id
    assert retry.engine.state == session.engine.state == session.lesson.initial


def test_abort_is_idempotent_freezes_time_and_cannot_award_or_accept_input() -> None:
    clock = Clock()
    session = EditingSession(number_lesson(), "free", clock_ns=clock)
    play(session, chars("d"))
    clock.seconds = 2
    session.abort()
    result = session.result
    assert result is not None and result.stars == 0
    clock.seconds = 100
    session.abort()
    session.resume()
    assert session.elapsed_seconds == 2
    assert session.result is result
    assert session.submit(ESC) == InputResult.IGNORED
    assert not session.return_to_step()


@pytest.mark.parametrize(
    ("completed", "key_count", "baseline", "hints", "returns", "expected"),
    [
        (False, 3, 5, 0, 0, 0),
        (True, 6, 5, 0, 0, 1),
        (True, 5, 5, 1, 0, 2),
        (True, 4, 5, 0, 1, 2),
        (True, 5, 5, 0, 0, 3),
        (True, 4, 5, 0, 0, 3),
    ],
)
def test_free_stars_use_efficiency_and_assistance(
    completed: bool,
    key_count: int,
    baseline: int,
    hints: int,
    returns: int,
    expected: int,
) -> None:
    assert (
        editing_stars(
            completed=completed,
            key_count=key_count,
            baseline_keys=baseline,
            extra_hints=hints,
            step_returns=returns,
        )
        == expected
    )
