"""가이드 이동은 문자 수 대신 단어·찾기·검색을 사용하고 정확히 도착한다."""

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState


def _verify_navigation(
    builder: GuideBuilder, initial: EditorState, row: int, column: int
) -> set[str]:
    replay = EditEngine(initial, builder.engine.allowed_commands)
    commands: set[str] = set()
    for step in builder.steps:
        for key in step.keys:
            pending = replay.state.pending
            outcome = replay.submit(key)
            assert outcome.accepted
            if outcome.command:
                commands.add(outcome.command)
            if outcome.command in {"h", "l"}:
                assert int(pending or "1") <= 2
        assert replay.state == step.expected
    assert replay.state.lines == initial.lines
    assert (replay.state.row, replay.state.column) == (row, column)
    assert replay.state.mode == "normal"
    assert not replay.state.pending
    return commands


@pytest.mark.parametrize(
    ("line", "column"),
    [
        ("alpha beta gamma delta epsilon zeta eta theta", 17),
        ("a very_long_identifier_with_a_marker_inside = enabled", 27),
        ("one/path two-name three:data four=value five", 30),
        (" ".join(f"word{index}" for index in range(50)), 153),
        (r"a.*[b]\path~^$ = value", 3),
    ],
)
def test_long_horizontal_movement_never_asks_for_large_character_counts(
    line: str, column: int
) -> None:
    initial = EditorState((line,))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    builder.navigate(0, column)
    _verify_navigation(builder, initial, 0, column)


@pytest.mark.parametrize(
    ("line", "column", "command", "expected"),
    [
        ("aa/bb cc-dd ee:ff gg=hh ii", 24, "W", "4W"),
        ("alpha beta gamma delta epsilon", 15, "e", "3e"),
    ],
)
def test_counted_word_and_end_motions_reach_visible_word_boundaries(
    line: str, column: int, command: str, expected: str
) -> None:
    initial = EditorState((line,))
    builder = GuideBuilder(initial, frozenset({command}))
    builder.navigate(0, column)
    assert _verify_navigation(builder, initial, 0, column) == {command}
    assert (
        "".join(key.display for step in builder.steps for key in step.keys) == expected
    )


def test_search_uses_actual_enter_and_escapes_vim_magic_characters() -> None:
    initial = EditorState(("first", r"prefix a.*[b]\path~^$ suffix", "last"))
    builder = GuideBuilder(initial, frozenset({"/"}))
    builder.navigate(1, 7)
    assert _verify_navigation(builder, initial, 1, 7) == {"/"}
    assert builder.steps[0].keys[-1] == KeyToken("special", "enter")


def test_search_can_disambiguate_repeated_fragments_on_the_same_line() -> None:
    initial = EditorState(("target target target target end",))
    builder = GuideBuilder(initial, frozenset({"/", "?"}))
    builder.navigate(0, 14)
    assert _verify_navigation(builder, initial, 0, 14) <= {"/", "?"}


def test_matching_bracket_motion_is_available_in_real_guide_navigation() -> None:
    initial = EditorState(("config = {", "  nested = (42)", "}"), column=9)
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    builder.navigate(2, 0)
    assert _verify_navigation(builder, initial, 2, 0) == {"%"}


@pytest.mark.parametrize("opening,closing", [("(", ")"), ("[", "]"), ("{", "}")])
def test_matching_bracket_can_be_followed_by_a_word_motion(
    opening: str, closing: str
) -> None:
    line = (
        f"prefix {opening}one {opening}two three{closing} four{closing} target suffix"
    )
    initial = EditorState((line,))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    column = line.index("target")
    builder.navigate(0, column)
    commands = _verify_navigation(builder, initial, 0, column)
    assert "%" in commands
    assert commands & {"w", "W"}


def test_navigation_respects_allowed_commands_instead_of_using_hidden_motions() -> None:
    initial = EditorState(("alpha beta gamma delta epsilon",))
    builder = GuideBuilder(initial, frozenset({"h", "l"}))
    with pytest.raises(ValueError, match="허용 명령"):
        builder.navigate(0, 17)
    assert builder.engine.state == initial
    assert not builder.steps


