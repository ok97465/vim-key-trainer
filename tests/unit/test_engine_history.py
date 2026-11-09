"""삽입·변경·반복의 undo/redo 단위와 스냅샷 복원 회귀."""

# Standard library imports
from dataclasses import FrozenInstanceError

# Third party imports
import pytest
from engine_support import BACKSPACE, ENTER, ESC, REDO, chord, type_keys

# Local imports
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import characters
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState


@pytest.mark.parametrize("command", ["2i", "2a", "2I", "2A"])
def test_counted_insert_is_one_undo_unit(command: str) -> None:
    engine = EditEngine(EditorState(("one two",)))
    type_keys(engine, command + "X")
    engine.submit(ESC)
    assert engine.state.lines[0].count("X") == 2
    type_keys(engine, "u")
    assert engine.state.lines == ("one two",)


@pytest.mark.parametrize(
    ("command", "column"), [("i", 3), ("a", 4), ("I", 2), ("A", 5)]
)
def test_insert_entry_points(command: str, column: int) -> None:
    engine = EditEngine(EditorState(("  abc",), column=3))
    type_keys(engine, command)
    assert engine.state.mode == "insert"
    assert engine.state.column == column
    type_keys(engine, "X")
    engine.submit(ESC)
    assert engine.state.mode == "normal"
    assert engine.state.column == column


@pytest.mark.parametrize(
    ("initial", "command", "undo_column", "redo_column"),
    [
        (EditorState(("abc",)), "A", 2, 3),
        (EditorState(("abc",)), "a", 1, 1),
        (EditorState(("  abc",), column=4), "I", 2, 2),
        (EditorState(("abc",)), "i", 0, 0),
        (EditorState(("",)), "A", 0, 0),
    ],
)
def test_insert_undo_redo_use_insertion_origin_not_previous_or_exit_cursor(
    initial: EditorState, command: str, undo_column: int, redo_column: int
) -> None:
    # normal.c moves a/A/I before edit.c saves the undo cursor; undo.c uses
    # that saved origin for both directions and clamps to the current line.
    engine = EditEngine(initial)
    type_keys(engine, command + "XY")
    engine.submit(ESC)
    changed_lines = engine.state.lines
    type_keys(engine, "u")
    assert engine.state.lines == initial.lines
    assert engine.state.column == undo_column
    assert engine.state.mode == "normal"
    engine.submit(REDO)
    assert engine.state.lines == changed_lines
    assert engine.state.column == redo_column


def test_insert_space_enter_backspace_and_exit_cursor() -> None:
    engine = EditEngine(EditorState(("ab",), column=1))
    type_keys(engine, "iX ")
    engine.submit(ENTER)
    type_keys(engine, "Y")
    assert engine.state.lines == ("aX ", "Yb")
    engine.submit(BACKSPACE)
    engine.submit(BACKSPACE)
    assert engine.state.lines == ("aX b",)
    assert engine.state.column == 3
    engine.submit(ESC)
    assert engine.state.column == 2


def test_backspace_can_remove_preexisting_text_and_join_lines() -> None:
    engine = EditEngine(EditorState(("abc", "def"), row=1))
    type_keys(engine, "i")
    engine.submit(BACKSPACE)
    engine.submit(BACKSPACE)
    assert engine.state.lines == ("abdef",)
    assert engine.state.column == 2
    engine.submit(ESC)
    type_keys(engine, "u")
    assert engine.state.lines == ("abc", "def")


def test_empty_insert_escape_and_backspace_at_buffer_start() -> None:
    engine = EditEngine(EditorState(("",)))
    type_keys(engine, "i")
    assert not engine.submit(KeyToken("special", "tab")).accepted
    engine.submit(BACKSPACE)
    engine.submit(ENTER)
    engine.submit(ESC)
    assert engine.state.lines == ("", "")
    assert (engine.state.row, engine.state.column, engine.state.mode) == (
        1,
        0,
        "normal",
    )


