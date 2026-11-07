"""참조의 검색·범주 조합과 글자 확대 시 읽기 영역을 검증한다."""

# Third party imports
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.ui.vim_cheatsheet import VimCheatSheetPage


@pytest.fixture
def sheet(qtbot: QtBot) -> VimCheatSheetPage:
    page = VimCheatSheetPage()
    qtbot.addWidget(page)
    page.resize(1005, 800)
    page.show()
    qtbot.waitUntil(lambda: page._column_count == 2)
    return page


def visible_keys(sheet: VimCheatSheetPage) -> set[str]:
    return {
        key.text() for card in sheet.cards for key in card.key_labels if key.isVisible()
    }


def test_search_combines_with_category_and_recovers_from_no_matches(
    sheet: VimCheatSheetPage, qtbot: QtBot
) -> None:
    sheet.focus_search()
    qtbot.keyClicks(sheet.search, ":write")
    assert visible_keys(sheet) == {":write / :w", ":write path"}
    sheet.category.setCurrentIndex(sheet.category.findData("motions"))
    assert not visible_keys(sheet)
    assert sheet.empty_label.isVisible()
    sheet.search.clear()
    assert "h / j / k / l" in visible_keys(sheet)
    assert ":write path" not in visible_keys(sheet)
    assert not sheet.empty_label.isVisible()
    sheet.category.setCurrentIndex(0)
    assert ":write path" in visible_keys(sheet)
    assert sheet.intro.isVisible()


def test_korean_search_and_special_keys_are_plain_selectable_text(
    sheet: VimCheatSheetPage,
) -> None:
    sheet.search.setText("괄호")
    assert "%" in visible_keys(sheet)
    sheet.search.setText("<Esc>")
    assert "<Esc>" in visible_keys(sheet)
    for card in sheet.cards:
        for key in card.key_labels:
            assert key.textFormat() == Qt.TextFormat.PlainText
            assert key.textInteractionFlags() & (
                Qt.TextInteractionFlag.TextSelectableByMouse
            )


def test_entry_shows_poster_and_search_stays_visible_while_filtering(
    sheet: VimCheatSheetPage, qtbot: QtBot
) -> None:
    sheet.focus_entry()
    assert sheet.scroll_area.verticalScrollBar().value() == 0
    assert sheet.poster.mapTo(sheet.scroll_area.viewport(), QPoint()).y() == 0
    sheet.focus_search()
    qtbot.waitUntil(lambda: sheet.scroll_area.verticalScrollBar().value() > 0)
    qtbot.keyClicks(sheet.search, ":write")
    assert sheet.scroll_area.verticalScrollBar().value() > 0
    assert (
        sheet.scroll_area.viewport()
        .rect()
        .intersects(
            sheet.search.rect().translated(
                sheet.search.mapTo(sheet.scroll_area.viewport(), QPoint())
            )
        )
    )
    assert visible_keys(sheet) == {":write / :w", ":write path"}
    sheet.focus_entry()
    assert sheet.scroll_area.verticalScrollBar().value() == 0


@pytest.mark.parametrize("width,size,columns", [(1005, 20, 1), (1405, 20, 2)])
def test_zoom_reflows_without_clipping_commands_or_descriptions(
    sheet: VimCheatSheetPage, qtbot: QtBot, width: int, size: int, columns: int
) -> None:
    sheet.resize(width, 800)
    sheet.font_size.setValue(size)
    qtbot.waitUntil(lambda: sheet._column_count == columns)
    # Let nested Qt layouts apply their height-for-width calculations.
    qtbot.waitUntil(
        lambda: all(
            widget.heightForWidth(widget.width()) <= widget.height()
            for card in sheet.cards
            for widget in card.findChildren(QLabel)
        )
    )
    assert sheet.content.width() <= sheet.scroll_area.viewport().width()
    assert all(
        card.geometry().right() < card.parentWidget().width() for card in sheet.cards
    )
