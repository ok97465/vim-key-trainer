"""반투명 가이드는 문서 위에서 진행만 표시하고 입력은 가로채지 않는다."""

# Third party imports
import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditorState
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
