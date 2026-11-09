"""참고 그림의 확대·탐색·저장과 연습 상태 보존을 검증한다."""

from __future__ import annotations

# Standard library imports
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path

# Third party imports
import pytest
from PySide6.QtCore import QPoint, QPointF, QSaveFile, Qt
from PySide6.QtGui import QContextMenuEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QMessageBox
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.ui.main_window import MainWindow
from vim_key_trainer.ui.vim_cheatsheet import VimCheatSheetPage
from vim_key_trainer.ui.widgets import cheatsheet_poster
from vim_key_trainer.ui.widgets.cheatsheet_poster import CheatSheetPoster, PosterViewer


@pytest.fixture
def poster(qtbot: QtBot) -> Iterator[CheatSheetPoster]:
    widget = CheatSheetPoster()
    qtbot.addWidget(widget)
    widget.resize(900, 630)
    widget.show()
    yield widget
    if widget.viewer is not None:
        widget.viewer.close()
    widget.close()


def open_viewer(poster: CheatSheetPoster, qtbot: QtBot) -> PosterViewer:
    qtbot.mouseClick(poster, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: poster.viewer is not None)
    viewer = poster.viewer
    assert viewer is not None
    qtbot.waitUntil(viewer.isVisible)
    return viewer


def test_click_opens_fullscreen_and_escape_allows_reopening(
    poster: CheatSheetPoster, qtbot: QtBot
) -> None:
    first = open_viewer(poster, qtbot)
    assert first.isFullScreen()
    assert first.view.scene() is not None
    assert first.view.sceneRect().width() == 5925
    assert first.view.sceneRect().height() == 4125
    qtbot.keyClick(first, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: poster.viewer is None)
    poster.setFocus()
    qtbot.keyClick(poster, Qt.Key.Key_Space)
    qtbot.waitUntil(lambda: poster.viewer is not None)
    second = poster.viewer
    assert second is not None and second is not first
    qtbot.mouseClick(second.close_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: poster.viewer is None)


def test_zoom_controls_and_mouse_wheel_preserve_native_image(
    poster: CheatSheetPoster, qtbot: QtBot
) -> None:
    viewer = open_viewer(poster, qtbot)
    qtbot.mouseClick(viewer.fit_button, Qt.MouseButton.LeftButton)
    fit_scale = viewer.scale_factor
    assert 0 < fit_scale < 1
    qtbot.mouseClick(viewer.zoom_in_button, Qt.MouseButton.LeftButton)
    assert viewer.scale_factor > fit_scale
    qtbot.mouseClick(viewer.zoom_out_button, Qt.MouseButton.LeftButton)
    assert viewer.scale_factor == pytest.approx(fit_scale)
    qtbot.mouseClick(viewer.actual_size_button, Qt.MouseButton.LeftButton)
    assert viewer.scale_factor == pytest.approx(1)
    viewport = viewer.view.viewport()
    position = QPointF(viewport.rect().center())
    wheel = QWheelEvent(
        position,
        QPointF(viewport.mapToGlobal(position.toPoint())),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, wheel)
    assert viewer.scale_factor > 1
    assert viewer.view.sceneRect().size().width() == 5925
    assert viewer.view.sceneRect().size().height() == 4125
    qtbot.mouseClick(viewer.fit_button, Qt.MouseButton.LeftButton)
    assert viewer.scale_factor == pytest.approx(fit_scale)


