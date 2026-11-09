"""현재 입력 가이드와 다음 수정 위치 예고의 가시성을 검증한다."""

from __future__ import annotations

# Standard library imports
from itertools import pairwise

# Third party imports
import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import characters
from vim_key_trainer.domain.editing import (
    EditLesson,
    EditMode,
    EditPracticeSpec,
    expected_states_match,
)
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison


def make_comparison(qtbot: QtBot) -> EditComparison:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(840, 300)
    state = EditorState(tuple(f"line {index}" for index in range(80)))
    comparison.show_documents(state, state)
    comparison.show()
    qtbot.waitExposed(comparison)
    return comparison


def cursor_clears_guide(comparison: EditComparison) -> bool:
    document = comparison.practice_input
    origin = document.mapTo(comparison.current_scroll.viewport(), QPoint())
    cursor = document.cursor_rect.translated(origin)
    return (
        cursor.top() >= 0
        and cursor.bottom() <= comparison.guide_overlay.geometry().top() - 8
    )


@pytest.mark.parametrize("follow_viewport", [False, True])
def test_final_line_scrolls_above_guide_without_changing_documents(
    qtbot: QtBot, follow_viewport: bool
) -> None:
    comparison = make_comparison(qtbot)
    goal = comparison.goal_document.editor_state
    comparison.show_guide(
        (KeyToken("char", "G"),), 0, description="마지막 줄로 이동", progress="1/2 단계"
    )
    last_line = EditorState(goal.lines, row=len(goal.lines) - 1, viewport_top=70)
    comparison.show_current(last_line, follow_viewport=follow_viewport)

    qtbot.waitUntil(lambda: cursor_clears_guide(comparison))
    assert comparison.practice_input.editor_state is last_line
    assert comparison.goal_document.editor_state is goal


def test_appearing_and_resumed_guide_reveals_existing_final_line(qtbot: QtBot) -> None:
    comparison = make_comparison(qtbot)
    state = EditorState(comparison.practice_input.editor_state.lines, row=79)
    comparison.show_current(state)
    comparison.show_guide(
        (KeyToken("char", "x"),), 0, description="마지막 글자 삭제", progress="2/2 단계"
    )
    qtbot.waitUntil(lambda: cursor_clears_guide(comparison))

    comparison.set_paused(True)
    comparison.current_scroll.verticalScrollBar().setValue(0)
    comparison.set_paused(False)
    qtbot.waitUntil(lambda: cursor_clears_guide(comparison))
    assert comparison.guide_overlay.isVisible()
    assert comparison.practice_input.editor_state is state


def test_final_line_keeps_guide_clearance_after_font_and_viewport_changes(
    qtbot: QtBot,
) -> None:
    comparison = make_comparison(qtbot)
    state = EditorState(comparison.practice_input.editor_state.lines, row=79)
    goal = comparison.goal_document.editor_state
    comparison.show_guide(
        (KeyToken("char", "x"),), 0, description="마지막 글자 삭제", progress="2/2 단계"
    )
    comparison.show_current(state)
    comparison.set_font_size(28)
    qtbot.waitUntil(lambda: cursor_clears_guide(comparison))

    comparison.resize(840, 180)
    qtbot.waitUntil(lambda: cursor_clears_guide(comparison))
    assert comparison.practice_input.editor_state is state
    assert comparison.goal_document.editor_state is goal


