"""Visual 선택·메모리 레지스터·복사 알림의 범위와 수명 회귀."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest
from engine_support import ENTER, ESC, chars, chord, execute, type_keys

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditLesson, EditMode, GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState, YankSpan
from vim_key_trainer.services.edit_session import EditingSession


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("yj", ("abc", "abc", "", "")),
        ("Vjy", ("abc", "abc", "", "")),
        ("Vy", ("abc", "abc", "")),
    ],
)
def test_linewise_yank_preserves_selected_trailing_empty_line(
    keys: str, expected: tuple[str, ...]
) -> None:
    engine = EditEngine(EditorState(("abc", "")))
    type_keys(engine, keys + "ggp")
    assert engine.state.lines == expected


@pytest.mark.parametrize("keys", ["cj", "Vjc"])
def test_linewise_change_includes_trailing_empty_line_and_undo(keys: str) -> None:
    engine = EditEngine(EditorState(("abc", "")))
    type_keys(engine, keys + "X")
    engine.submit(ESC)
    assert engine.state.lines == ("X",)
    type_keys(engine, "u")
    assert engine.state.lines == ("abc", "")
    chord(engine, "r")
    assert engine.state.lines == ("X",)


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("yyp", ("one", "one", "two")),
        ("yyP", ("one", "one", "two")),
        ('"ayyj"ap', ("one", "two", "one")),
        ("yiw$p", ("one twoone",)),
    ],
)
def test_yank_and_memory_register_put(keys: str, expected: tuple[str, ...]) -> None:
    lines = ("one two",) if keys == "yiw$p" else ("one", "two")
    engine = EditEngine(EditorState(lines))
    type_keys(engine, keys)
    assert engine.state.lines == expected
    type_keys(engine, "u")
    assert engine.state.lines == lines


@pytest.mark.parametrize(
    ("lines", "keys", "mode", "expected"),
    [
        (("one two",), "Viw", "visual", (" two",)),
        (("one two", "three", "", "tail"), "vip", "visual_line", ("", "tail")),
        (("one two", ""), "vap", "visual_line", ("",)),
    ],
)
def test_visual_text_object_uses_its_own_selection_mode(
    lines: tuple[str, ...], keys: str, mode: str, expected: tuple[str, ...]
) -> None:
    engine = EditEngine(EditorState(lines))
    type_keys(engine, keys)
    assert engine.state.mode == mode
    type_keys(engine, "x")
    assert engine.state.lines == expected
    type_keys(engine, "u")
    assert engine.state.lines == lines


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("vld", ("cdef", "second")),
        ("Vd", ("second",)),
        ("vly$p", ("abcdefab", "second")),
    ],
)
def test_visual_char_and_line_selection(keys: str, expected: tuple[str, ...]) -> None:
    engine = EditEngine(EditorState(("abcdef", "second")))
    type_keys(engine, keys)
    assert engine.state.lines == expected
    assert engine.state.mode == "normal"


def test_visual_change_groups_delete_and_insert() -> None:
    engine = EditEngine(EditorState(("abcd",)))
    type_keys(engine, "vlcX")
    engine.submit(ESC)
    assert engine.state.lines == ("Xcd",)
    type_keys(engine, "u")
    assert engine.state.lines == ("abcd",)


@pytest.mark.parametrize("selection", ["v", "V", "ctrl+v"])
@pytest.mark.parametrize("command", ["S", "R"])
def test_visual_line_change_aliases_clear_selection_and_group_insert(
    selection: str, command: str
) -> None:
    lines = ("first", "second", "third")
    engine = EditEngine(EditorState(lines, column=2))
    if selection == "ctrl+v":
        chord(engine, "v")
    else:
        type_keys(engine, selection)
    type_keys(engine, "j" + command)
    assert engine.state.lines == ("", "third")
    assert engine.state.mode == "insert"
    assert engine.state.visual_anchor is None
    type_keys(engine, "X")
    engine.submit(ENTER)
    type_keys(engine, "Y")
    engine.submit(ESC)
    assert engine.state.lines == ("X", "Y", "third")
    type_keys(engine, "u")
    assert engine.state.lines == lines
    chord(engine, "r")
    assert engine.state.lines == ("X", "Y", "third")


@pytest.mark.parametrize("selection", ["v", "V", "ctrl+v"])
def test_visual_uppercase_delete_removes_selected_lines(selection: str) -> None:
    lines = ("first", "second", "third")
    engine = EditEngine(EditorState(lines, column=2))
    if selection == "ctrl+v":
        chord(engine, "v")
    else:
        type_keys(engine, selection)
    type_keys(engine, "jX")
    assert engine.state.lines == ("third",)
    assert engine.state.mode == "normal"
    assert engine.state.visual_anchor is None
    type_keys(engine, "u")
    assert engine.state.lines == lines


def test_visual_block_delete_and_restore_selection_snapshot() -> None:
    engine = EditEngine(EditorState(("abcd", "ABCD"), column=1))
    chord(engine, "v")
    type_keys(engine, "jl")
    snapshot = engine.snapshot()
    type_keys(engine, "d")
    assert engine.state.lines == ("ad", "AD")
    engine.restore(snapshot)
    assert engine.state.mode == "visual_block"
    assert engine.state.visual_anchor == (0, 1)
    engine.submit(ESC)
    assert engine.state.lines == ("abcd", "ABCD")


def test_internal_register_and_mark_history_survive_snapshot() -> None:
    engine = EditEngine(EditorState(("one", "two")))
    type_keys(engine, '"ayyma')
    snapshot = engine.snapshot()
    type_keys(engine, 'j"ayyma')
    engine.restore(snapshot)
    type_keys(engine, 'G"ap')
    assert engine.state.lines == ("one", "two", "one")
    type_keys(engine, "`a")
    assert engine.state.row == 0


def test_yank_preserves_motion_range_when_adjacent_text_repeats() -> None:
    engine = EditEngine(EditorState(("one one",)))
    type_keys(engine, "yw$p")
    assert engine.state.lines == ("one oneone ",)


@pytest.mark.parametrize(
    ("initial", "contents", "kind", "keys", "expected", "cursor"),
    [
        (("abcde",), ("X",), "char", "$vhp", ("abcX",), (0, 3)),
        (("abcde",), ("XYZ",), "char", "vllp", ("XYZde",), (0, 2)),
        (("abcde",), ("X",), "line", "vllp", ("", "X", "de"), (1, 0)),
        (
            ("one", "middle", "last"),
            ("X",),
            "line",
            "GVp",
            ("one", "middle", "X"),
            (2, 0),
        ),
        (("one", "last"), ("XYZ",), "char", "GVp", ("one", "XYZ"), (1, 0)),
        (
            ("abcde", "fgHIj", "klmno"),
            ("X", "Y"),
            "block",
            "vllp",
            ("Xde", "YfgHIj", "klmno"),
            (0, 0),
        ),
    ],
)
def test_visual_put_replaces_the_exact_selection_as_one_change(
    initial: tuple[str, ...],
    contents: tuple[str, ...],
    kind: str,
    keys: str,
    expected: tuple[str, ...],
    cursor: tuple[int, int],
) -> None:
    engine = EditEngine(EditorState(initial))
    engine.restore(replace(engine.snapshot(), registers=(('"', contents, kind),)))
    type_keys(engine, keys)
    assert engine.state.lines == expected
    assert (engine.state.row, engine.state.column) == cursor
    type_keys(engine, "u")
    assert engine.state.lines == initial
    chord(engine, "r")
    assert engine.state.lines == expected


@pytest.mark.parametrize("put", ["p", "P"])
def test_visual_put_register_and_undo_preserve_an_earlier_independent_change(
    put: str,
) -> None:
    engine = EditEngine(EditorState(("abc", "")))
    type_keys(engine, "xyyjv" + put)
    assert engine.state.lines == ("bc", "", "bc", "")
    type_keys(engine, "u")
    assert engine.state.lines == ("bc", "")
    type_keys(engine, "u")
    assert engine.state.lines == ("abc", "")


@pytest.mark.parametrize("put", ["p", "P"])
def test_visual_put_updates_unnamed_register_only_for_lowercase_p(put: str) -> None:
    engine = EditEngine(EditorState(("abcde",)))
    type_keys(engine, "yl$v" + put)
    assert engine.state.lines == ("abcda",)
    unnamed = next(text for name, text, _ in engine.snapshot().registers if name == '"')
    assert unnamed == (("e",) if put == "p" else ("a",))


@pytest.mark.parametrize(
    ("contents", "kind", "expected"),
    [
        (("X",), "char", ("Xcde", "XHIj", "klmno")),
        (("XYZ",), "char", ("XYZcde", "XYZHIj", "klmno")),
        (("X", "Y"), "char", ("X", "Ycde", "HIj", "klmno")),
        (("X", "Y"), "block", ("Xcde", "YHIj", "klmno")),
        (("X", "Y"), "line", ("cde", "HIj", "X", "Y", "klmno")),
    ],
)
def test_visual_block_put_uses_register_shape(
    contents: tuple[str, ...], kind: str, expected: tuple[str, ...]
) -> None:
    initial = ("abcde", "fgHIj", "klmno")
    engine = EditEngine(EditorState(initial))
    engine.restore(replace(engine.snapshot(), registers=(('"', contents, kind),)))
    chord(engine, "v")
    type_keys(engine, "jlp")
    assert engine.state.lines == expected
    if kind == "char" and len(contents) == 1:
        assert (engine.state.row, engine.state.column) == (0, len(contents[0]) - 1)
    type_keys(engine, "u")
    assert engine.state.lines == initial


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
