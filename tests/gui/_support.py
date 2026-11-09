"""연습 화면에 KeyToken을 실제 Qt 키 이벤트로 전달한다."""

# Standard library imports
import sys

# Third party imports
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.ui.command_practice import CommandPracticePage
from vim_key_trainer.ui.edit_practice import EditPracticePage
from vim_key_trainer.ui.main_window import MainWindow


def press_key(widget: QWidget, qtbot: QtBot, token: KeyToken) -> None:
    if token.kind == "char":
        qtbot.keyClicks(widget, token.value)
    elif token.kind == "special":
        qtbot.keyClick(
            widget,
            {
                "esc": Qt.Key.Key_Escape,
                "enter": Qt.Key.Key_Return,
                "backspace": Qt.Key.Key_Backspace,
                "tab": Qt.Key.Key_Tab,
            }[token.value],
        )
    else:
        assert token.value.startswith("ctrl+")
        modifier = (
            Qt.KeyboardModifier.MetaModifier
            if sys.platform == "darwin"
            else Qt.KeyboardModifier.ControlModifier
        )
        qtbot.keyClick(
            widget, Qt.Key(ord(token.value.rsplit("+", 1)[1].upper())), modifier
        )


def press_page_key(
    page: MainWindow | CommandPracticePage | EditPracticePage,
    qtbot: QtBot,
    token: KeyToken,
) -> None:
    press_key(page.practice_input, qtbot, token)


def press_edit_key(window: MainWindow, qtbot: QtBot, token: KeyToken) -> None:
    press_page_key(window.edit_practice, qtbot, token)


def press_command_key(window: MainWindow, qtbot: QtBot, token: KeyToken) -> None:
    press_page_key(window.command_page, qtbot, token)
