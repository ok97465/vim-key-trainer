"""Vim 검색 문법·대화형 입력과 안전한 메모리 Ex 치환 회귀."""

# Third party imports
import pytest
from engine_support import BACKSPACE, ENTER, ESC, type_keys

# Local imports
from vim_key_trainer.engine import EditEngine, EditorState
from vim_key_trainer.engine.patterns import compile_pattern, find_match, substitute


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


def test_search_wrap_direction_count_and_whole_word() -> None:
    lines = ("one tone one", "one")
    assert find_match(lines, 0, 0, r"\<one\>") == (0, 9)
    assert find_match(lines, 0, 9, r"\<one\>", count=2) == (0, 0)
    assert find_match(lines, 0, 0, r"\<one\>", forward=False) == (1, 0)
    assert find_match(lines, 0, 0, "missing") is None
    assert find_match(("one",), 0, 0, "one") == (0, 0)
    assert find_match(("banana",), 0, 1, "ana") == (0, 3)


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        (r"a+b", "a+b", True),
        (r"a\+b", "aaab", True),
        (r"file\.py$", "file.py", True),
        (r"[A-Z]\{2,3}", "ABC", True),
        (r"\cword", "WORD", True),
        (r"\cword\C", "WORD", True),
        (r"\Cword", "WORD", False),
        (r"\c^word$", "WORD", True),
        (r"\d\+", "123", True),
        (r"^a.*b$", "a123b", True),
        (r"x(y)|z", "x(y)|z", True),
    ],
)
def test_vim_magic_semantics(pattern: str, text: str, expected: bool) -> None:
    assert bool(compile_pattern(pattern).fullmatch(text)) is expected


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "[",
        "x\\",
        r"\(x\)",
        r"x\|y",
        r"x\&y",
        r"\zsx",
        r"\1",
        "a*a*",
        r"\{2}x",
        r"x\{1000}",
        r"[[:alpha:]]",
        "~",
    ],
)
def test_unsupported_or_unsafe_patterns_are_rejected(pattern: str) -> None:
    with pytest.raises(ValueError):
        compile_pattern(pattern)


def test_substitution_defaults_to_current_line_first_occurrence() -> None:
    lines = ("cat cat", "cat cat")
    assert substitute(lines, ":s/cat/dog/", 1) == (("cat cat", "dog cat"), 1)
    assert substitute(lines, ":%s/cat/dog/g", 1) == (("dog dog", "dog dog"), 4)
    assert substitute(lines, ":1,2s/cat/dog/", 1) == (("dog cat", "dog cat"), 2)
    assert substitute(lines, ":.,$s/cat/dog/", 1) == (("cat cat", "dog cat"), 1)


def test_substitution_delimiters_case_and_replacement_escapes() -> None:
    assert substitute(("a/b A/B",), r":s/a\/b/[&]/gi", 0) == (("[a/b] [A/B]",), 2)
    assert substitute(("cat",), r":s#cat#\&\\&#", 0) == (("&\\cat",), 1)
    assert substitute(("Cat",), ":s/cat$/dog/i", 0) == (("dog",), 1)
    assert substitute(("Cat",), r":s/\Ccat/dog/i", 0) == (("Cat",), 0)
    assert substitute(("Cat",), r":s/\ccat/dog/I", 0) == (("dog",), 1)
    assert substitute(("cat",), r":s/cat/\~/", 0) == (("~",), 1)


@pytest.mark.parametrize(
    "command",
    [
        ":w",
        ":!ls",
        ":s/x/y/c",
        ":s/x/\\=run/",
        ":s/x/\\1/",
        ":0s/x/y/",
        ":3s/x/y/",
        ":2,1s/x/y/",
        ":s//y/",
        ":s/x/y",
        ":s/x/y/ii",
        ":s/x/~/",
    ],
)
def test_invalid_substitutions_are_rejected(command: str) -> None:
    lines = ("x", "x")
    with pytest.raises(ValueError):
        substitute(lines, command, 0)


@pytest.mark.parametrize(
    ("line", "command", "expected"),
    [
        ("axb a.b", r":s.a\.b.X.", "axb X"),
        ("aaab a+b", r":s+a\+b+X+", "aaab X"),
        ("ab a*b", r":s*a\*b*X*", "ab X"),
        ("a", r":s&a&\&&", "&"),
        ("a", r":s~a~\~~", "~"),
        ("a", r":s#a#\##", "#"),
    ],
)
def test_escaped_substitution_delimiters_stay_literal(
    line: str, command: str, expected: str
) -> None:
    assert substitute((line,), command, 0) == ((expected,), 1)
