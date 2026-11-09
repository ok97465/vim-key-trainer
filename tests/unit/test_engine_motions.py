"""문자·단어·문서·화면 이동과 이동 범위의 경계 회귀."""

# Third party imports
import pytest
from engine_support import chord, type_keys

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState


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
    ("initial", "keys", "position"),
    [
        (EditorState(("one_two,+=three  four",)), "W", (0, 17)),
        (EditorState(("one_two,+=three  four",), column=17), "B", (0, 0)),
        (EditorState(("one_two,+=three  four",), column=10), "B", (0, 0)),
        (EditorState(("one,two three",)), "e", (0, 2)),
        (EditorState(("one,two three",)), "2e", (0, 3)),
        (EditorState(("one,two three",)), "3e", (0, 6)),
        (EditorState(("one,two three",)), "E", (0, 6)),
        (EditorState(("one,two three",)), "2E", (0, 12)),
        (EditorState(("one,two",), column=2), "e", (0, 3)),
        (EditorState(("one,two",), column=2), "E", (0, 6)),
        (EditorState(("one,two", "", "  three")), "2W", (2, 2)),
        (EditorState(("one,two", "", "  three")), "2e", (0, 3)),
        (EditorState(("one,two", "", "  three")), "2E", (2, 6)),
        (EditorState(("one", "", "  three"), column=2), "e", (2, 6)),
        (EditorState(("one", "", "  three"), row=2, column=2), "2B", (0, 0)),
        (EditorState(("one", "  ", "two")), "W", (2, 0)),
        (EditorState(("one",)), "999E", (0, 2)),
        (EditorState(("one  ",)), "999e", (0, 4)),
        (EditorState(("",)), "WEB", (0, 0)),
    ],
)
def test_word_and_word_end_motions(
    initial: EditorState, keys: str, position: tuple[int, int]
) -> None:
    engine = EditEngine(initial)
    type_keys(engine, keys)
    assert engine.state.lines == initial.lines
    assert (engine.state.row, engine.state.column) == position
    assert engine.state.pending == ""


@pytest.mark.parametrize(
    ("keys", "column"),
    [("fc", 2), ("2fc", 5), ("tc", 1), ("fc;", 5), ("2fc,", 2), ("$Fc", 5), ("$Tc", 6)],
)
def test_character_find_counts_and_repeat(keys: str, column: int) -> None:
    engine = EditEngine(EditorState(("abcabcabc",)))
    type_keys(engine, keys)
    assert engine.state.column == column
    assert engine.state.lines == ("abcabcabc",)


def test_find_motion_can_be_combined_with_delete() -> None:
    engine = EditEngine(EditorState(("abc:def",)))
    type_keys(engine, "dt:")
    assert engine.state.lines == (":def",)
    type_keys(engine, "u")
    type_keys(engine, "df:")
    assert engine.state.lines == ("def",)


@pytest.mark.parametrize("lines", [("alpha",), ("alpha (beta",), ("alpha )beta",)])
@pytest.mark.parametrize("operator", ["d", "c", "y", "gU", ">"])
def test_failed_bracket_motion_does_not_apply_operator(
    lines: tuple[str, ...], operator: str
) -> None:
    initial = EditorState(lines, column=2)
    engine = EditEngine(initial)
    type_keys(engine, operator + "%")
    assert engine.state == initial
    assert not engine.snapshot().undo
    assert not engine.snapshot().registers


@pytest.mark.parametrize(
    ("row", "keys", "expected"),
    [
        (0, "d50%", ("gamma", "delta")),
        (3, "d50%", ("alpha",)),
        (0, "d100%", ("",)),
        (1, "d50%", ("alpha", "gamma", "delta")),
    ],
)
def test_percentage_operator_uses_complete_lines(
    row: int, keys: str, expected: tuple[str, ...]
) -> None:
    original = ("alpha", "beta", "gamma", "delta")
    engine = EditEngine(EditorState(original, row=row, column=2))
    type_keys(engine, keys)
    assert engine.state.lines == expected
    type_keys(engine, "u")
    assert engine.state.lines == original


