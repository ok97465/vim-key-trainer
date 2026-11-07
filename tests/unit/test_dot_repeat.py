"""변경 반복은 저장된 한 명령의 문맥과 삽입 문자열을 보존한다."""

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import ESC, characters
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditEngine, EditorState


def _type(engine: EditEngine, text: str) -> None:
    for token in characters(text):
        assert engine.submit(token).accepted


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
    _type(engine, "j0")
    before = engine.snapshot()
    _type(engine, "..")
    assert engine.state == before.state
    assert engine.snapshot().last_change == change
    _type(engine, "j0.")
    assert engine.state.lines == (text + " tail", "plain line", text + " tail")
    assert engine.snapshot().last_change == change
    _type(engine, "u")
    assert engine.state.lines[2] == "next? tail"


def test_consecutive_dots_keep_replaying_the_original_change_after_movements() -> None:
    engine = EditEngine(EditorState(("one two three", "four five six")))
    change = characters("ciwX") + (ESC,)
    for token in change:
        assert engine.submit(token).accepted
    _type(engine, "w.w.j0.w.w.")
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
    _type(probe, "j0.")
    assert probe.state.lines == ("p.r tail", "plain line", "next? tail")
    assert probe.state.mode == "normal" and not probe.state.pending
    assert guide.engine.snapshot() == snapshot
    guide.navigate(2, 0)
    guide.record(characters("."), "앞의 변경을 반복합니다.")
    assert guide.engine.state.lines == ("p.r tail", "plain line", "p.r tail")
    assert guide.engine.snapshot().last_change == change
