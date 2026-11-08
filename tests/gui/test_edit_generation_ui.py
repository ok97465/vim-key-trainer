"""긴 문서의 새 예제·재도전·길이 선택과 실제 입력 흐름을 검증한다."""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.editing import EditMode, EditPracticeSpec
from vim_key_trainer.domain.keys import KeyToken
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


def test_catalog_prepares_full_document_with_default_length(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.show_technique_editing()
    start = window.editing_techniques_page.findChild(
        QPushButton, "lesson_editing_numbers"
    )
    assert start is not None
    qtbot.mouseClick(start, Qt.MouseButton.LeftButton)
    page = window.edit_practice
    session = page.session
    assert session is not None
    assert session.lesson.practice_spec is not None
    assert session.lesson.practice_spec.document_lines == 24
    assert len(session.engine.state.lines) == 24
    assert session.lesson.content_version == 8
    assert session.state == SessionState.READY
    assert session.key_count == 0 and session.elapsed_seconds == 0
    assert page.length_combo.currentData() == 24


def test_length_retry_and_new_problem_preserve_the_right_conditions(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    original_spec = EditPracticeSpec("editing_numbers", seed=77)
    window.prepare_editing(original_spec.profile_id, original_spec)
    page = window.edit_practice
    previous = page.session
    assert previous is not None
    page.length_combo.setCurrentIndex(page.length_combo.findData(40))
    session = page.session
    assert session is not None and session.lesson.practice_spec is not None
    spec = session.lesson.practice_spec
    assert previous.state == SessionState.ABORTED
    assert spec.seed == 77 and spec.document_lines == 40
    assert len(session.engine.state.lines) == 40
    assert session.state == SessionState.READY
    page.mode_combo.setCurrentIndex(1)
    session = page.session
    assert session is not None and session.mode == "free"
    signature = session.lesson.signature
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "j")
    assert not page.mode_combo.isEnabled() and not page.length_combo.isEnabled()
    qtbot.mouseClick(page.retry_button, Qt.MouseButton.LeftButton)
    retried = page.session
    assert retried is not None
    assert session.state == SessionState.ABORTED
    assert retried.attempt_id != session.attempt_id
    assert retried.lesson.signature == signature
    assert retried.lesson.practice_spec == spec
    assert retried.mode == "free" and retried.key_count == 0
    qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)
    fresh = page.session
    assert fresh is not None and fresh.lesson.practice_spec is not None
    assert retried.state == SessionState.ABORTED
    assert fresh.lesson.practice_spec.seed != spec.seed
    assert fresh.lesson.practice_spec.document_lines == 40
    assert fresh.lesson.practice_spec.profile_id == spec.profile_id
    assert fresh.lesson.signature != signature
    assert fresh.mode == "free" and fresh.state == SessionState.READY


@pytest.mark.parametrize(
    ("profile_id", "lines", "mode"),
    [
        ("editing_numbers", 12, "guided"),
        ("editing_delete_line", 24, "free"),
        ("editing_delete_word", 40, "guided"),
        ("editing_append", 24, "free"),
        ("editing_compound", 40, "free"),
        ("editing_undo", 12, "guided"),
    ],
)
def test_generated_multi_edit_documents_complete_through_actual_keys(
    window: MainWindow,
    qtbot: QtBot,
    profile_id: str,
    lines: int,
    mode: EditMode,
) -> None:
    spec = EditPracticeSpec(profile_id, seed=23, document_lines=lines)
    window.prepare_editing(profile_id, spec)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(0 if mode == "guided" else 1)
    session = page.session
    assert session is not None
    goal = page.goal_document.editor_state
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    tokens = (
        tuple(key for step in session.lesson.guide for key in step.keys)
        if mode == "guided"
        else session.lesson.baseline
    )
    for token in tokens:
        press(window, qtbot, token)
    assert session.state == SessionState.COMPLETED
    assert session.result is not None
    assert session.result.practice_spec == spec
    assert session.result.key_count == len(tokens)
    assert session.result.delta == 0 and session.result.stars == 3
    assert page.goal_document.editor_state == goal
    assert page.stack.currentWidget() is page.result_page
    assert (
        window.repository.best_edit_stars(
            profile_id, session.lesson.content_version, mode
        )
        == 3
    )
    assert window.repository.best_edit_stars(profile_id, 2, mode) == 0
    assert window.repository.best_edit_stars(profile_id, 1, mode) == 0
    qtbot.mouseClick(page.result_new_button, Qt.MouseButton.LeftButton)
    assert page.session is not None and page.session.lesson.practice_spec is not None
    assert page.session.lesson.practice_spec.seed != spec.seed
    assert page.session.lesson.practice_spec.document_lines == lines
    assert page.session.mode == mode and page.session.key_count == 0


