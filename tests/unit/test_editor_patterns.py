"""Vim pattern.txt·change.txt의 검색 및 안전한 Ex 치환 예제."""

# Third party imports
import pytest

# Local imports
from vim_key_trainer.engine.patterns import compile_pattern, find_match, substitute


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
def test_substitution_errors_do_not_mutate(command: str) -> None:
    lines = ("x", "x")
    with pytest.raises(ValueError):
        substitute(lines, command, 0)
    assert lines == ("x", "x")


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
