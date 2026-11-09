"""CheatSheet의 검색·표시와 연습 상태 보존을 검증한다."""

from __future__ import annotations

# Standard library imports
from typing import Literal

# Third party imports
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QLineEdit
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.commands import CommandSpec
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.command_practice import CommandPracticePage
from vim_key_trainer.ui.edit_practice import EditPracticePage
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.vim_cheatsheet import VimCheatSheetPage

from ._support import press_page_key

Kind = Literal["numbers", "commands", "editing"]


PracticePage = MainWindow | CommandPracticePage | EditPracticePage


def prepare(window: MainWindow, kind: Kind) -> PracticePage:
    if kind == "numbers":
        window.prepare_practice(
            "numbers", PracticeSpec("numbers", target_length=20, seed=51)
        )
        return window
    if kind == "commands":
        window.prepare_commands(
            "commands_random", CommandSpec("commands_random", seed=51)
        )
        return window.command_page
    window.prepare_editing_lesson(get_edit_lesson("editing_numbers"))
    return window.edit_practice


@pytest.mark.parametrize("kind", ("numbers", "commands", "editing"))
def test_reference_pauses_and_returns_to_same_attempt_without_scoring(
    window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, kind: Kind
) -> None:
    page = prepare(window, kind)
    session = page.session
    assert session is not None
    ticks = [1_000_000_000]
    monkeypatch.setattr(session, "_clock_ns", lambda: ticks[0])
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    token = (
        KeyToken("char", session.target[0])
        if isinstance(page, MainWindow)
        else session.expected_token
    )
    assert token is not None
    press_page_key(page, qtbot, token)
    assert session.state == SessionState.RUNNING
    ticks[0] += 2_000_000_000
    attempt_id = session.attempt_id
    count = (
        session.key_count if isinstance(session, EditingSession) else session.position
    )
    snapshot = (
        session.engine.snapshot() if isinstance(session, EditingSession) else None
    )
    source = window.stack.currentWidget()

    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.cheatsheet_page
    assert window.cheatsheet_button.isChecked()
    assert session.state == SessionState.PAUSED
    assert session.elapsed_seconds == 2
    search = window.cheatsheet_page.findChild(QLineEdit)
    assert search is not None
    qtbot.keyClicks(search, "dd")
    ticks[0] += 30_000_000_000
    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.cheatsheet_page.return_button, Qt.MouseButton.LeftButton)

    assert window.stack.currentWidget() is source
    assert session.attempt_id == attempt_id
    assert session.state == SessionState.PAUSED
    assert session.elapsed_seconds == 2
    assert session.pause_count == 1
    assert page.pause_button.hasFocus()
    assert count == (
        session.key_count if isinstance(session, EditingSession) else session.position
    )
    if isinstance(session, EditingSession):
        assert session.engine.snapshot() == snapshot
    assert window.repository.results == ()
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.RUNNING
    ticks[0] += 1_000_000_000
    assert session.elapsed_seconds == 3


@pytest.mark.parametrize("kind", ("numbers", "commands", "editing"))
def test_reference_keeps_unstarted_practice_ready(
    window: MainWindow, qtbot: QtBot, kind: Kind
) -> None:
    page = prepare(window, kind)
    session = page.session
    assert session is not None
    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.cheatsheet_page.return_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.READY
    assert session.elapsed_seconds == 0
    assert session.pause_count == 0
    assert page.start_button.hasFocus()


def test_sidebar_places_reference_after_editing_and_restores_catalog(
    window: MainWindow, qtbot: QtBot
) -> None:
    layout = window.editing_button.parentWidget().layout()
    assert layout is not None
    assert (
        layout.indexOf(window.cheatsheet_button)
        == layout.indexOf(window.editing_button) + 1
    )
    assert window.cheatsheet_button.accessibleName() == "navCheatSheet"
    window.show_editing()
    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.cheatsheet_page.return_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.editing_menu_page
    assert window.editing_button.isChecked()
    assert not window.cheatsheet_button.isChecked()


def test_leaving_reference_for_another_menu_aborts_the_old_attempt(
    window: MainWindow, qtbot: QtBot
) -> None:
    page = prepare(window, "numbers")
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.commands_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.ABORTED
    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.cheatsheet_page.return_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.commands_menu_page
    assert window.commands_button.isChecked()


