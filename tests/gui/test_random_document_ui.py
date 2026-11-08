"""무작위 원문 선택과 콤보박스 변경이 새 시도를 올바르게 만든다."""

from __future__ import annotations

# Standard library imports
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.document_missions import get_document_mission
from vim_key_trainer.domain.sessions import SessionState
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


def test_single_launch_selects_random_document_and_uses_smaller_editor_font(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.show_editing()
    launch = window.editing_menu_page.findChild(QPushButton, "editingGeneral")
    assert launch is not None
    qtbot.mouseClick(launch, Qt.MouseButton.LeftButton)
    page = window.edit_practice
    assert window.stack.currentWidget() is page
    assert page.session is not None and page.session.lesson.document_spec is not None
    assert page.document_combo.currentData() == ""
    assert page.document_combo.count() == 17
    assert page.practice_input.font_size == page.goal_document.font_size == 12
    assert page.document_font_spin.value() == 12
    assert window.font_spin.value() == 23
    assert page.session.state == SessionState.READY
    assert page.session.key_count == 0 and page.session.elapsed_seconds == 0


def test_document_combo_can_replace_running_attempt_without_counting_gui_keys(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.prepare_document_mission("mission_flask_python", seed=42)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    previous = page.session
    assert previous is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "j")
    assert previous.key_count == 1
    assert page.document_combo.isEnabled()
    page.document_combo.setFocus()
    qtbot.keyClick(page.document_combo, Qt.Key.Key_End)
    current = page.session
    assert current is not None and current is not previous
    assert previous.state == SessionState.ABORTED
    assert previous.key_count == 1
    assert current.state == SessionState.READY and current.mode == "free"
    assert current.key_count == 0 and current.elapsed_seconds == 0
    assert current.lesson.document_spec is not None
    assert current.lesson.id == page.document_combo.currentData()
    assert current.lesson.id != previous.lesson.id
    assert (
        page.goal_document.language == get_document_mission(current.lesson.id).language
    )
    assert current.extra_hints == current.step_returns == 0
    assert previous.result in window.repository.results


def test_retry_keeps_actual_random_document_and_new_problem_avoids_it(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window.prepare_random_document()
    page = window.edit_practice
    original = page.session
    assert original is not None and original.lesson.document_spec is not None
    page.document_font_spin.setValue(12)
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    retried = page.session
    assert retried is not None
    assert retried.lesson.document_spec == original.lesson.document_spec
    assert retried.lesson.initial == original.lesson.initial
    assert retried.attempt_id != original.attempt_id
    assert page.document_combo.currentData() == ""
    assert page.practice_input.font_size == 12
    monkeypatch.setattr("vim_key_trainer.ui.edit_practice.randbelow", lambda _limit: 0)
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert fresh is not None and fresh.lesson.document_spec is not None
    assert fresh.lesson.id != original.lesson.id
    assert fresh.lesson.document_spec.seed != original.lesson.document_spec.seed
    assert page.document_combo.currentData() == ""
    assert page.practice_input.font_size == 12


def test_editor_font_change_preserves_content_and_key_count(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.prepare_document_mission("mission_fmt_cpp", seed=7)
    page = window.edit_practice
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    state = session.engine.snapshot()
    goal = page.goal_document.editor_state
    page.document_font_spin.setValue(16)
    assert session.engine.snapshot() == state
    assert page.goal_document.editor_state is goal
    assert session.key_count == 0
    assert page.goal_document.change_spans
    assert page.practice_input.font_size == page.goal_document.font_size == 16


def test_taller_document_view_still_keeps_controls_visible_at_minimum_window(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.prepare_document_mission("mission_flask", seed=1)
    page = window.edit_practice
    qtbot.wait(1)
    assert page.comparison.height() >= 480
    window.resize(960, 680)
    qtbot.wait(1)
    assert page.comparison.height() >= 330
    for control in (page.start_button, page.new_problem_button, page.source_button):
        bounds = control.rect().translated(
            control.mapTo(window, control.rect().topLeft())
        )
        assert window.rect().contains(bounds)


def test_invalid_document_switch_keeps_current_problem_and_selection(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window.prepare_document_mission("mission_flask", seed=8)
    page = window.edit_practice
    previous = page.session
    assert previous is not None
    snapshot = previous.engine.snapshot()

    def invalid_problem(_spec: object) -> None:
        raise ValueError("복구 풀이 검증 실패")

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.create_random_document_problem",
        invalid_problem,
    )
    page.document_combo.setCurrentIndex(page.document_combo.findData("mission_fmt_cpp"))
    assert page.session is previous
    assert page.document_combo.currentData() == previous.lesson.id
    assert previous.engine.snapshot() == snapshot
    assert previous.key_count == 0
    assert "검증 실패" in page.feedback.text()


def test_failed_new_document_keeps_running_attempt(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window.prepare_document_mission("mission_flask", seed=8)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "j")
    snapshot = session.engine.snapshot()

    def invalid_problem(_spec: object) -> None:
        raise ValueError("복구 풀이 검증 실패")

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.create_random_document_problem",
        invalid_problem,
    )
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)

    assert page.session is session
    assert session.state == SessionState.PAUSED
    assert session.engine.snapshot() == snapshot
    assert session.key_count == 1
    assert page.document_combo.currentData() == session.lesson.id
    assert "검증 실패" in page.feedback.text()
