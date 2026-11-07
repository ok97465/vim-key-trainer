"""공식 Vim 도움말의 작은 전후 예제와 엔진 경계 회귀 검증."""

# Standard library imports
from dataclasses import FrozenInstanceError

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState

ESC = KeyToken("special", "esc")
ENTER = KeyToken("special", "enter")
BACKSPACE = KeyToken("special", "backspace")
REDO = KeyToken("chord", "ctrl+r")


def type_keys(engine: EditEngine, text: str) -> None:
    for char in text:
        outcome = engine.submit(KeyToken("char", char))
        assert outcome.accepted, (char, outcome.message)


@pytest.mark.parametrize(
    ("initial", "keys", "position"),
    [
        (EditorState(("abcd",), column=2), "99h", (0, 0)),
        (EditorState(("abcd",)), "99l", (0, 3)),
        (EditorState(("", "abc")), "99j", (1, 0)),
        (EditorState(("abc", ""), row=1), "99k", (0, 0)),
        (EditorState(("  abc",), column=4), "0", (0, 0)),
        (EditorState(("  abc",)), "^", (0, 2)),
        (EditorState(("  abc  ",)), "$", (0, 6)),
        (EditorState(("",)), "^$0hl", (0, 0)),
        (EditorState(("a", "  b", "    c")), "G", (2, 4)),
        (EditorState(("a", "  b", "    c")), "2G", (1, 2)),
        (EditorState(("a", "  b", "c"), row=2), "gg", (0, 0)),
        (EditorState(("a", "  b", "c")), "2gg", (1, 2)),
        (EditorState(("a", "  b", "c")), "999G", (2, 0)),
    ],
)
def test_normal_motions(
    initial: EditorState, keys: str, position: tuple[int, int]
) -> None:
    engine = EditEngine(initial)
    type_keys(engine, keys)
    assert (engine.state.row, engine.state.column) == position
    assert engine.state.lines == initial.lines
    assert engine.state.pending == ""


def test_vertical_motions_keep_preferred_column_and_horizontal_resets_it() -> None:
    engine = EditEngine(EditorState(("abcdef", "x", "uvwxyz"), column=4))
    type_keys(engine, "jj")
    assert (engine.state.row, engine.state.column) == (2, 4)
    type_keys(engine, "khj")
    assert (engine.state.row, engine.state.column) == (2, 0)


def test_dollar_keeps_end_of_line_preference() -> None:
    engine = EditEngine(EditorState(("abc", "longer", "", "four")))
    type_keys(engine, "$j")
    assert engine.state.column == 5
    type_keys(engine, "jj")
    assert (engine.state.row, engine.state.column) == (3, 3)


def test_word_motions_distinguish_keyword_punctuation_and_empty_lines() -> None:
    engine = EditEngine(EditorState(("one_two,+=three  four", "", "  five")))
    expected = [(0, 7), (0, 10), (0, 17), (1, 0), (2, 2)]
    for position in expected:
        type_keys(engine, "w")
        assert (engine.state.row, engine.state.column) == position
    for position in reversed([(0, 0), *expected[:-1]]):
        type_keys(engine, "b")
        assert (engine.state.row, engine.state.column) == position


def test_word_motion_from_inside_word_or_whitespace_and_eof() -> None:
    engine = EditEngine(EditorState(("one  two",), column=2))
    type_keys(engine, "b")
    assert engine.state.column == 0
    type_keys(engine, "4lw")
    assert engine.state.column == 5
    type_keys(engine, "99w")
    assert engine.state.column == 7
    type_keys(engine, "99b")
    assert engine.state.column == 0


@pytest.mark.parametrize(
    ("initial", "keys", "lines", "position"),
    [
        (EditorState(("abcd",), column=1), "2x", ("ad",), (0, 1)),
        (EditorState(("abcd",), column=1), "999x", ("a",), (0, 0)),
        (EditorState(("",)), "x", ("",), (0, 0)),
        (EditorState(("one", "two", "  three")), "dd", ("two", "  three"), (0, 0)),
        (EditorState(("one", "two", "  three")), "d2d", ("  three",), (0, 2)),
        (EditorState(("one", "two", "  three")), "2dd", ("  three",), (0, 2)),
        (EditorState(("one", "two"), row=1), "dd", ("one",), (0, 0)),
        (EditorState(("one", "two")), "999dd", ("",), (0, 0)),
        (EditorState(("one two three",)), "dw", ("two three",), (0, 0)),
        (EditorState(("one two three",)), "d2w", ("three",), (0, 0)),
        (EditorState(("one,two",)), "dw", (",two",), (0, 0)),
        (EditorState(("one,two",), column=3), "dw", ("onetwo",), (0, 3)),
        (EditorState(("one", "two")), "dw", ("", "two"), (0, 0)),
        (
            EditorState(("one two   ", "three"), column=4),
            "dw",
            ("one ", "three"),
            (0, 3),
        ),
        (EditorState(("one two", "three")), "2dw", ("", "three"), (0, 0)),
        (EditorState(("one", "two three")), "2dw", ("three",), (0, 0)),
        (EditorState(("one", "two", "three")), "2dw", ("three",), (0, 0)),
        (EditorState(("", "two")), "dw", ("two",), (0, 0)),
        (EditorState(("one",)), "999dw", ("",), (0, 0)),
    ],
)
def test_deletion_ranges(
    initial: EditorState, keys: str, lines: tuple[str, ...], position: tuple[int, int]
) -> None:
    engine = EditEngine(initial)
    type_keys(engine, keys)
    assert engine.state.lines == lines
    assert (engine.state.row, engine.state.column) == position


