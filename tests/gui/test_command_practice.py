"""고정·연속 명령 연습의 입력·완료·재도전 흐름을 검증한다."""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.command_loader import list_command_lessons
from vim_key_trainer.domain.command_generator import (
    get_command_profile,
    list_command_profiles,
)
from vim_key_trainer.domain.commands import CommandItem, CommandLesson, CommandSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.command_session import ContinuousCommandSession
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.command_practice import CommandPracticePage
from vim_key_trainer.ui.main_window import MainWindow

from ._support import press_page_key


def command_lesson() -> CommandLesson:
    sequences = (
        (
            "insert",
            (KeyToken("char", "i"), KeyToken("char", "A"), KeyToken("special", "esc")),
        ),
        ("zero", (KeyToken("char", "0"),)),
        ("count", tuple(KeyToken("char", character) for character in "3j")),
        (
            "insert_keys",
            (
                KeyToken("char", "a"),
                KeyToken("char", "x"),
                KeyToken("special", "backspace"),
                KeyToken("char", "y"),
                KeyToken("special", "enter"),
                KeyToken("special", "esc"),
            ),
        ),
        ("history", (KeyToken("char", "u"), KeyToken("chord", "ctrl+r"))),
        ("macro", tuple(KeyToken("char", character) for character in "qa")),
        ("clipboard", tuple(KeyToken("char", character) for character in '"+y')),
        ("last", (KeyToken("char", "G"),)),
    )
    return CommandLesson(
        schema_version=1,
        content_version=1,
        id="test_commands",
        title="테스트 명령",
        description="독립된 명령 항목의 키 입력을 검증합니다.",
        difficulty="beginner",
        tags=("test",),
        display_count=8,
        items=tuple(
            CommandItem(
                id=item_id,
                tokens=tokens,
                meaning=f"{item_id}의 의미",
                start_mode="Normal",
                follow_up=f"{item_id}의 후속 입력 안내",
                execution_support="typing_only",
            )
            for item_id, tokens in sequences
        ),
    )


@pytest.fixture
def fixed_page(qtbot: QtBot) -> Iterator[CommandPracticePage]:
    widget = CommandPracticePage(MemoryResultRepository())
    qtbot.addWidget(widget)
    widget.prepare(command_lesson())
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()