def test_insert_group_and_delete_are_separate_undo_blocks() -> None:
    engine = EditEngine(EditorState(("one two",)))
    type_keys(engine, "dwiAB")
    engine.submit(ENTER)
    type_keys(engine, "CD")
    engine.submit(ESC)
    assert engine.state.lines == ("AB", "CDtwo")
    type_keys(engine, "u")
    assert engine.state.lines == ("two",)
    type_keys(engine, "u")
    assert engine.state.lines == ("one two",)
    engine.submit(REDO)
    engine.submit(REDO)
    assert engine.state.lines == ("AB", "CDtwo")


def test_movement_does_not_make_undo_or_erase_redo_but_new_edit_does() -> None:
    engine = EditEngine(EditorState(("abcdef",)))
    type_keys(engine, "xlu")
    assert engine.state.lines == ("abcdef",)
    type_keys(engine, "ll")
    engine.submit(REDO)
    assert engine.state.lines == ("bcdef",)
    type_keys(engine, "ux")
    assert engine.state.lines == ("bcdef",)
    engine.submit(REDO)
    assert engine.state.lines == ("bcdef",)


def test_empty_insert_does_not_erase_redo() -> None:
    engine = EditEngine(EditorState(("abc",)))
    type_keys(engine, "xuA")
    engine.submit(ESC)
    engine.submit(REDO)
    assert engine.state.lines == ("bc",)


def test_snapshot_restores_pending_preference_and_both_histories() -> None:
    engine = EditEngine(EditorState(("abcdef", "x", "abcdef"), column=4))
    type_keys(engine, "xxu$jd2")
    snapshot = engine.snapshot()
    type_keys(engine, "d")
    assert engine.state.lines == ("abcdf",)
    engine.restore(snapshot)
    assert engine.state.pending == "d2"
    engine.submit(ESC)
    type_keys(engine, "j")
    assert engine.state.column == 5
    engine.submit(REDO)
    assert engine.state.lines == ("abcd", "x", "abcdef")
    type_keys(engine, "u")
    assert engine.state.lines == ("abcdf", "x", "abcdef")


def test_snapshot_in_insert_preserves_original_undo_group() -> None:
    engine = EditEngine(EditorState(("abc",)))
    type_keys(engine, "iX")
    snapshot = engine.snapshot()
    type_keys(engine, "Y")
    engine.submit(ESC)
    engine.restore(snapshot)
    type_keys(engine, "Z")
    engine.submit(ESC)
    assert engine.state.lines == ("XZabc",)
    type_keys(engine, "u")
    assert engine.state.lines == ("abc",)
    engine.submit(REDO)
    assert engine.state.lines == ("XZabc",)


def test_initial_insert_state_and_immutable_document() -> None:
    state = EditorState(("abc",), column=3, mode="insert")
    engine = EditEngine(state)
    type_keys(engine, "d")
    engine.submit(ESC)
    type_keys(engine, "u")
    assert engine.state.lines == ("abc",)
    assert engine.state.mode == "normal"
    with pytest.raises(FrozenInstanceError):
        state.row = 1  # type: ignore[misc]


def test_initial_replace_mode_keeps_one_undo_group() -> None:
    engine = EditEngine(EditorState(("abc",), column=1, mode="replace"))
    type_keys(engine, "XY")
    snapshot = engine.snapshot()
    type_keys(engine, "Z")
    engine.restore(snapshot)
    engine.submit(ESC)
    assert engine.state.lines == ("aXY",)
    type_keys(engine, "u")
    assert engine.state.lines == ("abc",)
    chord(engine, "r")
    assert engine.state.lines == ("aXY",)


