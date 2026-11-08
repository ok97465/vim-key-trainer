"""실제 문서 미션의 복구·색상·출처·컬렉션 진행도를 검증한다."""

from __future__ import annotations

# Standard library imports
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.document_missions import list_document_missions
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository
from vim_key_trainer.ui.edit_catalog import EditCategoryPage
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
        press(window, qtbot, key)
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
    assert (
        window.repository.best_edit_stars(
            mission_id, session.lesson.content_version, mode
        )
        == 3
    )
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
        press(window, qtbot, key)
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
