"""구문 문자색과 수정 배경이 실제 Qt 화면에 함께 그려지는지 확인한다."""

# Third party imports
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.engine import EditorState
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison


def test_target_repair_has_painted_background_under_syntax_text(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(850, 300)
    comparison.set_language("python")
    comparison.show_documents(EditorState(("return 12",)), EditorState(("return 34",)))
    comparison.show()
    qtbot.waitExposed(comparison)
    document = comparison.goal_document
    metrics = document.document_metrics
    image = document.grab().toImage()
    scale = image.devicePixelRatio()
    y = round((16 + metrics.lineSpacing() - 4) * scale)
    changed_x = round(
        (58 + metrics.horizontalAdvance("return ") + metrics.horizontalAdvance("3") / 2)
        * scale
    )
    unchanged_x = round((58 + metrics.horizontalAdvance("ret")) * scale)
    assert image.pixelColor(changed_x, y) != image.pixelColor(unchanged_x, y)
    assert document.syntax_spans and document.change_spans
    assert document.editor_state.lines == ("return 34",)


def test_empty_target_anchor_is_painted_for_line_deletion(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(850, 300)
    comparison.show_documents(EditorState(("remove",)), EditorState(("",)))
    comparison.show()
    qtbot.waitExposed(comparison)
    document = comparison.goal_document
    image = document.grab().toImage()
    scale = image.devicePixelRatio()
    assert image.pixelColor(round(58 * scale), round(25 * scale)) != image.pixelColor(
        round(100 * scale), round(25 * scale)
    )
    assert document.change_spans[0].start == document.change_spans[0].end == 0


def test_json_syntax_colors_remain_while_repairs_update(qtbot: QtBot) -> None:
    comparison = EditComparison()
    qtbot.addWidget(comparison)
    comparison.resize(850, 300)
    comparison.set_language("json")
    comparison.set_font_size(18)
    goal = EditorState(('{"name": "ready", "enabled": true}',))
    comparison.show_documents(
        EditorState(('{"name": "pending", "enabled": false}',)), goal
    )
    comparison.show()
    qtbot.waitExposed(comparison)
    document = comparison.goal_document
    image = document.grab().toImage()
    scale = image.devicePixelRatio()
    metrics = document.document_metrics
    colors = {
        image.pixelColor(x, y).name()
        for y in range(round(16 * scale), round((16 + metrics.lineSpacing()) * scale))
        for x in range(round(58 * scale), min(image.width(), round(800 * scale)))
    }
    assert {"#86c9e8", "#b9de91", "#cda9ef"} <= colors
    assert document.change_spans
    comparison.show_current(goal)
    assert comparison.practice_input.syntax_spans
    assert not document.change_spans
    assert not comparison.practice_input.change_spans
