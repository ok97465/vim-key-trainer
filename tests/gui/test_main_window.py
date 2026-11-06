from __future__ import annotations

# Standard library imports
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.exercises import EXERCISES, PracticeSpec
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.session_service import PracticeSession
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


def begin(
    window: MainWindow,
    qtbot: QtBot,
    *,
    exercise_id: str = "numbers",
    length: int = 30,
    width: int = 20,
    seed: int = 42,
) -> PracticeSession:
    window.prepare_practice(
        exercise_id,
        PracticeSpec(
            exercise_id=exercise_id,
            target_length=length,
            display_width=width,
            seed=seed,
        ),
    )
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(window.practice_input.hasFocus)
    assert window.session is not None
    return window.session


def test_menu_opens_ready_practice_without_starting_clock(
    window: MainWindow, qtbot: QtBot
) -> None:
    assert window.stack.currentWidget() is window.home_page
    window.prepare_practice("numbers")
    assert window.session is not None
    assert window.stack.currentWidget() is window.practice_page
    assert window.session.state == SessionState.READY
    assert not window.practice_input.isEnabled()
    assert len(window.session.target) == 100
    qtbot.wait(30)
    assert window.session.elapsed_seconds == 0
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(window.practice_input.hasFocus)
    qtbot.wait(30)
    assert window.session.elapsed_seconds == 0
    qtbot.keyClicks(window.practice_input, "a")
    assert window.session.state == SessionState.RUNNING
    assert window.session.incorrect == 1


@pytest.mark.parametrize("exercise_id", [exercise.id for exercise in EXERCISES])
def test_all_four_lessons_complete_through_real_key_events(
    window: MainWindow, qtbot: QtBot, exercise_id: str
) -> None:
    session = begin(window, qtbot, exercise_id=exercise_id, length=20)
    qtbot.keyClicks(window.practice_input, session.target)
    assert session.state == SessionState.COMPLETED
    assert window.stack.currentWidget() is window.result_page
    assert session.result is window.last_result
    assert session.result is not None
    assert session.result.correct == 20
    assert session.result.incorrect == 0
    assert session.result.stars == 3
    assert window.repository.completed_count == 1
    assert window.repository.best_stars(exercise_id) == 3


def test_typo_holds_target_and_backspace_does_not_erase_error(
    window: MainWindow, qtbot: QtBot
) -> None:
    session = begin(window, qtbot)
    qtbot.keyClicks(window.practice_input, "a")
    qtbot.keyClick(window.practice_input, Qt.Key.Key_Backspace)
    assert session.position == 0
    assert session.incorrect == 1
    qtbot.keyClicks(window.practice_input, session.target[0])
    assert session.position == 1
    assert session.incorrect == 1
    assert session.accuracy == 50


def test_twenty_character_boundary_has_no_lost_or_duplicated_input(
    window: MainWindow, qtbot: QtBot
) -> None:
    session = begin(window, qtbot, length=100)
    qtbot.keyClicks(window.practice_input, session.target[:20])
    assert session.position == window.practice_input.position == 20
    assert session.state == SessionState.RUNNING
    assert window.practice_input.hasFocus()
    qtbot.keyClicks(window.practice_input, session.target[20:21])
    assert session.position == 21
    qtbot.keyClicks(window.practice_input, session.target[21:])
    assert session.state == SessionState.COMPLETED
    assert session.position == 100
    assert session.max_combo == 100
    assert window.repository.completed_count == 1
    # A late input cannot create another attempt or save the result twice.
    qtbot.keyClicks(window.practice_input, "1")
    assert window.repository.completed_count == 1
    assert len(window.repository.results) == 1


def test_paste_repeat_and_ime_do_not_advance_or_count(
    window: MainWindow, qtbot: QtBot
) -> None:
    session = begin(window, qtbot)
    first = session.target[0]
    repeat = QKeyEvent(
        QEvent.Type.KeyPress,
        ord(first),
        Qt.KeyboardModifier.NoModifier,
        first,
        True,
    )
    QApplication.sendEvent(window.practice_input, repeat)
    qtbot.keyClick(
        window.practice_input, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier
    )
    qtbot.keyClick(
        window.practice_input, Qt.Key.Key_Insert, Qt.KeyboardModifier.ShiftModifier
    )
    composition = QInputMethodEvent()
    composition.setCommitString(session.target)
    QApplication.sendEvent(window.practice_input, composition)
    assert session.state == SessionState.READY
    assert session.position == session.incorrect == 0
    assert session.elapsed_seconds == 0


def test_tab_is_one_scored_key_and_keeps_practice_focus(
    window: MainWindow, qtbot: QtBot
) -> None:
    session = begin(window, qtbot)
    qtbot.keyClick(window.practice_input, Qt.Key.Key_Tab)
    assert session.incorrect == 1
    assert session.position == 0
    assert window.practice_input.hasFocus()
    assert session.pause_count == 0


