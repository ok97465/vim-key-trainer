"""확장한 자유풀이의 키·선택·명령행·실제 화면 이동을 검증한다."""

from __future__ import annotations

# Standard library imports
import sys
from dataclasses import replace

# Third party imports
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.editing import GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.main_window import MainWindow


def prepare_free(
    qtbot: QtBot, lines: tuple[str, ...]
) -> tuple[MainWindow, EditingSession]:
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1100, 850)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    baseline = tuple(KeyToken("char", char) for char in "ggdGidone") + (
        KeyToken("special", "esc"),
    )
    lesson = replace(
        get_edit_lesson("editing_numbers"),
        initial=EditorState(lines),
        goal_lines=("done",),
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        baseline=baseline,
        baseline_keys=len(baseline),
        guide=(GuideStep(baseline, EditorState(("done",), column=3), "복구합니다."),),
    )
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    assert page.session is not None
    return window, page.session


def control(qtbot: QtBot, window: MainWindow, key: Qt.Key) -> None:
    modifier = (
        Qt.KeyboardModifier.MetaModifier
        if sys.platform == "darwin"
        else Qt.KeyboardModifier.ControlModifier
    )
    qtbot.keyClick(window.edit_practice.practice_input, key, modifier)


def test_change_object_undo_redo_and_replace_are_real_qt_keys(qtbot: QtBot) -> None:
    original = ('name = "bad"; count = 9',)
    window, session = prepare_free(qtbot, original)
    widget = window.edit_practice.practice_input
    qtbot.keyClicks(widget, 'ci"good')
    assert session.engine.state.mode == "insert"
    qtbot.keyClick(widget, Qt.Key.Key_Escape)
    assert session.engine.state.lines == ('name = "good"; count = 9',)
    assert session.key_count == 8
    qtbot.keyClicks(widget, "u")
    assert session.engine.state.lines == original
    control(qtbot, window, Qt.Key.Key_R)
    assert session.engine.state.lines == ('name = "good"; count = 9',)
    qtbot.keyClicks(widget, "$r8")
    assert session.engine.state.lines == ('name = "good"; count = 8',)
    control(qtbot, window, Qt.Key.Key_A)
    assert session.engine.state.lines == ('name = "good"; count = 9',)
    assert session.key_count == 14
    assert widget.hasFocus()


def test_visual_replace_clears_selection_and_groups_insert_undo(qtbot: QtBot) -> None:
    original = ("first", "second", "third")
    window, session = prepare_free(qtbot, original)
    widget = window.edit_practice.practice_input
    qtbot.keyClicks(widget, "llvjR")
    assert session.engine.state.lines == ("", "third")
    assert session.engine.state.mode == "insert"
    assert session.engine.state.visual_anchor is None
    qtbot.keyClicks(widget, "X")
    qtbot.keyClick(widget, Qt.Key.Key_Return)
    qtbot.keyClicks(widget, "Y")
    qtbot.keyClick(widget, Qt.Key.Key_Escape)
    assert session.engine.state.lines == ("X", "Y", "third")
    assert session.engine.state.mode == "normal"
    assert session.key_count == 9
    qtbot.keyClicks(widget, "u")
    assert session.engine.state.lines == original
    control(qtbot, window, Qt.Key.Key_R)
    assert session.engine.state.lines == ("X", "Y", "third")
    assert session.key_count == 11
    assert widget.hasFocus()


def test_counted_dot_replaces_motion_count_through_qt_keys(qtbot: QtBot) -> None:
    words = tuple(f"word{index}" for index in range(15))
    window, session = prepare_free(qtbot, (" ".join(words),))
    widget = window.edit_practice.practice_input
    qtbot.keyClicks(widget, '"ad2w3..')
    assert session.engine.state.lines == (" ".join(words[8:]),)
    assert session.key_count == 8
    qtbot.keyClicks(widget, "u")
    assert session.engine.state.lines == (" ".join(words[5:]),)
    control(qtbot, window, Qt.Key.Key_R)
    assert session.engine.state.lines == (" ".join(words[8:]),)
    assert widget.hasFocus()


def test_percentage_operator_and_failed_match_through_qt_keys(qtbot: QtBot) -> None:
    lines = ("alpha", "beta", "gamma", "delta")
    window, session = prepare_free(qtbot, lines)
    widget = window.edit_practice.practice_input
    qtbot.keyClicks(widget, "lld%c%")
    assert session.engine.state.lines == lines
    assert session.engine.state.mode == "normal"
    qtbot.keyClicks(widget, "d50%")
    assert session.engine.state.lines == ("gamma", "delta")
    qtbot.keyClicks(widget, "u")
    assert session.engine.state.lines == lines
    assert session.key_count == 11
    assert widget.hasFocus()