@pytest.mark.parametrize("keys", ["101%", "d101%", "c101%", "2d99%"])
def test_percentage_above_one_hundred_is_rejected_without_editing(keys: str) -> None:
    initial = EditorState(("alpha", "beta"), column=2)
    engine = EditEngine(initial)
    type_keys(engine, keys[:-1])
    assert not engine.submit(KeyToken("char", "%")).accepted
    assert engine.state == initial


def test_line_scroll_can_expose_eof_without_jumping_back_after_zt() -> None:
    engine = EditEngine(EditorState(tuple(f"line {row}" for row in range(30))))
    engine.set_viewport(10)
    type_keys(engine, "Gzt")
    assert engine.state.viewport_top == 29
    chord(engine, "e")
    assert (engine.state.row, engine.state.viewport_top) == (29, 29)
    chord(engine, "y")
    assert (engine.state.row, engine.state.viewport_top) == (29, 28)
    type_keys(engine, "zb")
    chord(engine, "e")
    assert (engine.state.row, engine.state.viewport_top) == (29, 21)


@pytest.mark.parametrize(("position", "control"), [("Gzt", "d"), ("ggzb", "u")])
def test_half_page_scroll_at_buffer_boundary_preserves_view(
    position: str, control: str
) -> None:
    engine = EditEngine(EditorState(tuple(f"  line {row}" for row in range(30))))
    engine.set_viewport(10)
    type_keys(engine, position + "l")
    before = engine.state
    chord(engine, control)
    assert engine.state == before


def test_viewport_motion_uses_visible_row_count_and_z_positioning() -> None:
    engine = EditEngine(EditorState(tuple(f"line {row}" for row in range(60))))
    engine.set_viewport(10, 0)
    chord(engine, "d")
    assert engine.state.row == 5
    chord(engine, "u")
    assert engine.state.row == 0
    type_keys(engine, "21Gzt")
    assert engine.state.viewport_top == 20
    type_keys(engine, "L")
    assert engine.state.row == 29
    type_keys(engine, "H")
    assert engine.state.row == 20
    engine.set_viewport(6)
    chord(engine, "d")
    assert engine.state.row == 23


def test_half_screen_count_is_remembered_restored_and_clamped_on_resize() -> None:
    engine = EditEngine(EditorState(tuple(f"row {row}" for row in range(100)), row=30))
    engine.set_viewport(12, 24)
    type_keys(engine, "3")
    chord(engine, "d")
    assert engine.state.row == 33
    snapshot = engine.snapshot()
    type_keys(engine, "8")
    chord(engine, "u")
    assert engine.state.row == 25
    engine.restore(snapshot)
    chord(engine, "u")
    assert engine.state.row == 30
    engine.set_viewport(2)
    chord(engine, "d")
    assert engine.state.row == 32
    engine.set_viewport(20)
    chord(engine, "u")
    assert engine.state.row == 30


def test_marks_and_jump_history_keep_line_and_exact_column_distinct() -> None:
    engine = EditEngine(EditorState(("  abc", "def", "ghi"), column=4))
    type_keys(engine, "maG`a")
    assert (engine.state.row, engine.state.column) == (0, 4)
    type_keys(engine, "G'a")
    assert (engine.state.row, engine.state.column) == (0, 2)
    chord(engine, "o")
    assert engine.state.row == 2
    chord(engine, "i")
    assert engine.state.row == 0


def test_mark_follows_its_line_when_an_earlier_line_is_deleted() -> None:
    engine = EditEngine(EditorState(("one", "two", "three"), row=1))
    type_keys(engine, "maggdd`a")
    assert (engine.state.row, engine.state.column) == (0, 0)
    assert engine.state.lines[engine.state.row] == "two"
