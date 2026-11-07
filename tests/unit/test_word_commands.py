"""Vim motion.txt의 word/WORD·iw/iW와 change.txt의 삭제 범위 회귀."""

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState

ESC = KeyToken("special", "esc")
REDO = KeyToken("chord", "ctrl+r")


def type_keys(engine: EditEngine, keys: str) -> None:
    for key in keys:
        outcome = engine.submit(KeyToken("char", key))
        assert outcome.accepted, (key, outcome.message)


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


def test_inner_object_count_limit_cancels_before_applying_delete() -> None:
    initial = EditorState(("one two three",))
    engine = EditEngine(initial)
    type_keys(engine, "99d9")
    assert not engine.submit(KeyToken("char", "9")).accepted
    assert engine.state == initial


def test_word_motion_does_not_add_history_or_discard_redo() -> None:
    engine = EditEngine(EditorState(("one,two three",)))
    type_keys(engine, "diwuWEB")
    engine.submit(REDO)
    assert engine.state.lines == (",two three",)