def test_accepted_keys_fade_without_spacing_or_changing_next_token(
    qtbot: QtBot,
) -> None:
    comparison = make_comparison(qtbot)
    keys = tuple(KeyToken("char", value) for value in "11111")
    comparison.show_guide(keys, 1, description="단어 변경", progress="1/3 단계")
    overlay = comparison.guide_overlay
    image = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    overlay.render(image)

    def brightest(box: QRectF) -> int:
        return max(
            image.pixelColor(x, y).red()
            for x in range(int(box.left()), int(box.right()))
            for y in range(int(box.top()), int(box.bottom()))
        )

    # Identical glyphs make painted brightness comparable without font assumptions.
    assert brightest(overlay.token_rect(0)) < brightest(overlay.token_rect(2)) / 2
    assert overlay.token_rect(0).right() == overlay.token_rect(1).left()
    assert "11111" in overlay.accessibleDescription()
    assert "1/5키 완료" in overlay.accessibleDescription()
    comparison.show_guide(keys, 2, description="단어 변경", progress="1/3 단계")
    assert overlay.completed == 2
    assert overlay.token_rect(1).right() == overlay.token_rect(2).left()


def test_long_guide_keeps_entire_next_special_key_visible(qtbot: QtBot) -> None:
    comparison = make_comparison(qtbot)
    keys = (KeyToken("char", "x"),) * 120 + (KeyToken("special", "backspace"),)
    comparison.show_guide(keys, 120, description="삽입 내용 수정", progress="2/3 단계")
    overlay = comparison.guide_overlay
    assert overlay.rect().contains(overlay.token_rect(120).toAlignedRect())
    assert "<Backspace>" in overlay.accessibleDescription()
    comparison.resize(320, 220)
    qtbot.waitUntil(lambda: overlay.width() < 160)
    assert overlay.rect().contains(overlay.token_rect(120).toAlignedRect())


def test_long_guide_previews_upcoming_keys_and_moves_in_chunks(qtbot: QtBot) -> None:
    comparison = make_comparison(qtbot)
    keys = (KeyToken("char", "x"),) * 160
    overlay = comparison.guide_overlay
    positions: list[float] = []
    for completed in range(70):
        comparison.show_guide(
            keys, completed, description="긴 문자열 삽입", progress="1/2 단계"
        )
        command_rect, _ = overlay._content_rects()
        # The real paint clip must fit several upcoming keys, not only the next key.
        for index in range(completed, completed + 3):
            assert command_rect.contains(overlay.token_rect(index))
        positions.append(overlay.token_rect(0).left())

    token_width = overlay.token_rect(0).width()
    shifts = [
        previous - current
        for previous, current in pairwise(positions)
        if current < previous
    ]
    assert shifts and min(shifts) > 2 * token_width
    assert any(previous == current for previous, current in pairwise(positions[20:]))


def test_long_guide_repositions_after_return_resize_and_new_step(qtbot: QtBot) -> None:
    comparison = make_comparison(qtbot)
    keys = (KeyToken("char", "x"),) * 160
    comparison.show_guide(keys, 0, description="긴 문자열 삽입", progress="1/2 단계")
    overlay = comparison.guide_overlay
    initial = overlay.token_rect(0)

    comparison.show_guide(keys, 80, description="긴 문자열 삽입", progress="1/2 단계")
    assert overlay.token_rect(0).left() < initial.left()
    comparison.show_guide(keys, 0, description="긴 문자열 삽입", progress="1/2 단계")
    assert overlay.token_rect(0) == initial

    comparison.show_guide(keys, 80, description="긴 문자열 삽입", progress="1/2 단계")
    comparison.resize(640, 300)
    qtbot.waitUntil(lambda: overlay.width() < 320)
    command_rect, _ = overlay._content_rects()
    for index in range(80, 83):
        assert command_rect.contains(overlay.token_rect(index))

    comparison.clear_guide()
    new_keys = (KeyToken("char", "d"),) * 2
    comparison.show_guide(new_keys, 0, description="줄 삭제", progress="2/2 단계")
    command_rect, _ = overlay._content_rects()
    assert command_rect.contains(overlay.token_rect(0))
    assert command_rect.contains(overlay.token_rect(1))


