"""일반 문서의 선택·복구·출처·기록 흐름을 검증한다."""

from __future__ import annotations

# Standard library imports
import sqlite3
from pathlib import Path

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.document_missions import (
    get_document_mission,
    list_document_missions,
)
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository
from vim_key_trainer.ui.edit_catalog import EditCategoryPage
from vim_key_trainer.ui.main_window import MainWindow

from ._support import press_edit_key


@pytest.mark.parametrize("mission_id", [m.id for m in list_document_missions()])
@pytest.mark.parametrize("mode", ["guided", "free"])
def test_real_document_missions_complete_with_colored_targets_and_independent_records(
    window: MainWindow,
    qtbot: QtBot,
    mission_id: str,
    mode: EditMode,
) -> None:
    window.prepare_document_mission(mission_id)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(0 if mode == "guided" else 1)
    session = page.session
    assert session is not None
    goal = page.goal_document.editor_state
    assert page.comparison.remaining_changes >= 3
    assert page.goal_document.change_spans
    assert not page.short_button.isVisible()
    assert not page.length_combo.isVisible()
    assert page.source_button.isVisible()
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    for key in session.lesson.baseline:
        press_edit_key(window, qtbot, key)
    assert session.state == SessionState.COMPLETED
    assert session.result is not None and session.result.stars == 3
    assert not page.goal_document.change_spans
    assert page.comparison.remaining_changes == 0
    assert page.goal_document.editor_state is goal
    assert page.result_summary.text() == (
        f"{session.result.key_count} / {session.result.baseline_keys}회"
    )
    assert page.result_time.text() == f"{session.result.elapsed_seconds:.1f}초"
    assert session.lesson.title in page.result_context.text()
    assert window.repository.best_edit_stars(mission_id, mode) == 3
    window.show_editing()
    assert "문서 복구 1/" in window.editing_menu_page.summary.text()
    assert "첫" in window.editing_menu_page.achievements.text()


def test_source_license_dialog_preserves_problem_and_requires_resume(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    mission = list_document_missions()[0]
    window.prepare_document_mission(mission.id)
    page = window.edit_practice
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    session = page.session
    assert session is not None
    snapshot = session.engine.snapshot()
    qtbot.mouseClick(page.source_button, Qt.MouseButton.LeftButton)
    assert page._source_dialog is not None and page._source_dialog.isVisible()
    assert session.engine.snapshot() == snapshot and session.key_count == 0
    assert session.state == SessionState.PAUSED
    page._source_dialog.close()
    assert session.state == SessionState.PAUSED
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.READY
    window.show_numbers()
    assert page._source_dialog is None


def test_explicit_document_gets_new_damage_and_keeps_mode(
    window: MainWindow, qtbot: QtBot
) -> None:
    first = list_document_missions()[0]
    window.prepare_document_mission(first.id)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    previous = page.session
    assert previous is not None
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    assert previous.state == SessionState.ABORTED
    assert page.session is not None
    assert page.session.lesson.id == first.id
    assert page.session.lesson.document_spec is not None
    assert previous.lesson.document_spec is not None
    assert page.session.lesson.document_spec.seed != previous.lesson.document_spec.seed
    assert page.session.mode == "free"
    assert page.session.key_count == 0


def test_general_document_card_emits_one_direct_launch(
    qtbot: QtBot,
) -> None:
    catalog = EditCategoryPage()
    qtbot.addWidget(catalog)
    catalog.show()
    catalog.refresh(MemoryResultRepository())
    assert not any(
        control.objectName().startswith("mission_")
        for control in catalog.findChildren(QPushButton)
    )
    launch = catalog.findChild(QPushButton, "editingGeneral")
    assert launch is not None
    launches = []
    catalog.general_requested.connect(lambda: launches.append(True))
    qtbot.mouseClick(launch, Qt.MouseButton.LeftButton)
    assert launches == [True]
    assert "웹 문서 구조대" in catalog.collection_progress.text()


def test_save_failure_can_retry_even_when_startup_already_has_warning(
    tmp_path: Path,
    qtbot: QtBot,
) -> None:
    path = tmp_path / "progress.sqlite3"
    repository = SqliteResultRepository(path)
    with sqlite3.connect(path) as database:
        database.execute(
            "CREATE TRIGGER fail_write BEFORE INSERT ON attempts "
            "BEGIN SELECT RAISE(FAIL, 'temporary failure'); END"
        )
    window = MainWindow(repository)
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.show_storage_warning("기존 기록 한 건을 제외했습니다.")
    window.prepare_document_mission(list_document_missions()[0].id)
    page = window.edit_practice
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    for key in session.lesson.baseline:
        press_edit_key(window, qtbot, key)
    assert session.state == SessionState.COMPLETED
    assert repository.pending_count == 1
    assert session.result in repository.results
    qtbot.waitUntil(window.storage_retry_button.isVisible, timeout=2500)
    with sqlite3.connect(path) as database:
        database.execute("DROP TRIGGER fail_write")
    qtbot.mouseClick(window.storage_retry_button, Qt.MouseButton.LeftButton)
    assert repository.pending_count == 0
    assert not window.storage_retry_button.isVisible()
    assert repository.completed_count == 1
    window.close()
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.completed_count == 1
    reopened.close()


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
    # OS별 마우스 포커스 이동과 분리해 문제 생성 실패 경로를 검증한다.
    page.new_problem_button.click()

    assert page.session is session
    assert session.state == SessionState.RUNNING
    assert session.engine.snapshot() == snapshot
    assert session.key_count == 1
    assert page.document_combo.currentData() == session.lesson.id
    assert "검증 실패" in page.feedback.text()
