"""무작위 문법 조합이 여러 화면 동안 이어지는 GUI 회귀 검증."""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.command_generator import get_command_profile
from vim_key_trainer.domain.commands import CommandSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.command_session import ContinuousCommandSession
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.command_practice import CommandPracticePage


@pytest.fixture
def page(qtbot: QtBot) -> Iterator[CommandPracticePage]:
    widget = CommandPracticePage(MemoryResultRepository())
    qtbot.addWidget(widget)
    profile = get_command_profile("commands_random")
    widget.prepare(profile, CommandSpec(profile.id, seed=127))
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    qtbot.mouseClick(widget.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(widget.practice_input.hasFocus)
    yield widget
    widget.close()


def press_token(page: CommandPracticePage, qtbot: QtBot, token: KeyToken) -> None:
    if token.kind == "char":
        qtbot.keyClicks(page.practice_input, token.value)
    elif token.kind == "special":
        qtbot.keyClick(
            page.practice_input,
            {
                "esc": Qt.Key.Key_Escape,
                "enter": Qt.Key.Key_Return,
                "backspace": Qt.Key.Key_Backspace,
                "tab": Qt.Key.Key_Tab,
            }[token.value],
        )
    else:
        assert token.value == "ctrl+r"
        modifier = (
            Qt.KeyboardModifier.MetaModifier
            if sys.platform == "darwin"
            else Qt.KeyboardModifier.ControlModifier
        )
        qtbot.keyClick(page.practice_input, Qt.Key.Key_R, modifier)


def complete_current(page: CommandPracticePage, qtbot: QtBot) -> str:
    session = page.session
    assert isinstance(session, ContinuousCommandSession)
    item = session.items[session.command_index]
    for token in item.tokens[session.token_index :]:
        press_token(page, qtbot, token)
    return item.display


def test_random_commands_continue_past_one_hundred_without_automatic_result(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = page.session
    assert isinstance(session, ContinuousCommandSession)
    first_page = session.items
    displays = [complete_current(page, qtbot) for _ in range(105)]
    assert len(set(displays)) > 40
    assert session.completed_commands == 105
    assert session.items != first_page
    assert len(session.items) == session.lesson.display_count
    assert session.state == SessionState.RUNNING
    assert session.combo == session.position
    assert session.incorrect == 0
    assert page.stack.currentWidget() is page.practice_page
    assert page.practice_input.hasFocus()
    assert page.repository.completed_count == 0
    assert page.last_result is None
    assert "105" in page.metrics["progress"].text()
    qtbot.mouseClick(page.finish_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.COMPLETED
    assert page.stack.currentWidget() is page.result_page
    assert page.last_result is not None
    assert page.last_result.completed_commands == 105
    assert len(page.last_result.command_samples) <= 100
    assert page.repository.completed_count == 1
    assert page.result_times.text()
    assert all(display in page.result_times.text() for display in displays[-100:])


def test_inline_hint_and_combo_survive_refill_then_mistake_keeps_target(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = page.session
    assert isinstance(session, ContinuousCommandSession)
    for _ in range(session.lesson.display_count):
        complete_current(page, qtbot)
    assert session.command_index == 0
    assert session.combo == session.position
    current = session.items[0]
    assert current.brief_meaning in page.practice_input.accessibleDescription()
    wrong = "!" if current.tokens[0] != KeyToken("char", "!") else "?"
    before = session.position
    qtbot.keyClicks(page.practice_input, wrong)
    assert current.brief_meaning in page.practice_input.accessibleDescription()
    assert session.position == before
    assert session.incorrect == 1
    assert session.combo == 0


def test_finish_midcommand_keeps_typing_until_that_command_is_complete(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = page.session
    assert isinstance(session, ContinuousCommandSession)
    while len(session.items[session.command_index].tokens) == 1:
        complete_current(page, qtbot)
    item = session.items[session.command_index]
    before = session.completed_commands
    press_token(page, qtbot, item.tokens[0])
    assert not page.finish_button.property("emphasized")
    qtbot.mouseClick(page.finish_button, Qt.MouseButton.LeftButton)
    assert session.finish_requested
    assert page.finish_button.property("emphasized")
    assert session.state == SessionState.RUNNING
    assert page.practice_input.hasFocus()
    assert page.stack.currentWidget() is page.practice_page
    for token in item.tokens[1:]:
        press_token(page, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.completed_commands == before + 1
    assert page.last_result is not None
    assert page.last_result.incorrect == 0
    assert page.last_result.correct == session.position
    assert page.repository.completed_count == 1


def test_retry_replays_generated_content_and_new_problem_changes_combinations(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    original = page.session
    assert isinstance(original, ContinuousCommandSession)
    first_page = tuple(item.display for item in original.items)
    for _ in range(3):
        complete_current(page, qtbot)
    qtbot.mouseClick(page.finish_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.result_retry_button, Qt.MouseButton.LeftButton)
    replay = page.session
    assert isinstance(replay, ContinuousCommandSession)
    assert replay.spec == original.spec
    assert replay.attempt_id != original.attempt_id
    assert tuple(item.display for item in replay.items) == first_page
    assert replay.state == SessionState.READY
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert isinstance(fresh, ContinuousCommandSession)
    assert fresh.spec.seed != original.spec.seed
    assert {item.display for item in fresh.items} != set(first_page)
    assert page.repository.completed_count == 1


def test_finish_stays_muted_until_requested_and_other_problem_resets_pending_finish(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = page.session
    assert isinstance(session, ContinuousCommandSession)
    assert not page.finish_button.isEnabled()
    assert not page.finish_button.property("emphasized")
    assert page.finish_button.objectName() != "primary"
    while len(session.items[session.command_index].tokens) == 1:
        complete_current(page, qtbot)
    item = session.items[session.command_index]
    press_token(page, qtbot, item.tokens[0])
    assert page.finish_button.isEnabled()
    assert not page.finish_button.property("emphasized")
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.PAUSED
    assert not page.finish_button.property("emphasized")
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.finish_button, Qt.MouseButton.LeftButton)
    assert session.finish_requested and page.finish_button.property("emphasized")
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert isinstance(fresh, ContinuousCommandSession)
    assert session.state == SessionState.ABORTED
    assert session.result is not None and session.result.stars == 0
    assert fresh.spec.lesson_id == session.spec.lesson_id
    assert fresh.spec.seed != session.spec.seed
    assert fresh.attempt_id != session.attempt_id
    assert fresh.profile == session.profile
    assert fresh.lesson.display_count == session.lesson.display_count
    assert not fresh.finish_requested
    assert fresh.position == 0 and fresh.elapsed_seconds == 0
    assert fresh.state == SessionState.READY
    assert not page.finish_button.isEnabled()
    assert not page.finish_button.property("emphasized")
    assert page.repository.completed_count == 0
    assert page.start_button.hasFocus()


@pytest.mark.parametrize("control", ("pause_button", "finish_button"))
def test_moving_focus_to_a_command_control_stops_timing(
    page: CommandPracticePage, qtbot: QtBot, control: str
) -> None:
    session = page.session
    assert isinstance(session, ContinuousCommandSession)
    assert session.expected_token is not None
    press_token(page, qtbot, session.expected_token)
    getattr(page, control).setFocus()
    qtbot.waitUntil(lambda: session.state == SessionState.PAUSED)
    assert not page.timer.isActive()
    elapsed = session.elapsed_seconds
    page.practice_input.setFocus()
    assert session.expected_token is not None
    before = session.position
    press_token(page, qtbot, session.expected_token)
    assert session.position == before
    assert session.elapsed_seconds == elapsed
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    assert session.state == SessionState.RUNNING
    assert page.timer.isActive()