@pytest.mark.parametrize(
    ("line", "column", "keys", "expected"),
    [
        ("one two", 1, "ciwX", "X two"),
        ('a "two" b', 4, 'ci"X', 'a "X" b'),
        ("one two", 0, "cwX", "X two"),
        ("one two", 0, "cWX", "X two"),
        ("one two", 0, "ceX", "X two"),
        ("  one two", 3, "ccX", "X"),
        ("one two", 4, "CX", "one X"),
        ("one two", 0, "sX", "Xne two"),
        ("one two", 0, "SX", "X"),
        ("abc", 1, "RXY", "aXY"),
    ],
)
def test_change_and_replace_group_delete_with_insert_until_escape(
    line: str, column: int, keys: str, expected: str
) -> None:
    engine = EditEngine(EditorState((line,), column=column))
    type_keys(engine, keys)
    assert engine.state.mode in {"insert", "replace"}
    engine.submit(ESC)
    assert engine.state.lines == (expected,)
    type_keys(engine, "u")
    assert engine.state.lines == (line,)
    chord(engine, "r")
    assert engine.state.lines == (expected,)


@pytest.mark.parametrize(
    ("command", "expected"),
    [("o", ("one", "new", "two")), ("O", ("new", "one", "two"))],
)
def test_open_line_and_text_form_one_undo(
    command: str, expected: tuple[str, ...]
) -> None:
    engine = EditEngine(EditorState(("one", "two")))
    type_keys(engine, command + "new")
    engine.submit(ESC)
    assert engine.state.lines == expected
    type_keys(engine, "u")
    assert engine.state.lines == ("one", "two")


def test_replace_backspace_restores_the_overwritten_character() -> None:
    engine = EditEngine(EditorState(("abcd",), column=1))
    type_keys(engine, "RXY")
    engine.submit(BACKSPACE)
    engine.submit(ESC)
    assert engine.state.lines == ("aXcd",)
    type_keys(engine, "u")
    assert engine.state.lines == ("abcd",)


@pytest.mark.parametrize("command", ["dW", "de", "dE", "diw", "diW", "2d2iw"])
def test_word_delete_is_one_undo_unit_and_redo_restores_it(command: str) -> None:
    initial = EditorState(("one,two three four",), column=1)
    engine = EditEngine(initial)
    type_keys(engine, command)
    changed = engine.state
    assert changed.lines != initial.lines
    type_keys(engine, "u")
    assert engine.state == initial
    engine.submit(REDO)
    assert engine.state == changed


@pytest.mark.parametrize("prefix", ["di", "2d3i", "d99i"])
def test_inner_object_pending_is_restored_and_escape_cancels(prefix: str) -> None:
    initial = EditorState(("one two three four five",))
    engine = EditEngine(initial)
    type_keys(engine, prefix)
    snapshot = engine.snapshot()
    engine.submit(ESC)
    assert engine.state == initial
    engine.restore(snapshot)
    assert engine.state.pending == prefix
    engine.submit(ESC)
    assert engine.state == initial


def test_word_motion_does_not_add_history_or_discard_redo() -> None:
    engine = EditEngine(EditorState(("one,two three",)))
    type_keys(engine, "diwuWEB")
    engine.submit(REDO)
    assert engine.state.lines == (",two three",)


def test_dot_repeats_insert_text_and_remains_one_undo() -> None:
    engine = EditEngine(EditorState(("one two",)))
    type_keys(engine, "ciwX")
    engine.submit(ESC)
    type_keys(engine, "w.")
    assert engine.state.lines == ("X X",)
    type_keys(engine, "u")
    assert engine.state.lines == ("X two",)


@pytest.mark.parametrize("change", ["d2w", "2dw", "2d2w", '"ad2w'])
def test_dot_count_replaces_operator_and_motion_counts(change: str) -> None:
    words = tuple(f"word{index}" for index in range(20))
    engine = EditEngine(EditorState((" ".join(words),)))
    type_keys(engine, change)
    before_repeat = engine.state.lines
    remaining = before_repeat[0].split()
    type_keys(engine, "3.")
    assert engine.state.lines == (" ".join(remaining[3:]),)
    type_keys(engine, "u")
    assert engine.state.lines == before_repeat
    chord(engine, "r")
    type_keys(engine, ".")
    assert engine.state.lines == (" ".join(remaining[6:]),)