def begin(fixed_page: CommandPracticePage, qtbot: QtBot) -> None:
    qtbot.mouseClick(fixed_page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(fixed_page.practice_input.hasFocus)


def test_inline_hint_tracks_target_and_requires_real_escape(
    fixed_page: CommandPracticePage, qtbot: QtBot
) -> None:
    assert fixed_page.session is not None
    session = fixed_page.session
    assert session.elapsed_seconds == 0
    assert not fixed_page.practice_input.isEnabled()
    assert "insert의 의미" in fixed_page.practice_input.accessibleDescription()
    begin(fixed_page, qtbot)
    qtbot.keyClick(fixed_page.practice_input, Qt.Key.Key_Backspace)
    assert session.state == SessionState.READY
    assert "insert의 의미" in fixed_page.practice_input.accessibleDescription()
    qtbot.keyClicks(fixed_page.practice_input, "I")
    assert session.position == 0
    assert session.incorrect == 1
    assert "insert의 의미" in fixed_page.practice_input.accessibleDescription()
    assert all(
        session.items[0].follow_up not in widget.text()
        for widget in fixed_page.practice_page.findChildren(QLabel)
    )
    qtbot.keyClicks(fixed_page.practice_input, "iA<Esc>")
    assert session.position == 2
    assert session.incorrect == 6
    assert session.completed_commands == 0
    qtbot.keyClick(fixed_page.practice_input, Qt.Key.Key_Escape)
    assert session.completed_commands == 1
    assert session.position == 3
    assert fixed_page.practice_input.hasFocus()
    assert "zero의 의미" in fixed_page.practice_input.accessibleDescription()
    qtbot.keyClick(fixed_page.practice_input, Qt.Key.Key_Backspace)
    assert "zero의 의미" in fixed_page.practice_input.accessibleDescription()
    qtbot.keyClicks(fixed_page.practice_input, "!")
    assert "zero의 의미" in fixed_page.practice_input.accessibleDescription()
    assert session.position == 3
    qtbot.keyClicks(fixed_page.practice_input, "0")
    assert session.completed_commands == 2


def test_special_keys_and_control_count_once_through_complete_and_retry(
    fixed_page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(fixed_page, qtbot)
    assert fixed_page.session is not None
    session = fixed_page.session
    for token in session.target:
        press_page_key(fixed_page, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.completed_commands == len(session.items) == 8
    assert session.position == len(session.target)
    assert session.incorrect == 0
    assert session.result is fixed_page.last_result
    assert session.result is not None
    assert session.result.correct == len(session.target)
    assert session.result.stars == 3
    assert len(session.command_times) == 8
    assert fixed_page.stack.currentWidget() is fixed_page.result_page
    assert fixed_page.result_times.text()
    assert fixed_page.repository.completed_count == 1
    qtbot.keyClicks(fixed_page.practice_input, "G")
    assert fixed_page.repository.completed_count == 1
    assert len(fixed_page.repository.results) == 1
    fixed_page.retry()
    assert fixed_page.session is not None
    assert fixed_page.session.state == SessionState.READY
    assert fixed_page.session.attempt_id != session.attempt_id
    assert fixed_page.session.target == session.target
    assert fixed_page.session.spec == session.spec
    assert fixed_page.repository.completed_count == 1


def test_command_key_is_not_physical_control_redo(
    fixed_page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(fixed_page, qtbot)
    assert fixed_page.session is not None
    session = fixed_page.session
    while session.expected_token != KeyToken("chord", "ctrl+r"):
        assert session.expected_token is not None
        press_page_key(fixed_page, qtbot, session.expected_token)
    before = session.position
    wrong_modifier = (
        Qt.KeyboardModifier.ControlModifier
        if sys.platform == "darwin"
        else Qt.KeyboardModifier.MetaModifier
    )
    qtbot.keyClick(fixed_page.practice_input, Qt.Key.Key_R, wrong_modifier)
    assert session.position == before
    assert session.incorrect == 1
    press_page_key(fixed_page, qtbot, KeyToken("chord", "ctrl+r"))
    assert session.position == before + 1
    assert session.incorrect == 1


def test_paste_repeat_ime_and_key_release_do_not_start_command(
    fixed_page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(fixed_page, qtbot)
    assert fixed_page.session is not None
    session = fixed_page.session
    for event in (
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_I,
            Qt.KeyboardModifier.NoModifier,
            "i",
            True,
        ),
        QKeyEvent(
            QEvent.Type.KeyRelease, Qt.Key.Key_I, Qt.KeyboardModifier.NoModifier, "i"
        ),
    ):
        QApplication.sendEvent(fixed_page.practice_input, event)
    qtbot.keyClick(
        fixed_page.practice_input, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier
    )
    composition = QInputMethodEvent()
    composition.setCommitString("iA")
    QApplication.sendEvent(fixed_page.practice_input, composition)
    assert session.state == SessionState.READY
    assert session.position == session.incorrect == 0
    assert session.elapsed_seconds == 0
    assert "insert의 의미" in fixed_page.practice_input.accessibleDescription()


def test_focus_loss_needs_resume_and_new_problem_aborts(
    fixed_page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(fixed_page, qtbot)
    assert fixed_page.session is not None
    session = fixed_page.session
    qtbot.keyClicks(fixed_page.practice_input, "i")
    fixed_page.retry_button.setFocus()
    qtbot.waitUntil(lambda: session.state == SessionState.PAUSED)
    paused = session.elapsed_seconds
    fixed_page.practice_input.setFocus()
    qtbot.keyClicks(fixed_page.practice_input, "A")
    assert session.position == 1
    assert session.elapsed_seconds == paused
    qtbot.mouseClick(fixed_page.pause_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(fixed_page.practice_input.hasFocus)
    qtbot.keyClicks(fixed_page.practice_input, "A")
    assert session.position == 2
    fixed_page.new_problem()
    assert session.state == SessionState.ABORTED
    assert session.result is not None
    assert session.result.stars == 0
    assert fixed_page.session is not None
    assert fixed_page.session.spec.seed != session.spec.seed
    assert fixed_page.session.state == SessionState.READY
    assert fixed_page.repository.completed_count == 0


def test_menu_opens_commands_and_navigation_aborts_without_award(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    lesson = list_command_profiles()[0]
    window.show_commands_menu()
    start = window.commands_menu_page.findChild(QPushButton, f"lesson_{lesson.id}")
    assert start is not None
    qtbot.mouseClick(start, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.command_page
    fixed_page = window.command_page
    assert fixed_page.session is not None
    assert fixed_page.session.lesson.id == lesson.id
    assert 8 <= len(fixed_page.session.items) <= 12
    session = fixed_page.session
    begin(fixed_page, qtbot)
    window.show_diagnostics()
    assert session.state == SessionState.ABORTED
    assert window.repository.completed_count == 0
    qtbot.keyClicks(window.diagnostic_input, "u")
    assert session.position == 0
    window.prepare_practice("numbers")
    assert window.stack.currentWidget() is window.practice_page
    assert window.session is not None
    assert window.session.state == SessionState.READY


@pytest.mark.parametrize("lesson", list_command_lessons(), ids=lambda lesson: lesson.id)
def test_packaged_command_lessons_complete_through_qt_keys(
    fixed_page: CommandPracticePage, qtbot: QtBot, lesson: CommandLesson
) -> None:
    fixed_page.prepare(lesson)
    begin(fixed_page, qtbot)
    assert fixed_page.session is not None
    session = fixed_page.session
    for token in session.target:
        press_page_key(fixed_page, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.completed_commands == len(lesson.items)
    assert session.result is not None
    assert session.result.incorrect == 0
    assert session.result.correct == len(session.target)
    assert session.result.stars == 3
    assert len(session.command_times) == len(lesson.items)
    assert fixed_page.repository.best_command_stars(lesson.id) == 3
    assert fixed_page.stack.currentWidget() is fixed_page.result_page


@pytest.fixture
def stream_page(qtbot: QtBot) -> Iterator[CommandPracticePage]:
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


def complete_current(stream_page: CommandPracticePage, qtbot: QtBot) -> str:
    session = stream_page.session
    assert isinstance(session, ContinuousCommandSession)
    item = session.items[session.command_index]
    for token in item.tokens[session.token_index :]:
        press_page_key(stream_page, qtbot, token)
    return item.display


def test_random_commands_continue_past_one_hundred_without_automatic_result(
    stream_page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = stream_page.session
    assert isinstance(session, ContinuousCommandSession)
    first_page = session.items
    displays = [complete_current(stream_page, qtbot) for _ in range(105)]
    assert len(set(displays)) > 40
    assert session.completed_commands == 105
    assert session.items != first_page
    assert len(session.items) == session.lesson.display_count
    assert session.state == SessionState.RUNNING
    assert session.combo == session.position
    assert session.incorrect == 0
    assert stream_page.stack.currentWidget() is stream_page.practice_page
    assert stream_page.practice_input.hasFocus()
    assert stream_page.repository.completed_count == 0
    assert stream_page.last_result is None
    assert "105" in stream_page.metrics["progress"].text()
    qtbot.mouseClick(stream_page.finish_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.COMPLETED
    assert stream_page.stack.currentWidget() is stream_page.result_page
    assert stream_page.last_result is not None
    assert stream_page.last_result.completed_commands == 105
    assert len(stream_page.last_result.command_samples) <= 100
    assert stream_page.repository.completed_count == 1
    assert stream_page.result_times.text()
    assert all(
        display in stream_page.result_times.text() for display in displays[-100:]
    )


def test_inline_hint_and_combo_survive_refill_then_mistake_keeps_target(
    stream_page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = stream_page.session
    assert isinstance(session, ContinuousCommandSession)
    for _ in range(session.lesson.display_count):
        complete_current(stream_page, qtbot)
    assert session.command_index == 0
    assert session.combo == session.position
    current = session.items[0]
    assert current.brief_meaning in stream_page.practice_input.accessibleDescription()
    wrong = "!" if current.tokens[0] != KeyToken("char", "!") else "?"
    before = session.position
    qtbot.keyClicks(stream_page.practice_input, wrong)
    assert current.brief_meaning in stream_page.practice_input.accessibleDescription()
    assert session.position == before
    assert session.incorrect == 1
    assert session.combo == 0


def test_finish_midcommand_keeps_typing_until_that_command_is_complete(
    stream_page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = stream_page.session
    assert isinstance(session, ContinuousCommandSession)
    while len(session.items[session.command_index].tokens) == 1:
        complete_current(stream_page, qtbot)
    item = session.items[session.command_index]
    before = session.completed_commands
    press_page_key(stream_page, qtbot, item.tokens[0])
    assert not stream_page.finish_button.property("emphasized")
    qtbot.mouseClick(stream_page.finish_button, Qt.MouseButton.LeftButton)
    assert session.finish_requested
    assert stream_page.finish_button.property("emphasized")
    assert session.state == SessionState.RUNNING
    assert stream_page.practice_input.hasFocus()
    assert stream_page.stack.currentWidget() is stream_page.practice_page
    for token in item.tokens[1:]:
        press_page_key(stream_page, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.completed_commands == before + 1
    assert stream_page.last_result is not None
    assert stream_page.last_result.incorrect == 0
    assert stream_page.last_result.correct == session.position
    assert stream_page.repository.completed_count == 1


def test_retry_replays_generated_content_and_new_problem_changes_combinations(
    stream_page: CommandPracticePage, qtbot: QtBot
) -> None:
    original = stream_page.session
    assert isinstance(original, ContinuousCommandSession)
    first_page = tuple(item.display for item in original.items)
    for _ in range(3):
        complete_current(stream_page, qtbot)
    qtbot.mouseClick(stream_page.finish_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(stream_page.result_retry_button, Qt.MouseButton.LeftButton)
    replay = stream_page.session
    assert isinstance(replay, ContinuousCommandSession)
    assert replay.spec == original.spec
    assert replay.attempt_id != original.attempt_id
    assert tuple(item.display for item in replay.items) == first_page
    assert replay.state == SessionState.READY
    qtbot.mouseClick(stream_page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = stream_page.session
    assert isinstance(fresh, ContinuousCommandSession)
    assert fresh.spec.seed != original.spec.seed
    assert {item.display for item in fresh.items} != set(first_page)
    assert stream_page.repository.completed_count == 1


def test_finish_stays_muted_until_requested_and_other_problem_resets_pending_finish(
    stream_page: CommandPracticePage, qtbot: QtBot
) -> None:
    session = stream_page.session
    assert isinstance(session, ContinuousCommandSession)
    assert not stream_page.finish_button.isEnabled()
    assert not stream_page.finish_button.property("emphasized")
    assert stream_page.finish_button.objectName() != "primary"
    while len(session.items[session.command_index].tokens) == 1:
        complete_current(stream_page, qtbot)
    item = session.items[session.command_index]
    press_page_key(stream_page, qtbot, item.tokens[0])
    assert stream_page.finish_button.isEnabled()
    assert not stream_page.finish_button.property("emphasized")
    qtbot.mouseClick(stream_page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.PAUSED
    assert not stream_page.finish_button.property("emphasized")
    qtbot.mouseClick(stream_page.pause_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(stream_page.finish_button, Qt.MouseButton.LeftButton)
    assert session.finish_requested and stream_page.finish_button.property("emphasized")
    qtbot.mouseClick(stream_page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = stream_page.session
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
    assert not stream_page.finish_button.isEnabled()
    assert not stream_page.finish_button.property("emphasized")
    assert stream_page.repository.completed_count == 0
    assert stream_page.start_button.hasFocus()


@pytest.mark.parametrize("control", ("pause_button", "finish_button"))
def test_moving_focus_to_a_command_control_stops_timing(
    stream_page: CommandPracticePage, qtbot: QtBot, control: str
) -> None:
    session = stream_page.session
    assert isinstance(session, ContinuousCommandSession)
    assert session.expected_token is not None
    press_page_key(stream_page, qtbot, session.expected_token)
    getattr(stream_page, control).setFocus()
    qtbot.waitUntil(lambda: session.state == SessionState.PAUSED)
    assert not stream_page.timer.isActive()
    elapsed = session.elapsed_seconds
    stream_page.practice_input.setFocus()
    assert session.expected_token is not None
    before = session.position
    press_page_key(stream_page, qtbot, session.expected_token)
    assert session.position == before
    assert session.elapsed_seconds == elapsed
    qtbot.mouseClick(stream_page.pause_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(stream_page.practice_input.hasFocus)
    assert session.state == SessionState.RUNNING
    assert stream_page.timer.isActive()
