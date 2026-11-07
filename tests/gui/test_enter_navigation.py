"""Enter로 준비·결과를 이동해도 연습 입력이나 시도가 중복되지 않는다."""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Iterator
from typing import Literal

# Third party imports
import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.commands import CommandItem, CommandLesson
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.command_practice import CommandPracticePage
from vim_key_trainer.ui.edit_practice import EditPracticePage
from vim_key_trainer.ui.main_window import MainWindow

Kind = Literal["numbers", "commands", "editing"]
PracticePage = MainWindow | CommandPracticePage | EditPracticePage
KINDS: tuple[Kind, ...] = ("numbers", "commands", "editing")
ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[MainWindow]:
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()


def _command_lesson() -> CommandLesson:
    return CommandLesson(
        schema_version=1,
        content_version=1,
        id="test_enter_commands",
        title="Enter 목표 연습",
        description="마지막 Enter의 화면 전환을 검증합니다.",
        difficulty="beginner",
        tags=("test",),
        display_count=8,
        items=(
            CommandItem(
                id="enter_goal",
                tokens=(KeyToken("char", "r"), KeyToken("special", "enter")),
                meaning="화면 전환 전 두 키를 입력합니다.",
                start_mode="Normal",
                follow_up="",
            ),
        ),
    )


def _prepare(window: MainWindow, kind: Kind) -> PracticePage:
    if kind == "numbers":
        window.prepare_practice("numbers", PracticeSpec("numbers", 41, 20, 20))
        return window
    if kind == "commands":
        window.prepare_commands("commands_random")
        window.command_page.prepare(_command_lesson())
        return window.command_page
    window.prepare_editing(
        "editing_numbers", EditPracticeSpec("editing_numbers", 41, 12)
    )
    return window.edit_practice


def _focused_enter(qtbot: QtBot, key: Qt.Key) -> None:
    before = QApplication.focusWidget()
    assert before is not None
    qtbot.keyPress(before, key)
    after = QApplication.focusWidget()
    assert after is not None
    qtbot.keyRelease(after, key)


def _auto_repeat(widget: QWidget, key: Qt.Key) -> None:
    QApplication.sendEvent(
        widget,
        QKeyEvent(
            QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, "\r", True, 1
        ),
    )


