"""문서 수정은 실제 Qt 키 이벤트만 엔진으로 전달한다."""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Iterator
from dataclasses import replace

# Third party imports
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.editing import EditMode, GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.qt_input import NormalizedKey


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[MainWindow]:
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()


def begin(
    window: MainWindow,
    qtbot: QtBot,
    lesson_id: str = "editing_numbers",
    mode: EditMode = "guided",
) -> EditingSession:
    window.prepare_editing_lesson(get_edit_lesson(lesson_id))
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(0 if mode == "guided" else 1)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    assert page.session is not None
    return page.session


def press(window: MainWindow, qtbot: QtBot, token: KeyToken) -> None:
    widget = window.edit_practice.practice_input
    if token.kind == "char":
        qtbot.keyClicks(widget, token.value)
    elif token.kind == "special":
        qtbot.keyClick(
            widget,
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
            widget, Qt.Key(ord(token.value.rsplit("+", 1)[1].upper())), modifier
        )


@pytest.mark.parametrize(
    ("lesson_id", "mode"),
    [
        (lesson_id, mode)
        for lesson_id in (
            "editing_numbers",
            "editing_delete_line",
            "editing_delete_word",
            "editing_append",
            "editing_compound",
            "editing_undo",
        )
        for mode in ("guided", "free")
        if lesson_id != "editing_undo" or mode != "free"
    ],
)
def test_packaged_lessons_complete_through_qt_keys(
    window: MainWindow,
    qtbot: QtBot,
    lesson_id: str,
    mode: EditMode,
) -> None:
    session = begin(window, qtbot, lesson_id, mode)
    page = window.edit_practice
    goal = page.goal_document.editor_state
    tokens = (
        tuple(key for step in session.lesson.guide for key in step.keys)
        if mode == "guided"
        else session.lesson.baseline
    )
    for token in tokens:
        press(window, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert page.stack.currentWidget() is page.result_page
    assert page.goal_document.editor_state == goal
    assert session.result is page.last_result
    assert session.result is not None and session.result.stars == 3
    assert session.key_count == len(tokens)
    assert window.repository.completed_count == 1
    assert window.repository.best_edit_stars(lesson_id, 1, mode) == 3
    assert page.result_summary.text() == (
        f"{session.result.key_count} / {session.result.baseline_keys}회"
    )
    assert "같음" in page.result_difference.text()
    assert page.result_time.text() == f"{session.result.elapsed_seconds:.1f}초"
    assert page.result_stars.text().count("★") == session.result.stars
    assert session.lesson.title in page.result_context.text()
    assert page.result_stars.geometry().right() < page.result_summary.geometry().left()
    assert page.result_summary.geometry().right() < page.result_time.geometry().left()
    if mode == "free":
        assert not page.result_accuracy.isVisible()
        assert session.result.accuracy is None
    else:
        assert page.result_accuracy.isVisible()
    count = len(window.repository.results)
    qtbot.keyClicks(page.practice_input, "x")
    assert len(window.repository.results) == count


def test_preparation_selects_mode_and_does_not_start_clock(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.show_technique_editing()
    lesson_button = window.editing_techniques_page.findChild(
        QPushButton, "lesson_editing_numbers"
    )
    assert lesson_button is not None
    qtbot.mouseClick(lesson_button, Qt.MouseButton.LeftButton)
    page = window.edit_practice
    assert window.stack.currentWidget() is page
    assert not page.practice_input.isEnabled()
    page.mode_combo.setCurrentIndex(1)
    assert page.session is not None and page.session.mode == "free"
    assert page.session.elapsed_seconds == 0
    assert page.session.engine.state == page.session.lesson.initial
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    assert not page.mode_combo.isEnabled()
    assert page.session.state == SessionState.READY


def test_guided_typo_is_counted_once_without_applying_it(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    session = begin(window, qtbot)
    before = session.engine.snapshot()
    qtbot.keyClicks(window.edit_practice.practice_input, "x")
    assert session.engine.snapshot() == before
    assert session.key_count == session.incorrect == 1
    assert session.token_index == 0
    assert session.state == SessionState.RUNNING
    press(window, qtbot, session.lesson.guide[0].keys[0])
    assert session.key_count == 2 and session.correct == 1
    assert session.accuracy == 50


def test_guide_overlay_tracks_accepted_prefix_and_resets_on_step_return(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    initial = EditorState(("abcdefghijklmnop",))
    goal = "abcdefghijklXnop"
    navigation = tuple(KeyToken("char", key) for key in "12l")
    replacement = tuple(KeyToken("char", key) for key in "rX")
    lesson = replace(
        get_edit_lesson("editing_numbers"),
        initial=initial,
        goal_lines=(goal,),
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(
            GuideStep(navigation, EditorState(initial.lines, column=12), "12칸 이동"),
            GuideStep(replacement, EditorState((goal,), column=12), "문자 교체"),
        ),
        baseline=navigation + replacement,
        baseline_keys=5,
    )
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    session = page.session
    assert session is not None
    overlay = page.comparison.guide_overlay
    assert overlay.isVisible()
    assert overlay.keys == navigation and overlay.completed == 0

    qtbot.keyClicks(page.practice_input, "1")
    assert overlay.completed == 1
    assert session.engine.state.lines == initial.lines
    qtbot.keyClicks(page.practice_input, "x")
    QApplication.sendEvent(
        page.practice_input,
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_2,
            Qt.KeyboardModifier.NoModifier,
            "2",
            True,
        ),
    )
    assert overlay.completed == 1
    assert session.key_count == 2 and session.token_index == 1
    qtbot.mouseClick(page.return_button, Qt.MouseButton.LeftButton)
    assert overlay.completed == 0 and overlay.keys == navigation
    assert session.key_count == 2 and session.step_returns == 1
    assert page.practice_input.hasFocus() and session.pause_count == 0

    qtbot.keyClicks(page.practice_input, "12l")
    assert overlay.keys == replacement and overlay.completed == 0
    qtbot.keyClicks(page.practice_input, "r")
    assert overlay.completed == 1
    qtbot.keyClicks(page.practice_input, "X")
    assert session.state == SessionState.COMPLETED
    assert not overlay.isVisible()


def test_guide_special_key_waits_for_real_escape(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    keys = (KeyToken("char", "i"), KeyToken("char", "a"), KeyToken("special", "esc"))
    goal = "atail"
    lesson = replace(
        get_edit_lesson("editing_numbers"),
        initial=EditorState(("tail",)),
        goal_lines=(goal,),
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(GuideStep(keys, EditorState((goal,)), "앞에 문자 추가"),),
        baseline=keys,
        baseline_keys=3,
    )
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "ia")
    session = page.session
    assert session is not None
    overlay = page.comparison.guide_overlay
    assert overlay.completed == 2 and overlay.keys[2].display == "<Esc>"
    qtbot.keyClicks(page.practice_input, "<Esc>")
    assert overlay.completed == 2
    assert session.engine.state.lines == (goal,)
    assert session.engine.state.mode == "insert"
    assert session.key_count == 7
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Escape)
    assert session.state == SessionState.COMPLETED
    assert session.key_count == 8


def test_free_guide_stays_hidden_through_mode_changes_and_attempt_controls(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.prepare_editing_lesson(get_edit_lesson("editing_numbers"))
    page = window.edit_practice
    overlay = page.comparison.guide_overlay
    assert overlay.isVisible()
    page.mode_combo.setCurrentIndex(1)
    assert not overlay.isVisible() and not overlay.keys
    page.mode_combo.setCurrentIndex(0)
    assert overlay.isVisible()
    page.mode_combo.setCurrentIndex(1)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    session = page.session
    assert session is not None and session.mode == "free"
    assert not overlay.isVisible()
    qtbot.keyClicks(page.practice_input, "$h")
    snapshot = session.engine.snapshot()
    assert not overlay.isVisible() and not overlay.keys
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.PAUSED
    assert not overlay.isVisible()
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.RUNNING
    assert not overlay.isVisible()
    assert session.engine.snapshot() == snapshot
    assert session.key_count == 2 and session.extra_hints == 0
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    assert page.session is not None and page.session.mode == "free"
    assert page.session.attempt_id != session.attempt_id
    assert page.session.key_count == 0 and page.session.extra_hints == 0
    assert not overlay.isVisible() and not overlay.keys


def test_free_shorter_solution_waits_for_escape_and_shows_negative_delta(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    session = begin(window, qtbot, mode="free")
    page = window.edit_practice
    qtbot.keyClicks(page.practice_input, "$hxi8")
    assert session.engine.state.lines == session.lesson.goal_lines
    assert session.engine.state.mode == "insert"
    assert session.state == SessionState.RUNNING
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Escape)
    assert session.state == SessionState.COMPLETED
    assert session.result is not None and session.result.delta == -1
    assert "1회 적게" in page.result_difference.text()
    assert session.result.accuracy is session.result.max_combo is None


def test_native_editing_paste_ime_repeat_mouse_and_shortcuts_cannot_bypass_engine(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    session = begin(window, qtbot, mode="free")
    widget = window.edit_practice.practice_input
    qtbot.keyClicks(widget, "i")
    snapshot = session.engine.snapshot()
    repeat = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier, "x", True
    )
    QApplication.sendEvent(widget, repeat)
    qtbot.keyClick(widget, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(widget, Qt.Key.Key_V, Qt.KeyboardModifier.MetaModifier)
    qtbot.keyClick(widget, Qt.Key.Key_Insert, Qt.KeyboardModifier.ShiftModifier)
    composition = QInputMethodEvent()
    composition.setCommitString("replacement")
    QApplication.sendEvent(widget, composition)
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert session.engine.snapshot() == snapshot
    assert session.key_count == 1
    assert not widget.acceptDrops()
    qtbot.keyClick(widget, Qt.Key.Key_Tab)
    qtbot.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert session.key_count == 3
    assert session.engine.snapshot() == snapshot
    assert widget.hasFocus()
    assert session.pause_count == 0


def test_step_return_and_restart_have_different_accounting(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    session = begin(window, qtbot)
    page = window.edit_practice
    for step in session.lesson.guide[:4]:
        for token in step.keys:
            press(window, qtbot, token)
    assert session.engine.state.lines != session.lesson.initial.lines
    key_count = session.key_count
    qtbot.mouseClick(page.return_button, Qt.MouseButton.LeftButton)
    assert session.key_count == key_count
    assert session.engine.state.lines == session.lesson.initial.lines
    assert session.step_returns == 1 and session.combo == 0
    assert page.practice_input.hasFocus()
    assert session.pause_count == 0
    for step in session.lesson.guide[session.step_index :]:
        for token in step.keys:
            press(window, qtbot, token)
    assert session.result is not None and session.result.stars == 1
    page.retry()
    assert page.session is not None and page.session.attempt_id != session.attempt_id
    assert page.session.key_count == 0 and page.session.elapsed_seconds == 0
    assert page.session.engine.state == session.lesson.initial


def test_focus_loss_pause_and_catalogs_keep_edit_records_separate(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    session = begin(window, qtbot, mode="free")
    page = window.edit_practice
    qtbot.keyClicks(page.practice_input, "$h")
    window.editing_button.setFocus()
    qtbot.waitUntil(lambda: session.state == SessionState.PAUSED)
    elapsed = session.elapsed_seconds
    page.practice_input.setFocus()
    qtbot.keyClicks(page.practice_input, "x")
    assert session.key_count == 2 and session.elapsed_seconds == elapsed
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "xi8")
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Escape)
    window.show_editing()
    assert "완료 1회" in window.editing_menu_page.summary.text()
    assert "완료 0회" in window.commands_summary.text()
    assert "완료 0회" in window.home_summary.text()
    assert window.repository.best_edit_stars("editing_numbers", 1, "guided") == 0
    assert window.repository.best_edit_stars("editing_numbers", 1, "free") == 3
    session = begin(window, qtbot)
    window.show_numbers()
    assert session.state == SessionState.ABORTED
    assert not page.timer.isActive()


def begin_word_problem(
    window: MainWindow,
    qtbot: QtBot,
    *,
    initial: EditorState,
    goal: str,
    baseline: str,
    final_column: int,
) -> EditingSession:
    keys = tuple(KeyToken("char", char) for char in baseline)
    lesson = replace(
        get_edit_lesson("editing_delete_word"),
        initial=initial,
        goal_lines=(goal,),
        allowed_commands=SUPPORTED_COMMANDS,
        guide=(
            GuideStep(
                keys,
                EditorState((goal,), column=final_column),
                "단어와 WORD의 범위를 구분해 목표 문서로 수정합니다.",
            ),
        ),
        baseline=keys,
        baseline_keys=len(keys),
    )
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(page.practice_input.hasFocus)
    assert page.session is not None
    return page.session


def test_free_word_commands_use_shift_keys_once_and_preserve_undo_accounting(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    initial = EditorState(("keep.one remove-two! tail extra",))
    session = begin_word_problem(
        window,
        qtbot,
        initial=initial,
        goal="keep.one tail",
        baseline="WdWWdiwx",
        final_column=12,
    )
    page = window.edit_practice
    widget = page.practice_input
    received: list[NormalizedKey] = []
    widget.key_received.connect(received.append)

    qtbot.keyClicks(widget, "W", Qt.KeyboardModifier.ShiftModifier)
    assert session.engine.state.column == 9
    assert session.key_count == 1
    qtbot.keyClicks(widget, "d")
    qtbot.keyClicks(widget, "W", Qt.KeyboardModifier.ShiftModifier)
    assert session.engine.state.lines == ("keep.one tail extra",)
    assert session.key_count == 3
    qtbot.keyClicks(widget, "u")
    assert session.engine.state.lines == initial.lines
    press(window, qtbot, KeyToken("chord", "ctrl+r"))
    assert session.engine.state.lines == ("keep.one tail extra",)
    assert session.key_count == 5

    qtbot.keyClicks(widget, "W", Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClicks(widget, "diw")
    assert session.engine.state.lines == ("keep.one tail ",)
    assert session.state == SessionState.RUNNING
    qtbot.keyClicks(widget, "x")

    assert session.state == SessionState.COMPLETED
    assert session.engine.state.lines == session.lesson.goal_lines
    assert session.key_count == 10
    assert sum(key.token is not None for key in received) == session.key_count
    assert widget.editor_state == session.engine.state
    assert session.result is not None and session.result.delta == 2
    assert window.repository.completed_count == 1
    assert page.stack.currentWidget() is page.result_page


def test_free_inner_word_pending_escape_counts_keys_without_entering_insert(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    initial = EditorState(("remove.one tail",), column=2)
    session = begin_word_problem(
        window,
        qtbot,
        initial=initial,
        goal=".one tail",
        baseline="diw",
        final_column=0,
    )
    widget = window.edit_practice.practice_input
    qtbot.keyClicks(widget, "di")
    assert session.engine.state.pending == "di"
    assert session.engine.state.mode == "normal"
    assert session.engine.state.lines == initial.lines
    assert session.key_count == 2

    qtbot.keyClick(widget, Qt.Key.Key_Escape)
    assert session.engine.state.pending == ""
    assert session.engine.state.lines == initial.lines
    assert session.key_count == 3
    assert session.state == SessionState.RUNNING

    qtbot.keyClicks(widget, "diw")
    assert session.engine.state.lines == (".one tail",)
    assert session.engine.state.mode == "normal"
    assert session.state == SessionState.COMPLETED
    assert session.key_count == 6
    assert session.result is not None and session.result.delta == 3