def test_mouse_pause_requires_explicit_resume(window: MainWindow, qtbot: QtBot) -> None:
    session = begin(window, qtbot)
    qtbot.keyClicks(window.practice_input, session.target[0])
    qtbot.mouseClick(window.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.PAUSED
    paused_time = session.elapsed_seconds
    qtbot.keyClicks(window.practice_input, session.target[1])
    qtbot.wait(20)
    assert session.position == 1
    assert session.elapsed_seconds == paused_time
    assert session.pause_count == 1
    qtbot.mouseClick(window.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.RUNNING
    qtbot.waitUntil(window.practice_input.hasFocus)
    qtbot.keyClicks(window.practice_input, session.target[1])
    assert session.position == 2


def test_focus_loss_pauses_and_focus_return_does_not_resume(
    window: MainWindow, qtbot: QtBot
) -> None:
    session = begin(window, qtbot)
    qtbot.keyClicks(window.practice_input, session.target[0])
    window.home_button.setFocus()
    qtbot.waitUntil(lambda: session.state == SessionState.PAUSED)
    window.practice_input.setFocus()
    qtbot.keyClicks(window.practice_input, session.target[1])
    assert session.position == 1
    assert session.pause_count == 1
    assert session.state == SessionState.PAUSED
    qtbot.mouseClick(window.pause_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(window.practice_input, session.target[1])
    assert session.position == 2


def test_retry_keeps_target_and_seed_but_uses_new_attempt(
    window: MainWindow, qtbot: QtBot
) -> None:
    previous = begin(window, qtbot, length=20)
    qtbot.keyClicks(window.practice_input, previous.target)
    window.retry()
    assert window.session is not None
    assert window.session.target == previous.target
    assert window.session.spec == previous.spec
    assert window.session.attempt_id != previous.attempt_id
    assert window.session.state == SessionState.READY
    assert window.repository.completed_count == 1


def test_new_problem_changes_seed_and_target_and_preserves_settings(
    window: MainWindow, qtbot: QtBot
) -> None:
    previous = begin(window, qtbot)
    window.new_problem()
    assert window.session is not None
    assert previous.state == SessionState.ABORTED
    assert window.session.spec.seed != previous.spec.seed
    assert window.session.target != previous.target
    assert window.session.spec.display_width == previous.spec.display_width
    assert window.session.spec.target_length == previous.spec.target_length
    assert window.session.state == SessionState.READY


def test_restart_and_menu_abort_without_awarding_stars(
    window: MainWindow, qtbot: QtBot
) -> None:
    previous = begin(window, qtbot)
    qtbot.keyClicks(window.practice_input, previous.target[:3])
    qtbot.mouseClick(window.restart_button, Qt.MouseButton.LeftButton)
    assert previous.state == SessionState.ABORTED
    assert previous.result is not None
    assert previous.result.stars == 0
    assert window.session is not None
    assert window.session.attempt_id != previous.attempt_id
    assert window.session.target == previous.target
    assert window.session.position == 0
    window.show_home()
    assert window.session.state == SessionState.ABORTED
    assert window.stack.currentWidget() is window.home_page
    assert window.repository.completed_count == 0
    assert window.repository.best_stars("numbers") == 0


def test_forty_character_display_still_completes_without_confirmation(
    window: MainWindow, qtbot: QtBot
) -> None:
    session = begin(window, qtbot, length=50, width=40)
    assert window.practice_input.display_width == 40
    qtbot.keyClicks(window.practice_input, session.target[:40])
    assert session.position == 40
    assert window.practice_input.hasFocus()
    qtbot.keyClicks(window.practice_input, session.target[40:])
    assert session.state == SessionState.COMPLETED
    assert session.result is not None
    assert session.result.correct == 50


def test_menu_click_uses_settings_and_result_retry_preserves_problem(
    window: MainWindow, qtbot: QtBot
) -> None:
    window.show_settings()
    window.length_combo.setCurrentIndex(0)  # 20자
    window.width_combo.setCurrentIndex(2)  # 40자 표시
    window.show_home()
    lesson = window.home_page.findChild(QPushButton, "lesson_numbers")
    assert lesson is not None
    qtbot.mouseClick(lesson, Qt.MouseButton.LeftButton)
    assert window.session is not None
    original = window.session
    assert original.spec.target_length == 20
    assert original.spec.display_width == 40
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(window.practice_input, original.target)
    retry_button = next(
        item
        for item in window.result_page.findChildren(QPushButton)
        if item.accessibleName() == "retryResult"
    )
    qtbot.mouseClick(retry_button, Qt.MouseButton.LeftButton)
    assert window.session is not original
    assert window.session.target == original.target
    assert window.session.attempt_id != original.attempt_id
    assert window.session.state == SessionState.READY


def test_diagnostics_does_not_score_an_aborted_practice(
    window: MainWindow, qtbot: QtBot
) -> None:
    session = begin(window, qtbot)
    window.show_diagnostics()
    qtbot.keyClicks(window.diagnostic_input, "3")
    assert session.state == SessionState.ABORTED
    assert session.position == session.incorrect == 0
    assert window.repository.completed_count == 0
    assert "char / 3" in window.diagnostic_text.text()