def test_zoomed_image_can_be_dragged_to_other_details(
    poster: CheatSheetPoster, qtbot: QtBot
) -> None:
    viewer = open_viewer(poster, qtbot)
    viewer.actual_size()
    horizontal = viewer.view.horizontalScrollBar()
    vertical = viewer.view.verticalScrollBar()
    assert horizontal.maximum() > 0 and vertical.maximum() > 0
    horizontal.setValue(horizontal.maximum() // 2)
    vertical.setValue(vertical.maximum() // 2)
    start = viewer.view.viewport().rect().center()
    before = (horizontal.value(), vertical.value())
    qtbot.mousePress(viewer.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(viewer.view.viewport(), start - QPoint(80, 60), delay=10)
    qtbot.mouseRelease(
        viewer.view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=start - QPoint(80, 60),
    )
    assert (horizontal.value(), vertical.value()) != before


@pytest.mark.parametrize("surface", ["preview", "viewer"])
def test_right_click_save_writes_exact_original_to_chosen_folder(
    poster: CheatSheetPoster,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    surface: str,
) -> None:
    folder = tmp_path / "선택한 폴더"
    folder.mkdir()
    destination = folder / "한글 Vim 참고서"
    monkeypatch.setattr(
        cheatsheet_poster.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "PNG 이미지 (*.png)"),
    )
    target = poster
    if surface == "viewer":
        viewer = open_viewer(poster, qtbot)
        viewer.actual_size()
        viewer.zoom_in()
        target = viewer.view.viewport()
    position = target.rect().center()
    context = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        position,
        target.mapToGlobal(position),
    )
    QApplication.sendEvent(target, context)
    qtbot.waitUntil(lambda: isinstance(QApplication.activePopupWidget(), QMenu))
    menu = QApplication.activePopupWidget()
    assert isinstance(menu, QMenu)
    action = next(action for action in menu.actions() if "저장" in action.text())
    qtbot.mouseClick(
        menu,
        Qt.MouseButton.LeftButton,
        pos=menu.actionGeometry(action).center(),
    )
    expected = (
        files("vim_key_trainer")
        .joinpath("resources", "cheatsheets", "vim-cheatsheet-ko.png")
        .read_bytes()
    )
    assert destination.with_suffix(".png").read_bytes() == expected


def test_cancel_save_leaves_files_unchanged(
    poster: CheatSheetPoster, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sentinel = tmp_path / "existing.png"
    sentinel.write_bytes(b"existing file")
    monkeypatch.setattr(
        cheatsheet_poster.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    poster.save_image()
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"existing file"


def test_failed_commit_preserves_existing_file_and_reports_error(
    poster: CheatSheetPoster, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "existing.png"
    destination.write_bytes(b"existing file")
    warnings: list[tuple[object, ...]] = []

    class UncommittableSaveFile(QSaveFile):
        def commit(self) -> bool:
            self.cancelWriting()
            return False

    monkeypatch.setattr(cheatsheet_poster, "QSaveFile", UncommittableSaveFile)
    monkeypatch.setattr(
        cheatsheet_poster.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "PNG 이미지 (*.png)"),
    )
    monkeypatch.setattr(
        cheatsheet_poster.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    poster.save_image()
    assert destination.read_bytes() == b"existing file"
    assert warnings


def test_sheet_poster_follows_title_with_responsive_width(qtbot: QtBot) -> None:
    page = VimCheatSheetPage()
    qtbot.addWidget(page)
    page.resize(1700, 800)
    page.show()
    title = page.findChild(QLabel, "sheetTitle")
    assert title is not None
    qtbot.waitUntil(lambda: page.poster.width() <= 1200)
    assert page.poster.mapTo(page, QPoint()).y() >= title.mapTo(page, QPoint()).y() + (
        title.height()
    )
    assert page.size().height() == 800
    wide_width = page.poster.width()
    page.resize(1005, 800)
    qtbot.waitUntil(lambda: page.poster.width() < wide_width)
    assert page.poster.width() <= page.scroll_area.viewport().width()
    assert page.poster.height() == pytest.approx(
        page.poster.width() * 4125 / 5925, abs=2
    )
    assert page.scroll_area.verticalScrollBar().maximum() > 0


@pytest.mark.parametrize(
    "decision", [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
)
def test_extension_collision_requires_overwrite_choice(
    poster: CheatSheetPoster,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    decision: QMessageBox.StandardButton,
) -> None:
    chosen = tmp_path / "poster"
    existing = chosen.with_suffix(".png")
    existing.write_bytes(b"existing file")
    questions: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        cheatsheet_poster.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(chosen), "PNG 이미지 (*.png)"),
    )

    def choose(*args: object) -> QMessageBox.StandardButton:
        questions.append(args)
        return decision

    monkeypatch.setattr(cheatsheet_poster.QMessageBox, "question", choose)
    poster.save_image()
    assert questions
    assert not chosen.exists()
    expected = (
        files("vim_key_trainer")
        .joinpath("resources", "cheatsheets", "vim-cheatsheet-ko.png")
        .read_bytes()
        if decision == QMessageBox.StandardButton.Yes
        else b"existing file"
    )
    assert existing.read_bytes() == expected


def test_sheet_opens_at_poster_and_fullscreen_keeps_edit_attempt_paused(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.prepare_editing_lesson(get_edit_lesson("editing_numbers"))
    practice = window.edit_practice
    session = practice.session
    assert session is not None
    ticks = [1_000_000_000]
    monkeypatch.setattr(session, "_clock_ns", lambda: ticks[0])
    qtbot.mouseClick(practice.start_button, Qt.MouseButton.LeftButton)
    token = session.expected_token
    assert token is not None and token.kind == "char"
    qtbot.keyClicks(practice.practice_input, token.value)
    assert session.state == SessionState.RUNNING
    ticks[0] += 2_000_000_000
    qtbot.mouseClick(window.cheatsheet_button, Qt.MouseButton.LeftButton)
    page = window.cheatsheet_page
    qtbot.waitUntil(lambda: page.scroll_area.verticalScrollBar().value() == 0)
    assert page.poster.mapTo(page.scroll_area.viewport(), QPoint()).y() >= 0
    assert session.state == SessionState.PAUSED
    assert session.elapsed_seconds == 2
    original = (session.attempt_id, session.key_count, session.engine.snapshot())
    viewer = open_viewer(page.poster, qtbot)
    qtbot.mouseClick(viewer.actual_size_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(viewer.zoom_in_button, Qt.MouseButton.LeftButton)
    ticks[0] += 60_000_000_000
    qtbot.keyClick(viewer, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: page.poster.viewer is None)
    assert window.stack.currentWidget() is page
    qtbot.mouseClick(page.return_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is practice
    assert session.state == SessionState.PAUSED
    assert session.elapsed_seconds == 2
    assert session.pause_count == 1
    after = (session.attempt_id, session.key_count, session.engine.snapshot())
    assert after == original
    assert window.repository.results == ()
    window.close()
