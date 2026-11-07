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
    y = int(16 + metrics.lineSpacing() - 4)
    changed_x = int(
        58 + metrics.horizontalAdvance("return ") + metrics.horizontalAdvance("3") / 2
    )
    unchanged_x = int(58 + metrics.horizontalAdvance("ret"))
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
    assert image.pixelColor(58, 25) != image.pixelColor(100, 25)
    assert document.change_spans[0].start == document.change_spans[0].end == 0