@pytest.mark.parametrize(
    ("kind", "generated"),
    [("numbers", False), ("commands", False), ("editing", False), ("editing", True)],
)
def test_reference_returns_to_result_with_enter_action_without_saving_again(
    window: MainWindow, qtbot: QtBot, kind: Kind, generated: bool
) -> None:
    page = prepare(window, kind)
    if generated:
        window.prepare_editing(
            "editing_numbers", EditPracticeSpec("editing_numbers", seed=51)
        )
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    if isinstance(page, MainWindow):
        qtbot.keyClicks(page.practice_input, session.target)
        action = page.result_new_button
    elif isinstance(page, CommandPracticePage):
        for token in session.items[0].tokens:
            press_page_key(page, qtbot, token)
        qtbot.mouseClick(page.finish_button, Qt.MouseButton.LeftButton)
        action = page.new_button
    else:
        for step in session.lesson.guide:
            for token in step.keys:
                press_page_key(page, qtbot, token)
        action = page.result_new_button if generated else page.result_retry_button
    assert session.state == SessionState.COMPLETED
    before = window.repository.results
    source = window.stack.currentWidget()
    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.cheatsheet_page.return_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is source
    assert session.state == SessionState.COMPLETED
    assert window.repository.results == before
    assert action.hasFocus()
    qtbot.keyClick(action, Qt.Key.Key_Return)
    assert page.session is not None
    assert page.session.attempt_id != session.attempt_id
    assert page.session.state == SessionState.READY
    assert window.repository.results == before


@pytest.fixture
def sheet(qtbot: QtBot) -> VimCheatSheetPage:
    page = VimCheatSheetPage()
    qtbot.addWidget(page)
    page.resize(1005, 800)
    page.show()
    qtbot.waitUntil(lambda: page._column_count == 2)
    return page


def visible_keys(sheet: VimCheatSheetPage) -> set[str]:
    return {
        key.text() for card in sheet.cards for key in card.key_labels if key.isVisible()
    }


def test_search_combines_with_category_and_recovers_from_no_matches(
    sheet: VimCheatSheetPage, qtbot: QtBot
) -> None:
    sheet.focus_search()
    qtbot.keyClicks(sheet.search, ":write")
    assert visible_keys(sheet) == {":write / :w", ":write path"}
    sheet.category.setCurrentIndex(sheet.category.findData("motions"))
    assert not visible_keys(sheet)
    assert sheet.empty_label.isVisible()
    sheet.search.clear()
    assert "h / j / k / l" in visible_keys(sheet)
    assert ":write path" not in visible_keys(sheet)
    assert not sheet.empty_label.isVisible()
    sheet.category.setCurrentIndex(0)
    assert ":write path" in visible_keys(sheet)
    assert sheet.intro.isVisible()


def test_korean_search_and_special_keys_are_plain_selectable_text(
    sheet: VimCheatSheetPage,
) -> None:
    sheet.search.setText("괄호")
    assert "%" in visible_keys(sheet)
    sheet.search.setText("<Esc>")
    assert "<Esc>" in visible_keys(sheet)
    for card in sheet.cards:
        for key in card.key_labels:
            assert key.textFormat() == Qt.TextFormat.PlainText
            assert key.textInteractionFlags() & (
                Qt.TextInteractionFlag.TextSelectableByMouse
            )


def test_entry_shows_poster_and_search_stays_visible_while_filtering(
    sheet: VimCheatSheetPage, qtbot: QtBot
) -> None:
    sheet.focus_entry()
    assert sheet.scroll_area.verticalScrollBar().value() == 0
    assert sheet.poster.mapTo(sheet.scroll_area.viewport(), QPoint()).y() == 0
    sheet.focus_search()
    qtbot.waitUntil(lambda: sheet.scroll_area.verticalScrollBar().value() > 0)
    qtbot.keyClicks(sheet.search, ":write")
    assert sheet.scroll_area.verticalScrollBar().value() > 0
    assert (
        sheet.scroll_area.viewport()
        .rect()
        .intersects(
            sheet.search.rect().translated(
                sheet.search.mapTo(sheet.scroll_area.viewport(), QPoint())
            )
        )
    )
    assert visible_keys(sheet) == {":write / :w", ":write path"}
    sheet.focus_entry()
    assert sheet.scroll_area.verticalScrollBar().value() == 0


@pytest.mark.parametrize("width,size,columns", [(1005, 20, 1), (1405, 20, 2)])
def test_zoom_reflows_without_clipping_commands_or_descriptions(
    sheet: VimCheatSheetPage, qtbot: QtBot, width: int, size: int, columns: int
) -> None:
    sheet.resize(width, 800)
    sheet.font_size.setValue(size)
    qtbot.waitUntil(lambda: sheet._column_count == columns)
    # Let nested Qt layouts apply their height-for-width calculations.
    qtbot.waitUntil(
        lambda: all(
            widget.heightForWidth(widget.width()) <= widget.height()
            for card in sheet.cards
            for widget in card.findChildren(QLabel)
        )
    )
    assert sheet.content.width() <= sheet.scroll_area.viewport().width()
    assert all(
        card.geometry().right() < card.parentWidget().width() for card in sheet.cards
    )