@pytest.mark.parametrize(
    ("change", "repeat", "expected"),
    [
        ("2r1", "l3.", "11111fghi"),
        ("d0", "$2.", "i"),
        ('"a2x', "3..", "i"),
    ],
)
def test_dot_count_keeps_literal_digits_and_named_registers(
    change: str, repeat: str, expected: str
) -> None:
    engine = EditEngine(EditorState(("abcdefghi",), column=1 if change == "d0" else 0))
    type_keys(engine, change + repeat)
    assert engine.state.lines == (expected,)


@pytest.mark.parametrize("text", ["p.r", ".", "u.p", "i.not_a_command"])
def test_failed_change_motion_does_not_execute_saved_insert_text_as_normal(
    text: str,
) -> None:
    engine = EditEngine(EditorState(("old? tail", "plain line", "next? tail")))
    change = characters("cf?" + text) + (ESC,)
    for token in change:
        assert engine.submit(token).accepted
    assert engine.state.lines[0] == text + " tail"
    assert engine.snapshot().last_change == change
    type_keys(engine, "j0")
    before = engine.snapshot()
    type_keys(engine, "..")
    assert engine.state == before.state
    assert engine.snapshot().last_change == change
    type_keys(engine, "j0.")
    assert engine.state.lines == (text + " tail", "plain line", text + " tail")
    assert engine.snapshot().last_change == change
    type_keys(engine, "u")
    assert engine.state.lines[2] == "next? tail"


def test_consecutive_dots_keep_replaying_the_original_change_after_movements() -> None:
    engine = EditEngine(EditorState(("one two three", "four five six")))
    change = characters("ciwX") + (ESC,)
    for token in change:
        assert engine.submit(token).accepted
    type_keys(engine, "w.w.j0.w.w.")
    assert engine.state.lines == ("X X X", "X X X")
    assert engine.snapshot().last_change == change


def test_guide_snapshot_probe_stops_a_failed_dot_before_literal_period() -> None:
    guide = GuideBuilder(
        EditorState(("old? tail", "plain line", "next? tail")), SUPPORTED_COMMANDS
    )
    change = characters("cf?p.r") + (ESC,)
    guide.record(change, "물음표까지의 값을 바꿉니다.")
    snapshot = guide.engine.snapshot()
    probe = EditEngine(snapshot.state, SUPPORTED_COMMANDS)
    probe.restore(snapshot)
    type_keys(probe, "j0.")
    assert probe.state.lines == ("p.r tail", "plain line", "next? tail")
    assert probe.state.mode == "normal" and not probe.state.pending
    assert guide.engine.snapshot() == snapshot
    guide.navigate(2, 0)
    guide.record(characters("."), "앞의 변경을 반복합니다.")
    assert guide.engine.state.lines == ("p.r tail", "plain line", "p.r tail")
    assert guide.engine.snapshot().last_change == change


def test_dot_does_not_repeat_an_ex_substitution() -> None:
    engine = EditEngine(EditorState(("a",)))
    type_keys(engine, ":s/a/aa/")
    engine.submit(ENTER)
    type_keys(engine, ".")
    assert engine.state.lines == ("aa",)


def test_large_unmarked_buffer_edits_skip_full_document_difference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = tuple(f"item_{row} = 10" for row in range(500))
    engine = EditEngine(EditorState(lines, row=450))

    def forbid_full_scan(*_args: object) -> None:
        pytest.fail("마크 없는 입력에서 문서 전체 차이를 계산했습니다.")

    monkeypatch.setattr(EditEngine, "_difference", forbid_full_scan)
    type_keys(engine, "A # updated")
    assert engine.submit(ESC).accepted
    assert engine.state.lines[450] == lines[450] + " # updated"
    type_keys(engine, "u")
    assert engine.state.lines == lines
    chord(engine, "r")
    assert engine.state.lines[450] == lines[450] + " # updated"