def test_long_document_controls_stay_visible_and_scrolling_does_not_edit(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    window.resize(960, 680)
    window.edit_practice.document_font_spin.setValue(30)
    window.prepare_editing(
        "editing_compound",
        EditPracticeSpec(
            "editing_compound",
            seed=3,
            document_lines=40,
        ),
    )
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    session = page.session
    assert session is not None
    goal = page.goal_document.editor_state
    qtbot.keyClicks(page.practice_input, "G")
    assert session.engine.state.row == 39
    assert page.document_scroll.verticalScrollBar().value() > 0
    assert page.goal_document.editor_state == goal
    assert session.key_count == 1
    for control in (page.pause_button, page.new_problem_button, page.short_button):
        rect = control.rect().translated(
            control.mapTo(window, control.rect().topLeft())
        )
        assert window.rect().contains(rect)
    overlay = page.comparison.guide_overlay
    assert not overlay.isVisible() and not overlay.keys
    assert session.extra_hints == 0
    assert page.document_scroll.viewport().height() < page.practice_input.height()
    assert page.practice_input.hasFocus()


@pytest.mark.parametrize("real_document", [False, True])
@pytest.mark.parametrize("mode", ["guided", "free"])
@pytest.mark.parametrize("started", [False, True])
def test_compact_practice_controls_share_one_row_and_editor_gets_extra_height(
    window: MainWindow,
    qtbot: QtBot,
    real_document: bool,
    mode: EditMode,
    started: bool,
) -> None:
    window.resize(1200, 800)
    if real_document:
        window.prepare_document_mission("mission_flask", seed=7)
    else:
        window.prepare_editing(
            "editing_compound",
            EditPracticeSpec("editing_compound", seed=3, document_lines=40),
        )
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(0 if mode == "guided" else 1)
    if started:
        qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(page.practice_input.hasFocus)
    qtbot.waitUntil(lambda: page.comparison.height() > 0)
    qtbot.wait(1)
    assert window.width() == 1200 and window.height() == 800

    controls = page.practice_page.findChildren(QPushButton)
    assert not any(
        control.accessibleName()
        in {"editOriginal", "editHint", "이전 가이드 단계", "다음 가이드 단계"}
        for control in controls
    )
    assert not any(
        "지원 명령 · 입력 안내" in text.text()
        for text in page.practice_page.findChildren(QLabel)
    )

    def check_single_row() -> None:
        bounds = sorted(
            (
                control.rect().translated(
                    control.mapTo(window, control.rect().topLeft())
                )
                for control in controls
                if control.isVisible()
            ),
            key=lambda rect: rect.left(),
        )
        assert len(bounds) >= 5
        assert all(window.rect().contains(rect) for rect in bounds)
        assert len({rect.center().y() for rect in bounds}) == 1
        assert all(
            left.right() < right.left()
            for left, right in zip(bounds, bounds[1:], strict=False)
        )

    check_single_row()
    editor_height = page.comparison.height()
    window_height = window.height()
    fixed_widgets = [
        page.title,
        page.description,
        page.mission_progress,
        page.mode_combo,
        page.document_font_spin,
        page.action_bar,
        page.feedback,
        *page.metrics.values(),
        *controls,
    ]
    fixed_heights = [widget.height() for widget in fixed_widgets]
    window.resize(1200, 1100)
    qtbot.waitUntil(lambda: page.comparison.height() > editor_height)
    check_single_row()
    assert [widget.height() for widget in fixed_widgets] == fixed_heights
    assert (
        page.comparison.height() - editor_height >= window.height() - window_height - 2
    )
    assert page.comparison.height() > 520
    assert page.comparison.guide_overlay.isVisible() == (mode == "guided")


def test_short_practice_has_seven_repairs_and_returns_to_long_document(
    window: MainWindow,
    qtbot: QtBot,
) -> None:
    spec = EditPracticeSpec("editing_numbers", seed=19, document_lines=40)
    window.prepare_editing(spec.profile_id, spec)
    page = window.edit_practice
    page.mode_combo.setCurrentIndex(1)
    generated = page.session
    assert generated is not None
    qtbot.mouseClick(page.short_button, Qt.MouseButton.LeftButton)
    intro = page.session
    assert intro is not None
    assert generated.state == SessionState.ABORTED
    assert intro.lesson.practice_spec == EditPracticeSpec(
        spec.profile_id, spec.seed, 12
    )
    assert intro.lesson.content_version == 8
    assert len(intro.lesson.initial.lines) == 12
    assert page.comparison.remaining_changes >= 7
    assert intro.mode == "free" and page.length_combo.isVisible()
    qtbot.mouseClick(page.short_button, Qt.MouseButton.LeftButton)
    returned = page.session
    assert returned is not None and returned.lesson.practice_spec == spec
    assert returned.lesson.signature == generated.lesson.signature
    assert returned.mode == "free" and returned.state == SessionState.READY
    assert returned.attempt_id != generated.attempt_id
    assert returned.key_count == 0 and page.length_combo.currentData() == 40


def test_invalid_short_problem_reports_error_without_replacing_active_problem(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window.prepare_editing("editing_numbers", EditPracticeSpec("editing_numbers", 91))
    page = window.edit_practice
    session = page.session
    assert session is not None
    snapshot = session.engine.snapshot()

    def unavailable(_spec: EditPracticeSpec) -> None:
        raise ValueError("과제 검증에 실패했습니다.")

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.create_edit_problem", unavailable
    )
    qtbot.mouseClick(page.short_button, Qt.MouseButton.LeftButton)
    assert page.session is session
    assert session.engine.snapshot() == snapshot
    assert session.key_count == 0
    assert "과제 검증" in page.feedback.text()


@pytest.mark.parametrize("action", ["length", "new_problem"])
def test_generation_failure_keeps_problem_and_options(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    spec = EditPracticeSpec("editing_numbers", seed=91)
    window.prepare_editing(spec.profile_id, spec)
    page = window.edit_practice
    session = page.session
    assert session is not None
    snapshot = session.engine.snapshot()

    def unavailable(_spec: EditPracticeSpec) -> None:
        raise ValueError("과제 검증에 실패했습니다.")

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.create_edit_problem", unavailable
    )
    if action == "length":
        page.length_combo.setCurrentIndex(page.length_combo.findData(40))
    else:
        qtbot.mouseClick(page.new_problem_button, Qt.MouseButton.LeftButton)

    assert page.session is session
    assert session.state == SessionState.READY
    assert session.engine.snapshot() == snapshot
    assert session.key_count == 0
    assert page.length_combo.currentData() == spec.document_lines
    assert "과제 검증" in page.feedback.text()


def test_generation_failure_on_result_page_keeps_visible_result(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = EditPracticeSpec("editing_numbers", seed=91, document_lines=12)
    window.prepare_editing(spec.profile_id, spec)
    page = window.edit_practice
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    for token in session.lesson.baseline:
        press(window, qtbot, token)
    assert session.state == SessionState.COMPLETED
    result = page.last_result
    page.result_note.hide()

    def unavailable(_spec: EditPracticeSpec) -> None:
        raise ValueError("과제 검증에 실패했습니다.")

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.create_edit_problem", unavailable
    )
    qtbot.mouseClick(page.result_new_button, Qt.MouseButton.LeftButton)

    assert page.session is session
    assert page.last_result is result
    assert page.stack.currentWidget() is page.result_page
    assert window.repository.completed_count == 1
    assert "과제 검증" in page.result_note.text()
    assert page.result_note.isVisible()


@pytest.mark.parametrize("real_document", [False, True])
@pytest.mark.parametrize("navigate", [False, True])
def test_menu_generation_failure_reports_error_and_preserves_current_attempt(
    window: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    real_document: bool,
    navigate: bool,
) -> None:
    window.prepare_editing("editing_numbers", EditPracticeSpec("editing_numbers", 91))
    page = window.edit_practice
    session = page.session
    assert session is not None
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.keyClicks(page.practice_input, "j")
    snapshot = session.engine.snapshot()
    category = window._category

    def unavailable(_spec: object) -> None:
        raise ValueError("과제 검증에 실패했습니다.")

    factory = (
        "create_random_document_problem" if real_document else "create_edit_problem"
    )
    with monkeypatch.context() as patch:
        patch.setattr(f"vim_key_trainer.ui.main_window.{factory}", unavailable)
        if real_document:
            window.prepare_document_mission("mission_flask", seed=8)
        else:
            window.prepare_editing("editing_numbers")

    assert page.session is session
    assert session.state == SessionState.RUNNING
    assert session.engine.snapshot() == snapshot
    assert session.key_count == 1
    assert window.stack.currentWidget() is page
    assert window._category == category
    assert "과제 검증" in window.statusBar().currentMessage()
    assert window.statusBar().isVisible()
    if navigate:
        window.show_editing()
        assert not window.statusBar().currentMessage()
        assert not window.statusBar().isVisible()
    window.prepare_editing("editing_numbers", EditPracticeSpec("editing_numbers", 91))
    assert session.state == SessionState.ABORTED
    assert page.session is not session
    assert not window.statusBar().currentMessage()
    assert not window.statusBar().isVisible()
