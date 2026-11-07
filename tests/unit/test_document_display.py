"""문자 범위·빈 경계와 구문 색상의 독립성 회귀 검증."""

# Standard library imports
from difflib import SequenceMatcher

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.document_display import (
    TextSpan,
    compare_documents,
    lexical_spans,
)


def test_replacement_highlights_only_changed_characters() -> None:
    diff = compare_documents(("limit = 15", "unchanged"), ("limit = 42", "unchanged"))
    assert diff.current_spans == (TextSpan(0, 8, 10, "replace"),)
    assert diff.goal_spans == (TextSpan(0, 8, 10, "replace"),)
    assert diff.remaining_count == 1
    assert diff == compare_documents(
        ("limit = 15", "unchanged"), ("limit = 42", "unchanged")
    )


@pytest.mark.parametrize(
    ("current", "goal", "current_span", "goal_span", "kind"),
    [
        (
            ("one", "three"),
            ("one", "two", "three"),
            TextSpan(1, 0, 0, "insert"),
            TextSpan(1, 0, 3, "insert"),
            "insert",
        ),
        (
            ("one", "two", "three"),
            ("one", "three"),
            TextSpan(1, 0, 3, "delete"),
            TextSpan(1, 0, 0, "delete"),
            "delete",
        ),
        (
            ("one", ""),
            ("one",),
            TextSpan(1, 0, 0, "delete"),
            TextSpan(0, 3, 3, "delete"),
            "delete",
        ),
        (
            ("one",),
            ("one", ""),
            TextSpan(0, 3, 3, "insert"),
            TextSpan(1, 0, 0, "insert"),
            "insert",
        ),
        (
            ("one", "three"),
            ("one", "", "three"),
            TextSpan(1, 0, 0, "insert"),
            TextSpan(1, 0, 0, "insert"),
            "insert",
        ),
        (
            ("remove",),
            ("",),
            TextSpan(0, 0, 6, "delete"),
            TextSpan(0, 0, 0, "delete"),
            "delete",
        ),
    ],
)
def test_insertions_deletions_and_empty_lines_have_visible_counterpart_anchors(
    current: tuple[str, ...],
    goal: tuple[str, ...],
    current_span: TextSpan,
    goal_span: TextSpan,
    kind: str,
) -> None:
    diff = compare_documents(current, goal)
    assert diff.remaining_count == 1
    assert diff.regions[0].kind == kind
    assert diff.current_spans == (current_span,)
    assert diff.goal_spans == (goal_span,)


def test_resolving_regions_updates_remaining_diff_without_changing_goals() -> None:
    current = ("a = 10", "keep", "b = 20", "keep again", "c = 30")
    goal = ("a = 11", "keep", "b = 21", "keep again", "c = 31")
    assert compare_documents(current, goal).remaining_count == 3
    partial = goal[:1] + current[1:]
    assert compare_documents(partial, goal).remaining_count == 2
    assert compare_documents(goal, goal).remaining_count == 0
    assert goal[0] == "a = 11"


def test_multiple_replacements_on_one_line_keep_unmodified_gap_uncolored() -> None:
    diff = compare_documents(("AAA middle BBB",), ("ccc middle ddd",))
    assert diff.remaining_count == 2
    assert diff.goal_spans == (
        TextSpan(0, 0, 3, "replace"),
        TextSpan(0, 11, 14, "replace"),
    )


def test_empty_document_and_missing_document_boundary() -> None:
    assert compare_documents(("",), ("",)).regions == ()
    with pytest.raises(ValueError, match="최소 한 줄"):
        compare_documents((), ("",))


def test_python_token_colors_do_not_execute_source() -> None:
    lines = ("def run(value=12):", '    return "class 99"  # while 42')
    spans = lexical_spans(lines, "python")
    assert TextSpan(0, 0, 3, "keyword") in spans
    assert TextSpan(0, 14, 16, "number") in spans
    assert TextSpan(1, 4, 10, "keyword") in spans
    assert TextSpan(1, 11, 21, "string") in spans
    assert TextSpan(1, 23, 33, "comment") in spans
    assert not any(
        span.role == "keyword" and span.start > 10 for span in spans if span.row == 1
    )


def test_python_multiline_string_and_incomplete_input_stay_in_document_bounds() -> None:
    lines = ('value = """first', 'last"""', "result = (")
    spans = lexical_spans(lines, "python")
    assert TextSpan(0, 8, 16, "string") in spans
    assert TextSpan(1, 0, 7, "string") in spans
    assert all(span.end <= len(lines[span.row]) for span in spans)
    assert lexical_spans(("def partial(",), "python")


def test_cpp_lexical_layers_handle_comments_multiline_and_raw_strings() -> None:
    lines = (
        "#include <vector>",
        'int count = 42; // return "x"',
        'auto text = R"tag(class',
        'return)tag";',
        "/* if",
        "while */ return count;",
    )
    spans = lexical_spans(lines, "cpp")
    assert TextSpan(0, 0, 17, "preprocessor") in spans
    assert TextSpan(1, 0, 3, "keyword") in spans
    assert TextSpan(1, 12, 14, "number") in spans
    assert TextSpan(2, 12, len(lines[2]), "string") in spans
    assert TextSpan(3, 0, 11, "string") in spans
    assert TextSpan(4, 0, 5, "comment") in spans
    assert TextSpan(5, 0, 8, "comment") in spans
    assert not any(span.role == "keyword" and span.row in {3, 4} for span in spans)