def test_navigating_to_current_position_does_not_add_an_empty_step() -> None:
    initial = EditorState(("alpha beta",), column=4)
    builder = GuideBuilder(initial, frozenset())
    builder.navigate(0, 4)
    assert not builder.steps
    assert builder.engine.state == initial


@pytest.mark.parametrize(
    ("line", "target"),
    [
        ("first second third fourth fifth target sixth seventh", "target"),
        ("left = one; middle = two; right = three;", "right"),
        ('config = {"alpha": "old", "beta": "target", "gamma": 3}', "target"),
    ],
)
def test_visible_landmarks_replace_counting_many_words(line: str, target: str) -> None:
    initial = EditorState((line,))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    column = line.index(target)
    builder.navigate(0, column)
    commands = _verify_navigation(builder, initial, 0, column)
    assert commands & {"f", "F", "t", "T", ";", ",", "/", "?"}
    replay = EditEngine(initial)
    for step in builder.steps:
        for key in step.keys:
            pending = replay.state.pending
            outcome = replay.submit(key)
            if outcome.command in {"w", "W", "e", "E", "b", "B"}:
                assert int(pending or "1") <= 3
    assert target in builder.steps[0].text
    assert "열" not in builder.steps[0].text


def test_repeated_delimiters_are_followed_with_semicolon_instead_of_an_ordinal() -> (
    None
):
    initial = EditorState(("a,b,c,d,e",))
    builder = GuideBuilder(initial, frozenset({"f", ";"}))
    builder.navigate(0, 5)
    assert _verify_navigation(builder, initial, 0, 5) == {"f", ";"}
    assert tuple(key.value for key in builder.steps[0].keys) == ("f", ",", ";", ";")


def test_find_history_is_reused_in_both_directions_across_guide_steps() -> None:
    initial = EditorState(("a,b,c,d",))
    builder = GuideBuilder(initial, frozenset({"f", ";", ","}))
    builder.record((KeyToken("char", "f"), KeyToken("char", ",")), "쉼표 찾기")
    for column, expected in ((3, ";"), (1, ","), (5, ";;")):
        builder.navigate(0, column)
        assert "".join(key.value for key in builder.steps[-1].keys) == expected
    _verify_navigation(builder, initial, 0, 5)
    assert builder.engine.last_find == ("f", ",")
    assert all("f," in step.text for step in builder.steps[1:])


def test_semicolon_without_find_history_is_not_offered() -> None:
    builder = GuideBuilder(EditorState(("a,b,c",)), frozenset({";"}))
    with pytest.raises(ValueError, match="허용 명령"):
        builder.navigate(0, 3)
    assert not builder.steps


def test_search_uses_a_readable_word_instead_of_a_fixed_length_fragment() -> None:
    initial = EditorState(("prefix recognisable_identifier suffix",))
    builder = GuideBuilder(initial, frozenset({"/"}))
    builder.navigate(0, 7)
    _verify_navigation(builder, initial, 0, 7)
    assert "".join(key.value for key in builder.steps[0].keys[1:-1]) == (
        "recognisable_identifier"
    )


def test_search_for_an_interior_letter_starts_with_the_whole_identifier() -> None:
    line = "prefix recognisable_identifier suffix"
    initial = EditorState(("header", line))
    builder = GuideBuilder(initial, frozenset({"/", "f"}))
    column = line.index("identifier")
    builder.navigate(1, column)
    _verify_navigation(builder, initial, 1, column)
    keys = builder.steps[0].keys
    assert keys[0] == KeyToken("char", "/")
    end = keys.index(KeyToken("special", "enter"))
    assert "".join(key.value for key in keys[1:end]) == "recognisable_identifier"


def test_indistinguishable_character_position_does_not_create_a_counting_regex() -> (
    None
):
    initial = EditorState(("a" * 80,))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    with pytest.raises(ValueError, match="허용 명령"):
        builder.navigate(0, 17)
    assert builder.engine.state == initial
    assert not builder.steps