def test_operator_counts_multiply_for_words_and_lines() -> None:
    words = EditEngine(EditorState(("a b c d e f keep",)))
    type_keys(words, "2d3w")
    assert words.state.lines == ("keep",)
    lines = EditEngine(EditorState(tuple(str(i) for i in range(8))))
    type_keys(lines, "2d3d")
    assert lines.state.lines == ("6", "7")


def test_zero_is_motion_or_count_digit_according_to_context() -> None:
    engine = EditEngine(EditorState(("abcdefghijklmnop",), column=4))
    type_keys(engine, "0")
    assert engine.state.column == 0
    type_keys(engine, "10l")
    assert engine.state.column == 10
    type_keys(engine, "d")
    assert engine.submit(KeyToken("char", "0")).accepted
    assert engine.state.lines == ("klmnop",)
    assert engine.state.pending == ""


@pytest.mark.parametrize("prefix", ["1000", "999d2", "99d99"])
def test_count_limit_cancels_atomically(prefix: str) -> None:
    initial = EditorState(("one two three",))
    engine = EditEngine(initial)
    outcomes = [engine.submit(KeyToken("char", char)) for char in prefix]
    assert not outcomes[-1].accepted
    assert engine.state.lines == initial.lines
    assert engine.state.pending == ""


@pytest.mark.parametrize("prefix", ["2", "d", "2d3", "g", "20g"])
def test_escape_cancels_incomplete_command(prefix: str) -> None:
    initial = EditorState(("one two three",))
    engine = EditEngine(initial)
    type_keys(engine, prefix)
    assert engine.state.pending == prefix
    assert engine.submit(ESC).accepted
    assert engine.state == initial


@pytest.mark.parametrize("command", ["q", "@", "K", "gd", "=", "Z"])
def test_unsupported_commands_never_edit(command: str) -> None:
    initial = EditorState(("one two",))
    engine = EditEngine(initial)
    # Stop at the first rejection: a new key after rejection is a new command.
    for char in command:
        if not engine.submit(KeyToken("char", char)).accepted:
            break
    assert engine.state.lines == initial.lines
    assert engine.state.mode == "normal"
    assert not engine.state.pending


@pytest.mark.parametrize("command", ["2i", "2a", "2I", "2A"])
def test_counted_insert_is_one_undo_unit(command: str) -> None:
    engine = EditEngine(EditorState(("one two",)))
    type_keys(engine, command + "X")
    engine.submit(ESC)
    assert engine.state.lines[0].count("X") == 2
    type_keys(engine, "u")
    assert engine.state.lines == ("one two",)


def test_lesson_command_allowlist_and_actual_control_r() -> None:
    engine = EditEngine(EditorState(("abc",)), frozenset({"i", "x"}))
    assert not engine.submit(KeyToken("char", "d")).accepted
    assert not engine.submit(KeyToken("char", "a")).accepted
    assert not engine.submit(REDO).accepted
    type_keys(engine, "iZ")
    engine.submit(ESC)
    assert engine.state.lines == ("Zabc",)
    assert not engine.submit(KeyToken("chord", "cmd+r")).accepted
    with pytest.raises(ValueError, match="미지원"):
        EditEngine(EditorState(("a",)), frozenset({"run-shell"}))


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lines": ()},
        {"lines": ("a\nb",)},
        {"lines": ("a\tb",)},
        {"lines": ("한글",)},
        {"lines": ("abc",), "row": -1},
        {"lines": ("abc",), "column": 3},
        {"lines": ("",), "column": 1},
        {"lines": ("abc",), "mode": "visual"},
        {"lines": ("abc",), "preferred_column": -1},
        {"lines": ("abc",), "pending": "1000"},
        {"lines": ("abc",), "pending": "99d99"},
        {"lines": ("abc",), "pending": "d$"},
        {"lines": ("abc",), "mode": "insert", "pending": "d"},
    ],
)
def test_state_validates_public_boundary(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        EditorState(**kwargs)  # type: ignore[arg-type]
