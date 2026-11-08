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
from vim_key_trainer.domain.command_generator import list_command_profiles
from vim_key_trainer.domain.commands import CommandItem, CommandLesson
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.command_practice import CommandPracticePage
from vim_key_trainer.ui.main_window import MainWindow


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
def page(qtbot: QtBot) -> Iterator[CommandPracticePage]:
    widget = CommandPracticePage(MemoryResultRepository())
    qtbot.addWidget(widget)
    widget.prepare(command_lesson())
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()


def begin(page: CommandPracticePage, qtbot: QtBot) -> None:
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)


def press_token(page: CommandPracticePage, qtbot: QtBot, token: KeyToken) -> None:
    if token.kind == "char":
        qtbot.keyClicks(page.practice_input, token.value)
    elif token.kind == "special":
        key = {
            "esc": Qt.Key.Key_Escape,
            "enter": Qt.Key.Key_Return,
            "backspace": Qt.Key.Key_Backspace,
        }[token.value]
        qtbot.keyClick(page.practice_input, key)
    else:
        assert token.value.startswith("ctrl+")
        modifier = (
            Qt.KeyboardModifier.MetaModifier
            if sys.platform == "darwin"
            else Qt.KeyboardModifier.ControlModifier
        )
        qtbot.keyClick(
            page.practice_input,
            Qt.Key(ord(token.value.rsplit("+", 1)[1].upper())),
            modifier,
        )


def test_inline_hint_tracks_target_and_requires_real_escape(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    assert page.session is not None
    session = page.session
    assert session.elapsed_seconds == 0
    assert not page.practice_input.isEnabled()
    assert "insert의 의미" in page.practice_input.accessibleDescription()
    begin(page, qtbot)
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Backspace)
    assert session.state == SessionState.READY
    assert "insert의 의미" in page.practice_input.accessibleDescription()
    qtbot.keyClicks(page.practice_input, "I")
    assert session.position == 0
    assert session.incorrect == 1
    assert "insert의 의미" in page.practice_input.accessibleDescription()
    assert all(
        session.items[0].follow_up not in widget.text()
        for widget in page.practice_page.findChildren(QLabel)
    )
    qtbot.keyClicks(page.practice_input, "iA<Esc>")
    assert session.position == 2
    assert session.incorrect == 6
    assert session.completed_commands == 0
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Escape)
    assert session.completed_commands == 1
    assert session.position == 3
    assert page.practice_input.hasFocus()
    assert "zero의 의미" in page.practice_input.accessibleDescription()
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Backspace)
    assert "zero의 의미" in page.practice_input.accessibleDescription()
    qtbot.keyClicks(page.practice_input, "!")
    assert "zero의 의미" in page.practice_input.accessibleDescription()
    assert session.position == 3
    qtbot.keyClicks(page.practice_input, "0")
    assert session.completed_commands == 2


def test_special_keys_and_control_count_once_through_complete_and_retry(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(page, qtbot)
    assert page.session is not None
    session = page.session
    for token in session.target:
        press_token(page, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.completed_commands == len(session.items) == 8
    assert session.position == len(session.target)
    assert session.incorrect == 0
    assert session.result is page.last_result
    assert session.result is not None
    assert session.result.correct == len(session.target)
    assert session.result.stars == 3
    assert len(session.command_times) == 8
    assert page.stack.currentWidget() is page.result_page
    assert page.result_times.text()
    assert page.repository.completed_count == 1
    qtbot.keyClicks(page.practice_input, "G")
    assert page.repository.completed_count == 1
    assert len(page.repository.results) == 1
    page.retry()
    assert page.session is not None
    assert page.session.state == SessionState.READY
    assert page.session.attempt_id != session.attempt_id
    assert page.session.target == session.target
    assert page.session.spec == session.spec
    assert page.repository.completed_count == 1


def test_command_key_is_not_physical_control_redo(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(page, qtbot)
    assert page.session is not None
    session = page.session
    while session.expected_token != KeyToken("chord", "ctrl+r"):
        assert session.expected_token is not None
        press_token(page, qtbot, session.expected_token)
    before = session.position
    wrong_modifier = (
        Qt.KeyboardModifier.ControlModifier
        if sys.platform == "darwin"
        else Qt.KeyboardModifier.MetaModifier
    )
    qtbot.keyClick(page.practice_input, Qt.Key.Key_R, wrong_modifier)
    assert session.position == before
    assert session.incorrect == 1
    press_token(page, qtbot, KeyToken("chord", "ctrl+r"))
    assert session.position == before + 1
    assert session.incorrect == 1


def test_paste_repeat_ime_and_key_release_do_not_start_command(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(page, qtbot)
    assert page.session is not None
    session = page.session
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
        QApplication.sendEvent(page.practice_input, event)
    qtbot.keyClick(
        page.practice_input, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier
    )
    composition = QInputMethodEvent()
    composition.setCommitString("iA")
    QApplication.sendEvent(page.practice_input, composition)
    assert session.state == SessionState.READY
    assert session.position == session.incorrect == 0
    assert session.elapsed_seconds == 0
    assert "insert의 의미" in page.practice_input.accessibleDescription()


def test_focus_loss_needs_resume_and_new_problem_aborts(
    page: CommandPracticePage, qtbot: QtBot
) -> None:
    begin(page, qtbot)
    assert page.session is not None
    session = page.session
    qtbot.keyClicks(page.practice_input, "i")
    page.retry_button.setFocus()
    qtbot.waitUntil(lambda: session.state == SessionState.PAUSED)
    paused = session.elapsed_seconds
    page.practice_input.setFocus()
    qtbot.keyClicks(page.practice_input, "A")
    assert session.position == 1
    assert session.elapsed_seconds == paused
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    qtbot.keyClicks(page.practice_input, "A")
    assert session.position == 2
    page.new_problem()
    assert session.state == SessionState.ABORTED
    assert session.result is not None
    assert session.result.stars == 0
    assert page.session is not None
    assert page.session.spec.seed != session.spec.seed
    assert page.session.state == SessionState.READY
    assert page.repository.completed_count == 0


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
    page = window.command_page
    assert page.session is not None
    assert page.session.lesson.id == lesson.id
    assert 8 <= len(page.session.items) <= 12
    session = page.session
    begin(page, qtbot)
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
    page: CommandPracticePage, qtbot: QtBot, lesson: CommandLesson
) -> None:
    page.prepare(lesson)
    begin(page, qtbot)
    assert page.session is not None
    session = page.session
    for token in session.target:
        press_token(page, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.completed_commands == len(lesson.items)
    assert session.result is not None
    assert session.result.incorrect == 0
    assert session.result.correct == len(session.target)
    assert session.result.stars == 3
    assert len(session.command_times) == len(lesson.items)
    assert page.repository.best_command_stars(lesson.id) == 3
    assert page.stack.currentWidget() is page.result_page