def test_guide_is_pinned_to_viewport_and_pause_does_not_destroy_progress(
    qtbot: QtBot,
) -> None:
    comparison = make_comparison(qtbot)
    comparison.show_guide(
        (KeyToken("char", "d"),) * 2,
        1,
        description="현재 줄 삭제",
        progress="3/4 단계",
    )
    overlay = comparison.guide_overlay
    geometry = overlay.geometry()
    document_size = comparison.practice_input.size()
    comparison.current_scroll.verticalScrollBar().setValue(400)
    assert overlay.geometry() == geometry
    assert comparison.practice_input.size() == document_size
    comparison.resize(1000, 420)
    qtbot.waitUntil(lambda: overlay.geometry() != geometry)
    assert overlay.geometry().bottom() < comparison.current_scroll.viewport().height()
    assert (
        overlay.geometry().bottom() > comparison.current_scroll.viewport().height() - 20
    )
    comparison.set_paused(True)
    assert not overlay.isVisible()
    comparison.set_paused(False)
    assert overlay.isVisible() and overlay.completed == 1
    comparison.clear_guide()
    comparison.set_paused(True)
    comparison.set_paused(False)
    assert not overlay.isVisible()


def test_guide_click_reaches_document_and_key_is_delivered_once(qtbot: QtBot) -> None:
    comparison = make_comparison(qtbot)
    comparison.show_guide(
        (KeyToken("char", "d"),) * 2,
        0,
        description="현재 줄 삭제",
        progress="1/2 단계",
    )
    comparison.activateWindow()
    overlay = comparison.guide_overlay
    hit = QApplication.widgetAt(overlay.mapToGlobal(overlay.rect().center()))
    assert hit is comparison.practice_input
    state = comparison.practice_input.editor_state
    events: list[NormalizedKey] = []
    comparison.practice_input.key_received.connect(events.append)
    qtbot.mouseClick(
        comparison.practice_input,
        Qt.MouseButton.LeftButton,
        pos=comparison.practice_input.mapFromGlobal(
            overlay.mapToGlobal(overlay.rect().center())
        ),
    )
    qtbot.waitUntil(comparison.practice_input.hasFocus)
    qtbot.keyClicks(comparison.practice_input, "d")
    assert len(events) == 1 and events[0].token == KeyToken("char", "d")
    assert comparison.practice_input.editor_state is state


@pytest.fixture
def preview_window(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    def create_session(
        lesson: EditLesson, mode: EditMode, *, challenge: ChallengeOptions
    ) -> EditingSession:
        return EditingSession(lesson, mode, clock_ns=lambda: 0, challenge=challenge)

    monkeypatch.setattr(
        "vim_key_trainer.ui.edit_practice.EditingSession", create_session
    )
    return window


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
    preview_window: MainWindow, qtbot: QtBot
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
    preview_window.prepare_editing_lesson(lesson)
    page = preview_window.edit_practice
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
        if session.state != SessionState.COMPLETED and session.engine.state.row == row:
            current_document = page.comparison.practice_input
            goal_document = page.comparison.goal_document
            current_y = (
                current_document.mapTo(
                    page.comparison.current_scroll.viewport(), QPoint()
                ).y()
                + 16
                + row * current_document.document_metrics.lineSpacing()
            )
            goal_y = (
                goal_document.mapTo(
                    page.comparison.goal_scroll.viewport(), QPoint()
                ).y()
                + 16
                + row * goal_document.document_metrics.lineSpacing()
            )
            assert abs(current_y - goal_y) <= 1
    assert session.state == SessionState.COMPLETED
    assert session.engine.state.lines == tuple(goal)
    assert session.key_count == lesson.baseline_keys


def test_goal_preview_survives_temporary_last_line_deletion_during_copy(
    preview_window: MainWindow, qtbot: QtBot
) -> None:
    goal = [f"int keep_{index} = {index};" for index in range(400)]
    goal[-1] = goal[0]
    initial = goal.copy()
    initial[-1] = "obsolete_line"
    lesson = _code_lesson(tuple(initial), tuple(goal), ('1G"ayy400Gdd"ap',))
    preview_window.prepare_editing_lesson(lesson)
    page = preview_window.edit_practice
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
