"""복사한 원본 범위와 세션의 일회성 알림을 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditLesson, EditMode, GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult
from vim_key_trainer.engine import (
    SUPPORTED_COMMANDS,
    EditEngine,
    EditorState,
    EditOutcome,
    YankSpan,
)
from vim_key_trainer.services.edit_session import EditingSession


def chars(text: str) -> tuple[KeyToken, ...]:
    return tuple(KeyToken("char", character) for character in text)


def execute(engine: EditEngine, text: str) -> EditOutcome:
    outcome = EditOutcome(True)
    for key in chars(text):
        outcome = engine.submit(key)
        assert outcome.accepted, outcome.message
    return outcome


@pytest.mark.parametrize(
    ("initial", "keys", "expected"),
    [
        (EditorState(("same", "same"), row=1), "yy", ((1, 0, 4),)),
        (EditorState(("same", "same"), row=1), "Y", ((1, 0, 4),)),
        (EditorState(("one", "", "three")), "2yy", ((0, 0, 3), (1, 0, 0))),
        (EditorState(("one", "")), "yj", ((0, 0, 3), (1, 0, 0))),
        (EditorState(("one", "two", "three"), row=2), "yk", ((1, 0, 3), (2, 0, 5))),
        (EditorState(("one two",), column=4), "yb", ((0, 0, 4),)),
        (EditorState(("abc abc",), column=5), "yiw", ((0, 4, 7),)),
        (EditorState(("one two",), column=4), "yw", ((0, 4, 7),)),
        (EditorState(("one two three",)), "y2w", ((0, 0, 8),)),
        (EditorState(("(one", "two)"), column=1), "yi(", ((0, 1, 4), (1, 0, 3))),
        (
            EditorState(("abc", "def"), column=1, mode="visual", visual_anchor=(1, 2)),
            "y",
            ((0, 1, 3), (1, 0, 3)),
        ),
        (
            EditorState(("abc", ""), row=1, mode="visual_line", visual_anchor=(0, 0)),
            "y",
            ((0, 0, 3), (1, 0, 0)),
        ),
        (
            EditorState(
                ("abcdef", "", "ab", "abcdef"),
                row=3,
                column=4,
                mode="visual_block",
                visual_anchor=(0, 2),
            ),
            "y",
            ((0, 2, 5), (3, 2, 5)),
        ),
        (EditorState(("",)), "yy", ((0, 0, 0),)),
        (EditorState(("",)), "yl", ()),
        (EditorState(("one two",)), "yfZ", ()),
        (EditorState(("one two",)), 'yi"', ()),
    ],
)
def test_yank_reports_actual_source_spans(
    initial: EditorState, keys: str, expected: tuple[tuple[int, int, int], ...]
) -> None:
    engine = EditEngine(initial)
    outcome = execute(engine, keys)
    assert outcome.yanked_spans == tuple(YankSpan(*span) for span in expected)
    assert engine.state.lines == initial.lines
    assert not outcome.changed
    assert not engine.snapshot().undo


def test_repeated_identical_yank_emits_each_time_without_register_change() -> None:
    engine = EditEngine(EditorState(("repeat",)))
    first = execute(engine, "yy")
    snapshot = engine.snapshot()
    assert execute(engine, "yy").yanked_spans == first.yanked_spans
    assert engine.snapshot() == snapshot
    assert engine.submit(KeyToken("char", "y")).yanked_spans == ()


@pytest.mark.parametrize("keys", ['"_yy', "dd", "cw", "p", "P", "u"])
def test_discard_delete_change_put_and_history_do_not_emit_yank(keys: str) -> None:
    engine = EditEngine(EditorState(("one two", "three")))
    execute(engine, "yy")
    assert execute(engine, keys).yanked_spans == ()


def test_named_register_append_only_highlights_the_new_source() -> None:
    engine = EditEngine(EditorState(("first", "second")))
    execute(engine, '"ayyj')
    assert execute(engine, '"Ayy').yanked_spans == (YankSpan(1, 0, 6),)


def yank_lesson() -> EditLesson:
    initial = EditorState(("one two",))
    goal = EditorState(("Xne two",))
    return EditLesson(
        schema_version=1,
        content_version=1,
        id="test_yank",
        title="복사",
        description="복사한 뒤 첫 글자를 수정합니다.",
        initial=initial,
        goal_lines=goal.lines,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(
            GuideStep(chars("yy"), initial, "복사"),
            GuideStep(chars("rX"), goal, "수정"),
        ),
        baseline_version=1,
        baseline=chars("yyrX"),
        baseline_keys=4,
    )


@pytest.mark.parametrize("mode", ["guided", "free"])
def test_session_exposes_event_only_for_last_successful_submit(mode: EditMode) -> None:
    session = EditingSession(yank_lesson(), mode)
    for key in chars("yy"):
        assert session.submit(key) == InputResult.ACCEPTED
    assert session.yanked_spans == (YankSpan(0, 0, 7),)
    assert session.key_count == 2
    assert session.submit(None) == InputResult.IGNORED
    assert not session.yanked_spans
    assert session.engine.state.lines == ("one two",)


def test_guided_rejection_does_not_publish_rolled_back_yank() -> None:
    lesson = yank_lesson()
    wrong_step = replace(lesson.guide[0], expected=EditorState(("wrong",)))
    session = EditingSession(replace(lesson, guide=(wrong_step,) + lesson.guide[1:]))
    assert session.submit(KeyToken("char", "y")) == InputResult.ACCEPTED
    assert session.submit(KeyToken("char", "y")) == InputResult.REJECTED
    assert not session.yanked_spans
    assert not session.engine.snapshot().registers


def test_wrong_guided_key_and_step_return_clear_event() -> None:
    session = EditingSession(yank_lesson())
    for key in chars("yy"):
        session.submit(key)
    assert session.yanked_spans
    assert session.submit(KeyToken("char", "x")) == InputResult.REJECTED
    assert not session.yanked_spans
    assert session.return_to_step(0)
    for key in chars("yy"):
        session.submit(key)
    assert session.yanked_spans
    assert session.return_to_step(0)
    assert not session.yanked_spans


def test_pause_abort_and_retry_do_not_replay_yank() -> None:
    session = EditingSession(yank_lesson(), "free")
    for key in chars("yy"):
        session.submit(key)
    assert session.yanked_spans
    assert not session.retry().yanked_spans
    session.pause()
    assert not session.yanked_spans
    session.resume()
    for key in chars("yy"):
        session.submit(key)
    assert session.yanked_spans
    session.abort()
    assert not session.yanked_spans


@pytest.mark.parametrize("timer_expiration", [False, True])
def test_deadline_recovery_does_not_republish_previous_yank(
    timer_expiration: bool,
) -> None:
    now_ns = 0
    session = EditingSession(
        yank_lesson(),
        clock_ns=lambda: now_ns,
        challenge=ChallengeOptions("bomb"),
    )
    for key in chars("yy"):
        session.submit(key)
    assert session.yanked_spans
    assert session.segment_limit_seconds is not None
    now_ns = round(session.segment_limit_seconds * 1_000_000_000)
    if timer_expiration:
        assert session.check_deadline()
    else:
        assert session.submit(KeyToken("char", "r")) == InputResult.REJECTED
    assert not session.yanked_spans
    assert session.engine.state.lines == session.lesson.goal_lines
