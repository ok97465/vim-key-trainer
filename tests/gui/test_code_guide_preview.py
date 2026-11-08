"""이동 전 목표 수정 위치와 복사 중의 목표 예고를 실제 Qt 화면에서 검증한다."""

from __future__ import annotations

# Standard library imports
from collections.abc import Iterator

# Third party imports
import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import characters
from vim_key_trainer.domain.editing import (
    EditLesson,
    EditMode,
    EditPracticeSpec,
    expected_states_match,
)
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison


@pytest.fixture
def window(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:
    def create_session(lesson: EditLesson, mode: EditMode) -> EditingSession:
        return EditingSession(lesson, mode, clock_ns=lambda: 0)

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.EditingSession", create_session
    )
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    widget.activateWindow()
    qtbot.waitUntil(widget.isActiveWindow)
    yield widget
    widget.close()


def _code_lesson(
    initial: tuple[str, ...], goal: tuple[str, ...], commands: tuple[str, ...]
) -> EditLesson:
    state = EditorState(initial)
    builder = GuideBuilder(state, SUPPORTED_COMMANDS)
    for command in commands:
        builder.record(characters(command), "수정 위치로 이동하고 코드를 복원합니다.")
    assert builder.engine.state.lines == goal
    baseline = tuple(key for step in builder.steps for key in step.keys)
    return EditLesson(
        schema_version=1,
        content_version=1,
        id="code_cpp",
        title="코드 목표 예고",
        description="이동 전에 이번 수정의 목표를 확인합니다.",
        initial=state,
        goal_lines=goal,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=tuple(builder.steps),
        baseline_version=1,
        baseline=baseline,
        baseline_keys=len(baseline),
        practice_spec=EditPracticeSpec("code_cpp", 0, len(initial)),
        generator_version=1,
    )


def _goal_character_visible(comparison: EditComparison, row: int, column: int) -> bool:
    document = comparison.goal_document
    viewport = comparison.goal_scroll.viewport()
    metrics = document.document_metrics
    line = document.editor_state.lines[row]
    character = QRectF(
        58 + metrics.horizontalAdvance(line[:column]),
        16 + row * metrics.lineSpacing(),
        metrics.horizontalAdvance(line[column : column + 1] or " "),
        metrics.lineSpacing(),
    )
    visible_character = character.translated(document.mapTo(viewport, QPoint()))
    return viewport.rect().contains(visible_character.toAlignedRect())


def test_far_target_in_long_line_is_visible_before_navigation_and_replays(
    window: MainWindow, qtbot: QtBot
) -> None:
    row = 280
    prefix = "int value = " + "padding_" * 30
    column = len(prefix)
    initial = [f"int keep_{index} = {index};" for index in range(400)]
    initial[row] = prefix + "1;"
    goal = initial.copy()
    goal[row] = prefix + "2;"
    lesson = _code_lesson(
        tuple(initial), tuple(goal), (f"{row + 1}G", f"{column + 1}|", "r2")
    )
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    session = page.session
    assert session is not None
    snapshot = session.engine.snapshot()
    qtbot.waitUntil(lambda: _goal_character_visible(page.comparison, row, column))
    assert page.comparison.goal_heading.text() == f"목표 문서 · 이번 수정 {row + 1}행"
    assert page.comparison.goal_scroll.verticalScrollBar().value() > 0
    assert page.comparison.goal_scroll.horizontalScrollBar().value() > 0
    assert session.engine.snapshot() == snapshot
    assert (session.engine.state.row, session.engine.state.column) == (0, 0)
    assert session.key_count == 0 and session.elapsed_seconds == 0
    assert page.document_scroll.verticalScrollBar().value() == 0
    assert page.document_scroll.horizontalScrollBar().value() == 0

    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    for step in lesson.guide:
        for key in step.keys:
            qtbot.keyClicks(page.practice_input, key.value)
        assert expected_states_match(step.expected, session.engine.state)
    assert session.state == SessionState.COMPLETED
    assert session.engine.state.lines == tuple(goal)
    assert session.key_count == lesson.baseline_keys


def test_goal_preview_survives_temporary_last_line_deletion_during_copy(
    window: MainWindow, qtbot: QtBot
) -> None:
    goal = [f"int keep_{index} = {index};" for index in range(400)]
    goal[-1] = goal[0]
    initial = goal.copy()
    initial[-1] = "obsolete_line"
    lesson = _code_lesson(tuple(initial), tuple(goal), ('1G"ayy400Gdd"ap',))
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    session = page.session
    assert session is not None
    qtbot.waitUntil(lambda: _goal_character_visible(page.comparison, 399, 0))
    assert session.key_count == 0
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    deleted_last_line = False
    for key in lesson.baseline:
        qtbot.keyClicks(page.practice_input, key.value)
        if len(session.engine.state.lines) == 399:
            deleted_last_line = True
            qtbot.waitUntil(lambda: _goal_character_visible(page.comparison, 399, 0))
            assert page.comparison.goal_heading.text() == "목표 문서 · 이번 수정 400행"
    assert deleted_last_line
    assert session.state == SessionState.COMPLETED
    assert session.engine.state.lines == tuple(goal)
    assert session.key_count == lesson.baseline_keys
