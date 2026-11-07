"""Normal 편집의 전후 문서·undo·검색·선택 상태 회귀 예제."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState

ESC = KeyToken("special", "esc")
ENTER = KeyToken("special", "enter")
BACKSPACE = KeyToken("special", "backspace")


def type_keys(engine: EditEngine, text: str) -> None:
    for char in text:
        outcome = engine.submit(KeyToken("char", char))
        assert outcome.accepted, (text, char, outcome.message)


def chord(engine: EditEngine, value: str) -> None:
    outcome = engine.submit(KeyToken("chord", "ctrl+" + value))
    assert outcome.accepted, outcome.message


@pytest.mark.parametrize(
    ("lines", "row", "column", "keys", "expected"),
    [
        (("one two",), 0, 4, "d$", ("one ",)),
        (("one two",), 0, 4, "D", ("one ",)),
        (("one two",), 0, 4, "d0", ("two",)),
        (("one two",), 0, 4, "dh", ("onetwo",)),
        (("one two",), 0, 4, "db", ("two",)),
        (("one,two three",), 0, 8, "dB", ("three",)),
        (("  abc def",), 0, 6, "d^", ("  def",)),
        (("one", "two", "three"), 1, 0, "dG", ("one",)),
        (("one", "two", "three"), 1, 0, "dgg", ("three",)),
        (("a", "b", "c", "d"), 0, 0, "d2j", ("d",)),
        (("a", "b", "c", "d"), 0, 0, "d2G", ("c", "d")),
        (("one two three",), 0, 5, "daw", ("one three",)),
        (('a "two" b',), 0, 4, 'da"', ("a b",)),
        (("a (one (two)) z",), 0, 8, "di(", ("a (one ()) z",)),
        (("abcd",), 0, 1, "d2l", ("ad",)),
        (("(a(b)c) z",), 0, 0, "d%", (" z",)),
    ],
)
def test_operator_ranges_and_one_undo(
    lines: tuple[str, ...],
    row: int,
    column: int,
    keys: str,
    expected: tuple[str, ...],
) -> None:
    engine = EditEngine(EditorState(lines, row, column))
    type_keys(engine, keys)
    assert engine.state.lines == expected
    assert engine.state.mode == "normal"
    type_keys(engine, "u")
    assert engine.state.lines == lines
    chord(engine, "r")
    assert engine.state.lines == expected


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
        ("abc:def", 6, "dF:", "abcf"),
        ("abc:def", 6, "dT:", "abc:f"),
        ("abc:def", 0, "f:$d,", "abcf"),
        ("abc:def", 6, "T:$d;", "abc:f"),
        ("one two", 6, "dge", "on"),
        ("one two", 6, "dgE", "on"),
    ],
)
def test_backward_operator_motion_preserves_inclusive_or_exclusive_end(
    line: str, column: int, keys: str, expected: str
) -> None:
    engine = EditEngine(EditorState((line,), column=column))
    type_keys(engine, keys)
    assert engine.state.lines == (expected,)
    type_keys(engine, "u")
    assert engine.state.lines == (line,)


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
    ("lines", "column", "keys", "expected"),
    [
        (("abc",), 1, "2rX", ("aXX",)),
        (("Abc",), 0, "2~", ("aBc",)),
        (("one", "  two"), 0, "J", ("one two",)),
        (("one", "  two"), 0, "gJ", ("one  two",)),
        (("one", "two", "three"), 0, "3J", ("one two three",)),
        (("one two three",), 0, "dw.", ("three",)),
    ],
)
def test_simple_changes(
    lines: tuple[str, ...], column: int, keys: str, expected: tuple[str, ...]
) -> None:
    engine = EditEngine(EditorState(lines, column=column))
    type_keys(engine, keys)
    if engine.state.mode in {"insert", "replace"}:
        engine.submit(ESC)
    assert engine.state.lines == expected


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


def test_replace_backspace_restores_the_overwritten_character() -> None:
    engine = EditEngine(EditorState(("abcd",), column=1))
    type_keys(engine, "RXY")
    engine.submit(BACKSPACE)
    engine.submit(ESC)
    assert engine.state.lines == ("aXcd",)
    type_keys(engine, "u")
    assert engine.state.lines == ("abcd",)


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


def test_actual_ctrl_number_edit_and_count() -> None:
    engine = EditEngine(EditorState(("item = 19",)))
    type_keys(engine, "3")
    chord(engine, "a")
    assert engine.state.lines == ("item = 22",)
    chord(engine, "x")
    assert engine.state.lines == ("item = 21",)
    type_keys(engine, "2u")
    assert engine.state.lines == ("item = 19",)


def test_search_prompt_edit_cancel_wrap_and_repeat() -> None:
    engine = EditEngine(EditorState(("one two one", "one")))
    type_keys(engine, "/onex")
    assert engine.state.command_line == "/onex"
    engine.submit(BACKSPACE)
    engine.submit(ENTER)
    assert (engine.state.row, engine.state.column) == (0, 8)
    type_keys(engine, "n")
    assert (engine.state.row, engine.state.column) == (1, 0)
    type_keys(engine, "N")
    assert (engine.state.row, engine.state.column) == (0, 8)
    type_keys(engine, "/missing")
    engine.submit(ESC)
    assert not engine.state.pending
    assert not engine.state.command_line
    type_keys(engine, "n")
    assert (engine.state.row, engine.state.column) == (1, 0)


def test_search_and_find_history_are_restored_with_snapshot() -> None:
    engine = EditEngine(EditorState(("one two one",)))
    type_keys(engine, "/one")
    engine.submit(ENTER)
    snapshot = engine.snapshot()
    type_keys(engine, "/two")
    engine.submit(ENTER)
    engine.restore(snapshot)
    type_keys(engine, "n")
    assert engine.state.column == 0


def test_ex_substitution_and_line_jump() -> None:
    engine = EditEngine(EditorState(("cat cat", "cat cat")))
    type_keys(engine, ":%s/cat/dog/g")
    engine.submit(ENTER)
    assert engine.state.lines == ("dog dog", "dog dog")
    type_keys(engine, "u")
    assert engine.state.lines == ("cat cat", "cat cat")
    type_keys(engine, ":2")
    engine.submit(ENTER)
    assert engine.state.row == 1


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


def test_mark_follows_its_line_when_an_earlier_line_is_deleted() -> None:
    engine = EditEngine(EditorState(("one", "two", "three"), row=1))
    type_keys(engine, "maggdd`a")
    assert (engine.state.row, engine.state.column) == (0, 0)
    assert engine.state.lines[engine.state.row] == "two"


def test_counted_replace_past_line_end_is_an_unchanged_command() -> None:
    engine = EditEngine(EditorState(("abcd",), column=2))
    type_keys(engine, "3rX")
    assert engine.state.lines == ("abcd",)
    assert engine.state.mode == "normal"


def test_star_search_matches_whole_word_and_retains_direction() -> None:
    engine = EditEngine(EditorState(("one tone one", "one")))
    type_keys(engine, "*")
    assert (engine.state.row, engine.state.column) == (0, 9)
    type_keys(engine, "n")
    assert (engine.state.row, engine.state.column) == (1, 0)
    type_keys(engine, "#")
    assert (engine.state.row, engine.state.column) == (0, 9)
    type_keys(engine, "n")
    assert (engine.state.row, engine.state.column) == (0, 0)


def test_unsupported_ex_pattern_and_expression_never_change_document() -> None:
    engine = EditEngine(EditorState(("aaa",)))
    type_keys(engine, r":s/\(a\)/X/")
    assert not engine.submit(ENTER).accepted
    assert engine.state.lines == ("aaa",)
    type_keys(engine, r":s/a/\=run()/")
    assert not engine.submit(ENTER).accepted
    assert engine.state.lines == ("aaa",)
    assert not engine.state.pending
    assert not engine.state.command_line


def test_dot_does_not_repeat_an_ex_substitution() -> None:
    engine = EditEngine(EditorState(("a",)))
    type_keys(engine, ":s/a/aa/")
    engine.submit(ENTER)
    type_keys(engine, ".")
    assert engine.state.lines == ("aa",)


@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        ("0x0f", "0x10"),
        ("0x0E", "0x0F"),
        ("0X0e", "0X0f"),
        ("007", "010"),
        ("008", "9"),
        ("0b0111", "0b1000"),
        ("-0x01", "-0x02"),
        ("-007", "-010"),
    ],
)
def test_numeric_formats_keep_vim_prefix_case_sign_and_octal_rules(
    initial: str, expected: str
) -> None:
    engine = EditEngine(EditorState((initial,)))
    chord(engine, "a")
    assert engine.state.lines == (expected,)
    type_keys(engine, "u")
    assert engine.state.lines == (initial,)


@pytest.mark.parametrize(
    ("line", "column", "keys", "expected"),
    [
        ('a "two" b', 4, 'd2i"', "a  b"),
        ('a "two"', 4, 'da"', "a"),
        ("a (one (two)) z", 8, "d2i(", "a () z"),
    ],
)
def test_quote_whitespace_and_counted_nested_objects(
    line: str, column: int, keys: str, expected: str
) -> None:
    engine = EditEngine(EditorState((line,), column=column))
    type_keys(engine, keys)
    assert engine.state.lines == (expected,)


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("g~2w", "ONE two three"),
        ("gu2w", "one two three"),
        ("gU2w", "ONE TWO three"),
    ],
)
def test_case_operator_accepts_its_own_motion_count(keys: str, expected: str) -> None:
    engine = EditEngine(EditorState(("one TWO three",)))
    type_keys(engine, keys)
    assert engine.state.lines == (expected,)


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


@pytest.mark.parametrize("keys", ["d2aw", "c2aW", "y2aw", "2daw"])
def test_around_word_rejects_count_crossing_a_line_without_editing(keys: str) -> None:
    initial = EditorState(("one", "two three"))
    engine = EditEngine(initial)
    for char in keys[:-1]:
        assert engine.submit(KeyToken("char", char)).accepted
    outcome = engine.submit(KeyToken("char", keys[-1]))
    assert not outcome.accepted
    assert "줄을 넘는" in outcome.message
    assert engine.state == initial
    assert not engine.snapshot().undo
    assert not engine.snapshot().registers


def test_around_word_keeps_same_line_count_and_eof_clipping() -> None:
    same_line = EditEngine(EditorState(("one two three", "next")))
    type_keys(same_line, "d2aw")
    assert same_line.state.lines == ("three", "next")
    eof = EditEngine(EditorState(("one",)))
    type_keys(eof, "d2aw")
    assert eof.state.lines == ("",)


def test_around_word_on_space_includes_the_following_word() -> None:
    engine = EditEngine(EditorState(("one   two three",), column=4))
    type_keys(engine, "daw")
    assert engine.state.lines == ("one three",)


def test_quote_objects_use_odd_even_backslash_escape_parity() -> None:
    even = EditEngine(EditorState((r'path = "C:\\" tail',), column=9))
    type_keys(even, 'di"')
    assert even.state.lines == ('path = "" tail',)
    odd = EditEngine(EditorState((r'path = "a\"b" tail',), column=9))
    type_keys(odd, 'di"')
    assert odd.state.lines == ('path = "" tail',)


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