def _complete(page: PracticePage, qtbot: QtBot) -> None:
    session = page.session
    assert session is not None
    if isinstance(page, MainWindow):
        qtbot.keyClicks(page.practice_input, session.target)
        return
    keys = (
        session.lesson.baseline
        if isinstance(session, EditingSession)
        else session.target
    )
    for token in keys:
        if token.kind == "char":
            qtbot.keyClicks(page.practice_input, token.value)
        elif token.kind == "special":
            qtbot.keyClick(
                page.practice_input,
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
            qtbot.keyClick(
                page.practice_input,
                Qt.Key(ord(token.value.rsplit("+", 1)[1].upper())),
                modifier,
            )


def _new_button(page: PracticePage) -> QPushButton:
    return (
        page.new_button
        if isinstance(page, CommandPracticePage)
        else page.result_new_button
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("key", ENTER_KEYS)
def test_enter_starts_focused_ready_practice_without_scoring_the_gui_key(
    window: MainWindow, qtbot: QtBot, kind: Kind, key: Qt.Key
) -> None:
    page = _prepare(window, kind)
    session = page.session
    assert session is not None
    qtbot.waitUntil(page.start_button.hasFocus)
    clicks: list[bool] = []
    page.start_button.clicked.connect(lambda checked=False: clicks.append(checked))
    _auto_repeat(page.start_button, key)
    assert page.start_button.isVisible()
    assert clicks == []
    _focused_enter(qtbot, key)
    qtbot.waitUntil(page.practice_input.hasFocus)
    assert clicks == [False]
    assert not page.start_button.isVisible()
    assert page.practice_input.isEnabled()
    assert session.state == SessionState.READY
    assert session.elapsed_seconds == 0
    if isinstance(session, EditingSession):
        assert session.key_count == 0
    else:
        assert session.position == session.incorrect == 0


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("key", ENTER_KEYS)
def test_result_enter_opens_the_emphasized_first_new_problem_without_starting_it(
    window: MainWindow, qtbot: QtBot, kind: Kind, key: Qt.Key
) -> None:
    page = _prepare(window, kind)
    _focused_enter(qtbot, key)
    previous = page.session
    assert previous is not None
    _complete(page, qtbot)
    assert previous.state == SessionState.COMPLETED
    assert page.stack.currentWidget() is page.result_page
    fresh = _new_button(page)
    retry = page.result_retry_button
    qtbot.waitUntil(fresh.hasFocus)
    assert (
        fresh.mapTo(page.result_page, QPoint()).x()
        < retry.mapTo(page.result_page, QPoint()).x()
    )
    assert fresh.objectName() == "primary"
    assert retry.objectName() != "primary"
    _auto_repeat(fresh, key)
    assert page.session is previous
    clicks: list[bool] = []
    fresh.clicked.connect(lambda checked=False: clicks.append(checked))
    _focused_enter(qtbot, key)
    current = page.session
    assert current is not None and current is not previous
    assert current.attempt_id != previous.attempt_id
    assert current.state == SessionState.READY
    assert current.elapsed_seconds == 0
    assert clicks == [False]
    qtbot.waitUntil(page.start_button.hasFocus)
    assert not page.practice_input.isEnabled()
    _auto_repeat(page.start_button, key)
    assert page.start_button.hasFocus()
    assert not page.practice_input.isEnabled()


@pytest.mark.parametrize("key", ENTER_KEYS)
def test_final_scored_enter_and_its_held_repeats_do_not_skip_the_result(
    window: MainWindow, qtbot: QtBot, key: Qt.Key
) -> None:
    page = _prepare(window, "commands")
    _focused_enter(qtbot, key)
    session = page.session
    assert session is not None
    qtbot.keyClicks(page.practice_input, "r")
    _focused_enter(qtbot, key)
    assert session.state == SessionState.COMPLETED
    assert session.position == 2 and session.incorrect == 0
    assert page.stack.currentWidget() is page.result_page
    fresh = _new_button(page)
    assert fresh.hasFocus()
    _auto_repeat(fresh, key)
    _auto_repeat(fresh, key)
    assert page.session is session
    assert window.repository.completed_count == 1


@pytest.mark.parametrize("kind", KINDS)
def test_secondary_result_retry_remains_available_from_tab_and_enter(
    window: MainWindow, qtbot: QtBot, kind: Kind
) -> None:
    page = _prepare(window, kind)
    _focused_enter(qtbot, Qt.Key.Key_Return)
    previous = page.session
    assert previous is not None
    _complete(page, qtbot)
    fresh = _new_button(page)
    qtbot.waitUntil(fresh.hasFocus)
    qtbot.keyClick(fresh, Qt.Key.Key_Tab)
    qtbot.waitUntil(page.result_retry_button.hasFocus)
    _focused_enter(qtbot, Qt.Key.Key_Return)
    retried = page.session
    assert retried is not None and retried is not previous
    assert retried.state == SessionState.READY
    if isinstance(retried, EditingSession):
        assert retried.lesson.signature == previous.lesson.signature
    else:
        assert retried.spec == previous.spec


def test_fixed_edit_lesson_falls_back_to_enter_retry_when_new_problem_is_disabled(
    window: MainWindow, qtbot: QtBot
) -> None:
    window.prepare_editing_lesson(get_edit_lesson("editing_numbers"))
    page = window.edit_practice
    _focused_enter(qtbot, Qt.Key.Key_Return)
    previous = page.session
    assert previous is not None
    _complete(page, qtbot)
    assert not page.result_new_button.isEnabled()
    qtbot.waitUntil(page.result_retry_button.hasFocus)
    _focused_enter(qtbot, Qt.Key.Key_Enter)
    assert page.session is not None and page.session is not previous
    assert page.session.lesson is previous.lesson
    assert page.session.state == SessionState.READY
