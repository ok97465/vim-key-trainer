"""Normal 명령의 문서 변경 범위와 지원·입력 경계 회귀."""

# Third party imports
import pytest
from engine_support import ESC, REDO, chord, type_keys

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState


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
    assert engine.state == initial


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


@pytest.mark.parametrize(
    ("initial", "keys", "lines", "position"),
    [
        (EditorState(("one,two three",)), "dW", ("three",), (0, 0)),
        (EditorState(("one,two three",)), "de", (",two three",), (0, 0)),
        (EditorState(("one,two three",)), "dE", (" three",), (0, 0)),
        (EditorState(("one,two three",)), "d2e", ("two three",), (0, 0)),
        (EditorState(("one,two three",)), "2de", ("two three",), (0, 0)),
        (EditorState(("one,two three",)), "diw", (",two three",), (0, 0)),
        (EditorState(("one,two three",)), "diW", (" three",), (0, 0)),
        (EditorState(("one,two three",), column=5), "diw", ("one, three",), (0, 4)),
        (EditorState(("one,two three",), column=5), "diW", (" three",), (0, 0)),
        (EditorState(("one,+two",), column=4), "diw", ("onetwo",), (0, 3)),
        (EditorState(("one  two three",)), "d2iw", ("two three",), (0, 0)),
        (EditorState(("one  two three",)), "d3iw", (" three",), (0, 0)),
        (EditorState(("one  two three",), column=4), "diw", ("onetwo three",), (0, 3)),
        (EditorState(("one two three",)), "2d2iw", ("three",), (0, 0)),
        (EditorState(("a b c d e f keep",)), "2d3W", ("keep",), (0, 0)),
        (EditorState(("aa bb cc dd ee ff keep",)), "2d3E", (" keep",), (0, 0)),
        (EditorState(("one   ", "  two"), column=3), "dW", ("one", "  two"), (0, 2)),
        (EditorState(("one   ", "  two"), column=3), "dw", ("one", "  two"), (0, 2)),
        (EditorState(("   ", "two")), "dW", ("", "two"), (0, 0)),
        (EditorState(("   ", "two")), "dw", ("", "two"), (0, 0)),
        (EditorState(("", "  two")), "dW", ("  two",), (0, 2)),
        (EditorState(("one", "two")), "dW", ("", "two"), (0, 0)),
        (EditorState(("one", "two")), "2dW", ("",), (0, 0)),
        (EditorState(("one", "two three")), "2dE", (" three",), (0, 0)),
        (EditorState(("one", "two")), "2dE", ("",), (0, 0)),
        (EditorState(("one", "two"), column=1), "2de", ("o",), (0, 0)),
        (EditorState(("one   ", ""), column=4), "de", ("one ",), (0, 3)),
        (EditorState(("one", "two three")), "d2iw", (" three",), (0, 0)),
        (EditorState(("one   ", "  two three")), "d2iw", ("", "  two three"), (0, 0)),
        (EditorState(("one", "", "two")), "d2iw", ("two",), (0, 0)),
        (EditorState(("one", "", "two")), "d3iw", ("",), (0, 0)),
        (EditorState(("", "two")), "diw", ("", "two"), (0, 0)),
        (EditorState(("", "two")), "d2iw", ("",), (0, 0)),
        (EditorState(("one", ""), row=1), "diw", ("on",), (0, 1)),
        (EditorState(("",)), "diW", ("",), (0, 0)),
        (EditorState(("one two",)), "d99iw", ("one two",), (0, 6)),
    ],
)
def test_word_deletion_ranges_and_cursors(
    initial: EditorState,
    keys: str,
    lines: tuple[str, ...],
    position: tuple[int, int],
) -> None:
    engine = EditEngine(initial)
    type_keys(engine, keys)
    assert engine.state.lines == lines
    assert (engine.state.row, engine.state.column) == position
    assert engine.state.mode == "normal"
    assert engine.state.pending == ""


def test_inner_object_allowlist_and_invalid_suffixes_do_not_delete() -> None:
    initial = EditorState(("one,two three",), column=2)
    engine = EditEngine(initial, frozenset({"diW"}))
    type_keys(engine, "di")
    assert not engine.submit(KeyToken("char", "w")).accepted
    assert engine.state == initial
    type_keys(engine, "diW")
    assert engine.state.lines == (" three",)
    for suffix in ("2", "z", "i", "f"):
        engine = EditEngine(initial)
        type_keys(engine, "di")
        assert not engine.submit(KeyToken("char", suffix)).accepted
        assert engine.state == initial


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


def test_counted_replace_past_line_end_is_an_unchanged_command() -> None:
    engine = EditEngine(EditorState(("abcd",), column=2))
    type_keys(engine, "3rX")
    assert engine.state.lines == ("abcd",)
    assert engine.state.mode == "normal"


def test_actual_ctrl_number_edit_and_count() -> None:
    engine = EditEngine(EditorState(("item = 19",)))
    type_keys(engine, "3")
    chord(engine, "a")
    assert engine.state.lines == ("item = 22",)
    chord(engine, "x")
    assert engine.state.lines == ("item = 21",)
    type_keys(engine, "2u")
    assert engine.state.lines == ("item = 19",)


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
