"""문서 종류 선택부터 코드 편집·재도전·모드별 기록까지 실제 키로 검증한다."""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QTextBrowser
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.content.document_missions import list_document_missions
from vim_key_trainer.domain.edit_generator import get_edit_profile
from vim_key_trainer.domain.editing import EditLesson, EditMode, EditPracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.edit_catalog import EditCategoryPage
from vim_key_trainer.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:
    monkeypatch.setattr(
        "vim_key_trainer.ui.main_window.randbelow", lambda limit: 41 % limit
    )
    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.randbelow", lambda limit: 47 % limit
    )
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


def test_peer_cards_open_documents_or_techniques_and_keep_return_destinations(
    window: MainWindow, qtbot: QtBot
) -> None:
    qtbot.mouseClick(window.editing_button, Qt.MouseButton.LeftButton)
    menu = window.editing_menu_page
    assert window.stack.currentWidget() is menu
    choices = {
        control.objectName()
        for control in menu.findChildren(QPushButton)
        if control.objectName().startswith(
            ("editingGeneral", "editingTechniques", "lesson_code_")
        )
    }
    assert choices == {
        "editingGeneral",
        "editingTechniques",
        "lesson_code_python",
        "lesson_code_cpp",
        "lesson_code_json",
    }
    general = menu.findChild(QPushButton, "editingGeneral")
    assert general is not None
    qtbot.mouseClick(general, Qt.MouseButton.LeftButton)
    page = window.edit_practice
    assert window.stack.currentWidget() is page
    assert page.session is not None and page.session.lesson.document_spec is not None
    assert page.document_combo.currentData() == ""
    qtbot.mouseClick(page.leave_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is menu
    techniques = menu.findChild(QPushButton, "editingTechniques")
    assert techniques is not None
    qtbot.mouseClick(techniques, Qt.MouseButton.LeftButton)
    technique_page = window.editing_techniques_page
    assert window.stack.currentWidget() is technique_page
    start = technique_page.findChild(QPushButton, "lesson_editing_numbers")
    assert start is not None
    qtbot.mouseClick(start, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is page
    assert page.session is not None and page.session.lesson.practice_spec is not None
    assert page.session.lesson.id == "editing_numbers"
    assert page.session.lesson.practice_spec.document_lines == 24
    assert not page.document_combo.isVisible()
    qtbot.mouseClick(page.leave_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is technique_page
    back = technique_page.findChild(QPushButton, "editingToCategories")
    assert back is not None
    qtbot.mouseClick(back, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is menu


@pytest.mark.parametrize("error_type", [ValueError, FileNotFoundError])
def test_json_card_remains_available_when_project_corpus_is_unavailable(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[ValueError] | type[OSError],
) -> None:
    def fail() -> None:
        raise error_type("코드 원문 파일이 없습니다.")

    monkeypatch.setattr("vim_key_trainer.ui.edit_catalog.load_code_sources", fail)
    menu = EditCategoryPage()
    qtbot.addWidget(menu)
    json_start = menu.findChild(QPushButton, "lesson_code_json")
    python_start = menu.findChild(QPushButton, "lesson_code_python")
    assert json_start is not None and json_start.isEnabled()
    assert python_start is not None and not python_start.isEnabled()


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp", "code_json"])
def test_code_card_opens_long_highlighted_document_before_clock_starts(
    window: MainWindow, qtbot: QtBot, profile_id: str
) -> None:
    window.show_editing()
    start = window.editing_menu_page.findChild(QPushButton, f"lesson_{profile_id}")
    assert start is not None
    if profile_id == "code_python":
        start.setFocus()
        qtbot.keyClick(start, Qt.Key.Key_Return)
    else:
        qtbot.mouseClick(start, Qt.MouseButton.LeftButton)
    page = window.edit_practice
    profile = get_edit_profile(profile_id)
    assert window.stack.currentWidget() is page
    session = page.session
    assert session is not None and session.lesson.practice_spec is not None
    assert session.lesson.id == profile_id
    if profile_id == "code_json":
        assert len(session.engine.state.lines) == 60
    else:
        assert 300 <= len(session.engine.state.lines) <= 500
    assert not page.length_combo.isVisible() and not page.short_button.isVisible()
    assert (
        page.practice_input.language == page.goal_document.language == profile.language
    )
    assert page.practice_input.syntax_spans and page.goal_document.syntax_spans
    assert page.goal_document.change_spans
    excerpt = session.lesson.code_excerpt
    if profile_id == "code_json":
        assert excerpt is None
        assert not page.document_combo.isVisible()
        assert not page.source_button.isVisible()
        assert not page.code_source_summary.isVisible()
    else:
        assert page.document_combo.isVisible() and page.document_combo.isEnabled()
        assert page.document_combo.currentData() == ""
        assert page.document_combo.itemText(0) == "무작위 코드 문서"
        assert {
            page.document_combo.itemData(index)
            for index in range(1, page.document_combo.count())
        } == {
            item.source.id
            for item in load_code_sources()
            if item.source.language == profile.language
        }
        assert page.source_button.isVisible() and page.code_source_summary.isVisible()
        assert excerpt is not None
        source_summary = page.code_source_summary.text()
        assert excerpt.source.project in source_summary
        assert excerpt.source.title in source_summary
        assert f"{excerpt.start_line}~{excerpt.end_line}행" in source_summary
    assert session.state == SessionState.READY
    assert session.key_count == 0 and session.elapsed_seconds == 0
    assert not page.practice_input.isEnabled() and page.start_button.hasFocus()


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp", "code_json"])
def test_code_retry_keeps_excerpt_and_new_problem_restores_general_options(
    window: MainWindow, qtbot: QtBot, profile_id: str
) -> None:
    profile = get_edit_profile(profile_id)
    spec = EditPracticeSpec(
        profile_id, seed=73, document_lines=profile.default_document_lines
    )
    window.prepare_editing(profile_id, spec)
    page = window.edit_practice
    assert page.session is not None
    original = page.session.lesson
    assert not page.length_combo.isVisible() and not page.short_button.isVisible()
    page.mode_combo.setCurrentIndex(1)
    previous = page.session
    assert previous is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "j")
    assert previous.key_count == 1
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    retried = page.session
    assert retried is not None
    assert previous.state == SessionState.ABORTED
    assert retried.attempt_id != previous.attempt_id
    assert retried.lesson.signature == original.signature
    assert retried.lesson.code_excerpt == original.code_excerpt
    assert retried.mode == "free" and retried.key_count == 0
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    current = page.session
    assert current is not None and current.lesson.practice_spec is not None
    assert current.lesson.id == profile_id
    assert current.lesson.practice_spec.seed != spec.seed
    if profile_id == "code_json":
        assert current.lesson.practice_spec.document_lines == 60
    else:
        assert 300 <= current.lesson.practice_spec.document_lines <= 500
    assert current.mode == "free" and current.state == SessionState.READY
    assert current.lesson.signature != original.signature
    assert page.practice_input.language == profile.language
    assert not page.length_combo.isVisible() and not page.short_button.isVisible()
    window.prepare_editing("editing_numbers")
    assert page.length_combo.isVisible() and page.short_button.isVisible()
    assert page.length_combo.currentData() == 24
    assert page.length_combo.count() == 3
    page.length_combo.setCurrentIndex(page.length_combo.findData(40))
    assert page.session is not None and page.session.lesson.practice_spec is not None
    assert page.session.lesson.practice_spec.document_lines == 40
    assert page.practice_input.language == "text"
    assert not page.code_source_summary.isVisible()
    assert not page.source_button.isVisible()


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp", "code_json"])
@pytest.mark.parametrize("mode", ["guided", "free"])
def test_code_baseline_completes_through_qt_and_keeps_mode_records_separate(
    window: MainWindow, qtbot: QtBot, profile_id: str, mode: EditMode
) -> None:
    profile = get_edit_profile(profile_id)
    spec = EditPracticeSpec(
        profile_id, seed=41, document_lines=profile.document_lengths[0]
    )
    window.prepare_editing(profile_id, spec)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(0 if mode == "guided" else 1)
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    for token in session.lesson.baseline:
        press(window, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.result is not None and session.result.stars == 3
    assert page.comparison.remaining_changes == 0
    assert session.key_count == session.lesson.baseline_keys
    assert window.repository.completed_count == 1
    assert window.repository.best_edit_stars(profile_id, mode) == 3
    other_mode: EditMode = "free" if mode == "guided" else "guided"
    assert window.repository.best_edit_stars(profile_id, other_mode) == 0
    home = page.result_page.findChild(QPushButton, "editingResultHome")
    assert home is not None
    qtbot.mouseClick(home, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.editing_menu_page
    assert window.editing_button.isChecked()
    assert "완료 1회" in window.editing_menu_page.summary.text()


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp"])
def test_code_source_dialog_shows_full_license_without_changing_attempt(
    window: MainWindow, qtbot: QtBot, profile_id: str
) -> None:
    window.prepare_editing(profile_id)
    page = window.edit_practice
    session = page.session
    assert session is not None and session.lesson.code_excerpt is not None
    excerpt = session.lesson.code_excerpt
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    snapshot = session.engine.snapshot()
    qtbot.mouseClick(page.source_button, Qt.MouseButton.LeftButton)
    dialog = page._source_dialog
    assert dialog is not None and dialog.isVisible()
    assert session.state == SessionState.PAUSED
    assert session.engine.snapshot() == snapshot and session.key_count == 0
    details = "\n".join(widget.text() for widget in dialog.findChildren(QLabel))
    assert excerpt.source.url in details
    assert excerpt.source.revision in details
    assert excerpt.source.sha256 in details
    assert f"{excerpt.start_line}~{excerpt.end_line}행" in details
    license_view = dialog.findChild(QTextBrowser)
    assert license_view is not None
    assert "copyright" in license_view.toPlainText().lower()
    assert len(license_view.toPlainText()) > 500
    dialog.close()
    assert session.state == SessionState.PAUSED
    qtbot.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert session.state == SessionState.READY


@pytest.mark.parametrize(
    "error",
    [
        ValueError("라이선스 SHA-256 불일치"),
        FileNotFoundError("라이선스 파일이 없습니다."),
        PermissionError("라이선스 파일을 읽을 수 없습니다."),
    ],
    ids=["hash", "missing", "unreadable"],
)
def test_code_license_read_failure_preserves_problem(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    error: ValueError | OSError,
) -> None:
    window.prepare_editing("code_python")
    page = window.edit_practice
    session = page.session
    assert session is not None

    def fail(_source_id: str) -> str:
        raise error

    monkeypatch.setattr("vim_key_trainer.ui.edit_practice.read_code_license", fail)
    qtbot.mouseClick(page.source_button, Qt.MouseButton.LeftButton)
    assert page.session is session and session.state == SessionState.READY
    assert session.key_count == 0 and page._source_dialog is None
    assert str(error) in page.feedback.text()


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp"])
@pytest.mark.parametrize("state", ["ready", "running", "paused"])
def test_code_document_selection_replaces_attempt_after_success(
    window: MainWindow, qtbot: QtBot, profile_id: str, state: str
) -> None:
    window.prepare_editing(profile_id)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    previous = page.session
    assert previous is not None and previous.lesson.practice_spec is not None
    if state != "ready":
        qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
        qtbot.keyClicks(page.practice_input, "j")
        if state == "paused":
            page.pause()
    assert page.document_combo.isEnabled()
    page.document_combo.setFocus()
    qtbot.keyClick(page.document_combo, Qt.Key.Key_End)
    current = page.session
    assert current is not None and current is not previous
    assert previous.state == SessionState.ABORTED
    assert previous.key_count == (0 if state == "ready" else 1)
    assert current.state == SessionState.READY and current.mode == "free"
    assert current.key_count == 0 and current.elapsed_seconds == 0
    spec = current.lesson.practice_spec
    excerpt = current.lesson.code_excerpt
    assert spec is not None and excerpt is not None
    assert spec.seed != previous.lesson.practice_spec.seed
    assert 300 <= spec.document_lines <= 500
    assert spec.code_source_id == excerpt.source.id == page.document_combo.currentData()
    assert current.extra_hints == current.step_returns == 0
    if state != "ready":
        assert previous.result in window.repository.results


@pytest.mark.parametrize("profile_id", ["code_python", "code_cpp"])
def test_fixed_code_selection_survives_mode_retry_and_new_problem(
    window: MainWindow, qtbot: QtBot, profile_id: str
) -> None:
    window.prepare_editing(profile_id)
    page = window.edit_practice
    page.document_combo.setCurrentIndex(1)
    fixed = page.session
    assert fixed is not None and fixed.lesson.practice_spec is not None
    source_id = fixed.lesson.practice_spec.code_source_id
    assert source_id
    page.mode_combo.setCurrentIndex(1)
    assert page.session is not None
    assert page.session.lesson.signature == fixed.lesson.signature
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    retried = page.session
    assert retried is not None and retried.attempt_id != fixed.attempt_id
    assert retried.lesson.signature == fixed.lesson.signature
    assert page.document_combo.currentData() == source_id
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert fresh is not None and fresh.lesson.practice_spec is not None
    assert fresh.lesson.code_excerpt is not None
    assert fresh.lesson.practice_spec.seed != fixed.lesson.practice_spec.seed
    assert fresh.lesson.practice_spec.code_source_id == source_id
    assert fresh.lesson.code_excerpt.source.id == source_id
    assert page.document_combo.currentData() == source_id and fresh.mode == "free"
    page.document_combo.setCurrentIndex(0)
    random_session = page.session
    assert (
        random_session is not None and random_session.lesson.practice_spec is not None
    )
    assert random_session.lesson.practice_spec.code_source_id is None
    assert page.document_combo.currentData() == ""
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    assert page.session is not None
    assert page.session.lesson.signature == random_session.lesson.signature
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    assert page.session is not None and page.session.lesson.practice_spec is not None
    assert page.session.lesson.practice_spec.code_source_id is None
    assert page.document_combo.currentData() == ""


def test_document_choices_reset_between_code_general_and_json(
    window: MainWindow,
) -> None:
    page = window.edit_practice
    for profile_id in ("code_python", "code_cpp"):
        window.prepare_editing(profile_id)
        expected = {
            item.source.id
            for item in load_code_sources()
            if item.source.language == get_edit_profile(profile_id).language
        }
        assert {
            page.document_combo.itemData(index)
            for index in range(1, page.document_combo.count())
        } == expected
        page.document_combo.setCurrentIndex(1)
    mission = list_document_missions()[0]
    window.prepare_document_mission(mission.id, seed=41)
    assert page.document_combo.isVisible()
    assert page.document_combo.currentData() == mission.id
    assert page.document_combo.itemText(0) == "무작위 문서"
    assert {
        page.document_combo.itemData(index)
        for index in range(1, page.document_combo.count())
    } == {item.id for item in list_document_missions()}
    window.prepare_editing("code_json")
    assert not page.document_combo.isVisible()
    assert (
        not page.source_button.isVisible() and not page.code_source_summary.isVisible()
    )
    window.prepare_editing("editing_numbers")
    assert not page.document_combo.isVisible()
    assert page.length_combo.isVisible()


@pytest.mark.parametrize("fixed", [False, True])
@pytest.mark.parametrize("error_type", [ValueError, FileNotFoundError])
def test_failed_code_document_selection_restores_selection_and_attempt(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    fixed: bool,
    error_type: type[ValueError] | type[OSError],
) -> None:
    now = [0]

    def create_session(lesson: EditLesson, mode: EditMode) -> EditingSession:
        return EditingSession(lesson, mode, clock_ns=lambda: now[0])

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.EditingSession", create_session
    )
    source_id = next(
        item.source.id
        for item in load_code_sources()
        if item.source.language == "python"
    )
    spec = EditPracticeSpec(
        "code_python", 41, 360, code_source_id=source_id if fixed else None
    )
    window.prepare_editing("code_python", spec)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    previous = page.session
    assert previous is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "j")
    now[0] = 2_000_000_000
    snapshot = previous.engine.snapshot()
    elapsed = previous.elapsed_seconds
    assert previous.state == SessionState.RUNNING and previous.key_count == 1

    def fail(_spec: EditPracticeSpec) -> EditLesson:
        raise error_type("선택한 코드 문서를 열 수 없습니다.")

    monkeypatch.setattr("vim_key_trainer.ui.edit_practice.create_edit_problem", fail)
    page.document_combo.setCurrentIndex(page.document_combo.count() - 1)
    assert page.session is previous and previous.state == SessionState.RUNNING
    assert previous.engine.snapshot() == snapshot
    assert previous.elapsed_seconds == elapsed and previous.key_count == 1
    assert previous.result is None
    assert page.document_combo.currentData() == (source_id if fixed else "")
    assert "코드 문서를 열 수 없습니다" in page.feedback.text()