def test_markdown_can_dispatch_fenced_python_and_cpp_coloring() -> None:
    lines = (
        "# Title",
        "`inline`",
        "```python",
        "return 12",
        "```",
        "```cpp",
        "int value = 5;",
        "```",
    )
    spans = lexical_spans(lines, "markdown")
    assert TextSpan(0, 0, 7, "heading") in spans
    assert TextSpan(1, 0, 8, "string") in spans
    assert TextSpan(3, 0, 6, "keyword") in spans
    assert TextSpan(6, 0, 3, "keyword") in spans
    assert lexical_spans(lines, "text") == ()


def test_diff_background_ranges_are_independent_from_syntax_foreground() -> None:
    current = ("return 12",)
    goal = ("return 34",)
    diff = compare_documents(current, goal)
    assert TextSpan(0, 7, 9, "replace") in diff.goal_spans
    assert TextSpan(0, 7, 9, "number") in lexical_spans(goal, "python")
    assert compare_documents(current, goal) is diff


@pytest.mark.parametrize("row,start,end", [(0, 2, 1), (-1, 0, 1), (0, -1, 0)])
def test_invalid_display_ranges_are_rejected(row: int, start: int, end: int) -> None:
    with pytest.raises(ValueError):
        TextSpan(row, start, end, "replace")


def test_long_common_edges_are_excluded_from_character_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aligned: list[tuple[str, str]] = []
    original = SequenceMatcher.get_opcodes

    def trace_alignment(
        matcher: SequenceMatcher[str],
    ) -> list[tuple[str, int, int, int, int]]:
        if isinstance(matcher.a, str) and isinstance(matcher.b, str):
            aligned.append((matcher.a, matcher.b))
        return original(matcher)

    monkeypatch.setattr(SequenceMatcher, "get_opcodes", trace_alignment)
    prefix, suffix = "a" * 2_000, "b" * 2_000
    diff = compare_documents((prefix + "X" + suffix,), (prefix + "Y" + suffix,))
    assert aligned == [("X", "Y")]
    assert diff.current_spans == (TextSpan(0, 2_000, 2_001, "replace"),)
    assert diff.goal_spans == (TextSpan(0, 2_000, 2_001, "replace"),)


def test_large_different_interiors_have_bounded_alignment_and_keep_equal_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = SequenceMatcher.get_opcodes

    def forbid_large_character_alignment(
        matcher: SequenceMatcher[str],
    ) -> list[tuple[str, int, int, int, int]]:
        assert not isinstance(matcher.a, str)
        return original(matcher)

    monkeypatch.setattr(
        SequenceMatcher, "get_opcodes", forbid_large_character_alignment
    )
    current = "begin:" + "ab" * 1_000 + ":end"
    goal = "begin:" + "ba" * 1_000 + ":end"
    diff = compare_documents((current,), (goal,))
    assert diff.remaining_count == 1
    assert diff.current_spans == (TextSpan(0, 6, 2_006, "replace"),)
    assert diff.goal_spans == (TextSpan(0, 6, 2_006, "replace"),)


def test_repeated_equal_rows_are_excluded_from_line_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aligned: list[tuple[object, object]] = []
    original = SequenceMatcher.get_opcodes

    def trace_alignment(
        matcher: SequenceMatcher[str],
    ) -> list[tuple[str, int, int, int, int]]:
        if not isinstance(matcher.a, str):
            aligned.append((matcher.a, matcher.b))
        return original(matcher)

    monkeypatch.setattr(SequenceMatcher, "get_opcodes", trace_alignment)
    edges = ("unchanged repeated row",) * 1_000
    diff = compare_documents(edges + ("old",) + edges, edges + ("new",) + edges)
    assert aligned == [(("old",), ("new",))]
    assert diff.current_spans == (TextSpan(1_000, 0, 3, "replace"),)
    assert diff.goal_spans == (TextSpan(1_000, 0, 3, "replace"),)


def test_large_row_interiors_skip_quadratic_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = SequenceMatcher.get_opcodes

    def forbid_large_line_alignment(
        matcher: SequenceMatcher[str],
    ) -> list[tuple[str, int, int, int, int]]:
        if not isinstance(matcher.a, str):
            assert len(matcher.a) * len(matcher.b) <= 100_000
        return original(matcher)

    monkeypatch.setattr(SequenceMatcher, "get_opcodes", forbid_large_line_alignment)
    current = ("keep start",) + ("old", "same") * 500 + ("keep end",)
    goal = ("keep start",) + ("new", "same") * 500 + ("keep end",)
    diff = compare_documents(current, goal)
    assert diff.remaining_count == 500
    assert all(span.row % 2 == 1 for span in diff.current_spans)
    assert all(span.role == "replace" for span in diff.current_spans)


@pytest.mark.parametrize(
    ("current", "goal", "goal_rows"),
    [
        (("one", "two"), ("one", "two"), (0, 1)),
        (("one", "three"), ("one", "two", "three"), (0, 2)),
        (("one", "two", "three"), ("one", "three"), (0, 1, 1)),
        (("remove", "one"), ("one",), (0, 0)),
        (("one", "remove"), ("one",), (0, 0)),
        (("one",), ("add", "one"), (1,)),
        (("one",), ("one", "add"), (0,)),
        (
            ("start", "old one", "old two", "end"),
            ("start", "new", "end"),
            (0, 1, 1, 2),
        ),
        (("", ""), ("",), (0, 0)),
    ],
)
def test_row_mapping_keeps_corresponding_context_after_line_changes(
    current: tuple[str, ...], goal: tuple[str, ...], goal_rows: tuple[int, ...]
) -> None:
    assert compare_documents(current, goal).goal_rows == goal_rows


def test_repeated_equal_rows_keep_mapping_after_goal_insertion() -> None:
    edges = ("repeated mapping context",) * 1_000
    diff = compare_documents(edges + ("old",) + edges, edges + ("new", "added") + edges)
    assert diff.goal_rows == tuple(range(1_001)) + tuple(range(1_002, 2_002))
