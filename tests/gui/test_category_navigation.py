"""연습 분야별 메뉴 분리와 실제 연습 후 돌아오는 경로를 검증한다."""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.command_generator import list_command_profiles
from vim_key_trainer.domain.exercises import EXERCISES
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.command_session import ContinuousCommandSession
from vim_key_trainer.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[MainWindow]:
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()


def lesson_ids(page: QWidget) -> set[str]:
    return {
        button.objectName().removeprefix("lesson_")
        for button in page.findChildren(QPushButton)
        if button.objectName().startswith("lesson_")
    }


def click_named(page: QWidget, qtbot: QtBot, name: str) -> None:
    target = next(
        button
        for button in page.findChildren(QPushButton)
        if button.accessibleName() == name or button.objectName() == name
    )
    qtbot.mouseClick(target, Qt.MouseButton.LeftButton)


def press_token(window: MainWindow, qtbot: QtBot, token: KeyToken) -> None:
    target = window.command_page.practice_input
    if token.kind == "char":
        qtbot.keyClicks(target, token.value)
    elif token.kind == "special":
        qtbot.keyClick(
            target,
            {
                "esc": Qt.Key.Key_Escape,
                "enter": Qt.Key.Key_Return,
                "backspace": Qt.Key.Key_Backspace,
            }[token.value],
        )
    else:
        modifier = (
            Qt.KeyboardModifier.MetaModifier
            if sys.platform == "darwin"
            else Qt.KeyboardModifier.ControlModifier
        )
        qtbot.keyClick(target, Qt.Key.Key_R, modifier)


def test_sidebar_separates_numeric_and_command_catalogs(
    window: MainWindow, qtbot: QtBot
) -> None:
    assert window.stack.currentWidget() is window.numbers_page
    assert window.numbers_button.isChecked()
    assert lesson_ids(window.numbers_page) == {exercise.id for exercise in EXERCISES}
    assert len(lesson_ids(window.numbers_page)) == 6
    qtbot.mouseClick(window.commands_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.commands_menu_page
    assert window.commands_button.isChecked()
    assert not window.numbers_button.isChecked()
    assert lesson_ids(window.commands_menu_page) == {
        profile.id for profile in list_command_profiles()
    }
    assert len(lesson_ids(window.commands_menu_page)) == 6
    assert not lesson_ids(window.numbers_page) & lesson_ids(window.commands_menu_page)


@pytest.mark.parametrize("exercise_id", ["bracket_pairs", "quotes"])
def test_new_numeric_choices_follow_settings_and_return_to_numeric_menu(
    window: MainWindow, qtbot: QtBot, exercise_id: str
) -> None:
    window.show_settings()
    window.length_combo.setCurrentIndex(0)
    window.width_combo.setCurrentIndex(2)
    qtbot.mouseClick(window.numbers_button, Qt.MouseButton.LeftButton)
    click_named(window.numbers_page, qtbot, f"lesson_{exercise_id}")
    assert window.session is not None
    session = window.session
    assert session.spec.exercise_id == exercise_id
    assert session.spec.target_length == 20
    assert session.spec.display_width == 40
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(window.practice_input.hasFocus)
    qtbot.keyClicks(window.practice_input, session.target)
    assert session.state == SessionState.COMPLETED
    assert session.result is not None and session.result.incorrect == 0
    click_named(window.result_page, qtbot, "resultHome")
    assert window.stack.currentWidget() is window.numbers_page
    assert window.numbers_button.isChecked()
    assert window.repository.best_stars(exercise_id) == 3
    assert "완료 1회" in window.home_summary.text()
    assert "완료 0회" in window.commands_summary.text()


def test_sidebar_switch_aborts_active_attempts_and_opens_editing_placeholder(
    window: MainWindow, qtbot: QtBot
) -> None:
    click_named(window.numbers_page, qtbot, "lesson_numbers")
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    assert window.session is not None
    numeric = window.session
    qtbot.keyClicks(window.practice_input, numeric.target[0])
    qtbot.mouseClick(window.commands_button, Qt.MouseButton.LeftButton)
    assert numeric.state == SessionState.ABORTED
    click_named(window.commands_menu_page, qtbot, "lesson_commands_objects_random")
    qtbot.mouseClick(window.command_page.start_button, Qt.MouseButton.LeftButton)
    command = window.command_page.session
    assert isinstance(command, ContinuousCommandSession)
    assert command.expected_token is not None
    press_token(window, qtbot, command.expected_token)
    qtbot.mouseClick(window.editing_button, Qt.MouseButton.LeftButton)
    assert command.state == SessionState.ABORTED
    assert window.stack.currentWidget() is window.editing_page
    assert window.editing_button.isChecked()
    assert not window.commands_button.isChecked()
    assert not lesson_ids(window.editing_page)
    assert any(
        "준비" in label.text() for label in window.editing_page.findChildren(QLabel)
    )
    assert window.repository.completed_count == 0
    assert window.repository.best_stars("numbers") == 0
    click_named(window.editing_page, qtbot, "editingToCommands")
    assert window.stack.currentWidget() is window.commands_menu_page
    assert window.commands_button.isChecked()


def test_command_result_and_settings_return_to_command_menu(
    window: MainWindow, qtbot: QtBot
) -> None:
    qtbot.mouseClick(window.commands_button, Qt.MouseButton.LeftButton)
    click_named(window.commands_menu_page, qtbot, "lesson_commands_insert_random")
    qtbot.mouseClick(window.command_page.start_button, Qt.MouseButton.LeftButton)
    session = window.command_page.session
    assert isinstance(session, ContinuousCommandSession)
    first = session.items[0]
    for token in first.tokens:
        press_token(window, qtbot, token)
    qtbot.mouseClick(window.command_page.finish_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.COMPLETED
    click_named(window.command_page.result_page, qtbot, "commandResultHome")
    assert window.stack.currentWidget() is window.commands_menu_page
    assert window.commands_button.isChecked()
    assert "완료 0회" in window.home_summary.text()
    assert "완료 1회" in window.commands_summary.text()
    window.show_settings()
    assert window.settings_button.isChecked()
    assert not window.commands_button.isChecked()
    window.show_home()
    assert window.stack.currentWidget() is window.commands_menu_page
    assert window.commands_button.isChecked()