def test_search_and_ex_prompt_support_edit_confirm_and_cancel(qtbot: QtBot) -> None:
    window, session = prepare_free(qtbot, ("first", "token = bad", "last"))
    page = window.edit_practice
    widget = page.practice_input
    qtbot.keyClicks(widget, "/tokex")
    qtbot.keyClick(widget, Qt.Key.Key_Backspace)
    qtbot.keyClicks(widget, "n")
    assert page.command_prompt.text() == "/token"
    assert session.engine.state.row == 0
    qtbot.keyClick(widget, Qt.Key.Key_Return)
    assert session.engine.state.row == 1
    assert not page.command_prompt.text()
    qtbot.keyClicks(widget, "/missing")
    qtbot.keyClick(widget, Qt.Key.Key_Escape)
    assert session.engine.state.row == 1
    assert not session.engine.state.pending
    qtbot.keyClicks(widget, ":%s/bad/good/g")
    assert page.command_prompt.text() == ":%s/bad/good/g"
    qtbot.keyClick(widget, Qt.Key.Key_Return)
    assert session.engine.state.lines == ("first", "token = good", "last")
    qtbot.keyClicks(widget, "u")
    assert session.engine.state.lines == ("first", "token = bad", "last")
    assert widget.hasFocus()


def test_block_selection_is_painted_and_command_paste_remains_excluded(
    qtbot: QtBot,
) -> None:
    window, session = prepare_free(qtbot, ("abcde", "fghij", "klmno"))
    widget = window.edit_practice.practice_input
    paste_modifier = (
        Qt.KeyboardModifier.ControlModifier
        if sys.platform == "darwin"
        else Qt.KeyboardModifier.MetaModifier
    )
    qtbot.keyClick(widget, Qt.Key.Key_V, paste_modifier)
    assert session.key_count == 0
    control(qtbot, window, Qt.Key.Key_V)
    qtbot.keyClicks(widget, "jl")
    assert session.engine.state.mode == "visual_block"
    image = widget.grab().toImage()
    scale = image.devicePixelRatio()
    selection = image.copy(
        round(58 * scale),
        round(16 * scale),
        round(widget.document_metrics.horizontalAdvance("ab") * scale),
        round(widget.document_metrics.lineSpacing() * scale),
    )
    assert any(
        selection.pixelColor(x, y).name() == "#3d506a"
        for x in range(selection.width())
        for y in range(selection.height())
    )
    qtbot.keyClicks(widget, "d")
    assert session.engine.state.lines == ("cde", "hij", "klmno")
    assert session.engine.state.mode == "normal"
    assert session.key_count == 4
    qtbot.keyClicks(widget, "u")
    assert session.engine.state.lines == ("abcde", "fghij", "klmno")
    assert widget.hasFocus()


def test_hybrid_numbers_follow_cursor_without_renumbering_goal(qtbot: QtBot) -> None:
    window, session = prepare_free(qtbot, tuple(f"line {i}" for i in range(25)))
    widget = window.edit_practice.practice_input
    image = widget.grab().toImage()
    scale = image.devicePixelRatio()
    number_box = tuple(round(value * scale) for value in (4, 16, 42, 24))
    before = image.copy(*number_box)
    qtbot.keyClicks(widget, "10G")
    assert session.engine.state.row == 9
    assert [widget.line_number_text(row) for row in (0, 8, 9, 10, 24)] == [
        "9",
        "1",
        "10",
        "1",
        "15",
    ]
    after = widget.grab().toImage().copy(*number_box)
    assert before != after
    assert window.edit_practice.goal_document.line_number_text(0) == "1"
    assert session.key_count == 3


def test_page_motion_uses_current_viewport_and_preserves_focus(qtbot: QtBot) -> None:
    lines = tuple(f"line {i}" for i in range(100))
    window, session = prepare_free(qtbot, lines)
    page = window.edit_practice
    rows = page.comparison.viewport_rows
    control(qtbot, window, Qt.Key.Key_D)
    assert session.engine.state.row == rows // 2
    assert session.engine.state.viewport_rows == rows
    assert page.document_scroll.verticalScrollBar().value() > 0
    qtbot.keyClicks(page.practice_input, "L")
    assert session.engine.state.row == session.engine.state.viewport_top + rows - 1
    page.document_font_spin.setValue(20)
    qtbot.waitUntil(lambda: page.comparison.viewport_rows < rows)
    previous_row = session.engine.state.row
    current_rows = page.comparison.viewport_rows
    control(qtbot, window, Qt.Key.Key_F)
    assert session.engine.state.viewport_rows == current_rows
    assert session.engine.state.row > previous_row
    assert session.engine.state.lines == lines
    assert session.key_count == 3
    assert page.practice_input.hasFocus()
