"""한글 Vim 포스터 미리보기·전체 화면 확대·원본 PNG 저장."""

# Standard library imports
from collections.abc import Callable
from functools import cache
from importlib.resources import files
from pathlib import Path

# Third party imports
from PySide6.QtCore import (
    QIODevice,
    QPoint,
    QRectF,
    QSaveFile,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFocusEvent,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.ui.components import button, label

_FILE_NAME = "vim-cheatsheet-ko.png"
_PREVIEW_WIDTH = 1200
_MIN_SCALE = 0.02
_MAX_SCALE = 4.0
_VIEWER_STYLESHEET = """
QDialog#posterViewer { background: #10151d; }
QFrame#posterViewerToolbar { background: #19222e; border-bottom: 1px solid #344255; }
QGraphicsView#posterCanvas { background: #0b1016; border: none; }
QLabel#posterViewerTitle { color: #d5efb8; font-size: 18px; font-weight: bold; }
QLabel#posterZoom { color: #c3ef85; font-weight: bold; min-width: 54px; }
QLabel#posterHelp { color: #a9b7c9; padding: 7px 16px; }
"""


@cache
def _load_poster() -> tuple[bytes, QPixmap]:
    """같은 원본을 한 번만 디코딩하고 미리보기·확대 창에서 공유한다."""
    data = (
        files("vim_key_trainer")
        .joinpath("resources", "cheatsheets", _FILE_NAME)
        .read_bytes()
    )
    pixmap = QPixmap()
    if not pixmap.loadFromData(data, "PNG"):
        raise ValueError("Vim CheatSheet 이미지를 읽을 수 없습니다.")
    return data, pixmap


def _save_png(image_bytes: bytes, parent: QWidget) -> None:
    filename, _ = QFileDialog.getSaveFileName(
        parent,
        "CheatSheet PNG 저장",
        _FILE_NAME,
        "PNG 이미지 (*.png)",
    )
    if not filename:
        return
    destination = Path(filename)
    if not destination.suffix:
        destination = destination.with_suffix(".png")
        # 대화상자가 확인한 경로와 확장자를 보완한 실제 저장 경로가 다를 수 있다.
        if (
            destination.exists()
            and QMessageBox.question(
                parent,
                "파일 바꾸기",
                f"'{destination.name}' 파일이 이미 있습니다. 바꾸시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
    output = QSaveFile(str(destination))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        QMessageBox.warning(
            parent,
            "이미지 저장 실패",
            f"이미지를 저장하지 못했습니다.\n{output.errorString()}",
        )
        return
    if output.write(image_bytes) != len(image_bytes):
        error = output.errorString()
        output.cancelWriting()
    elif output.commit():
        return
    else:
        error = output.errorString()
    QMessageBox.warning(
        parent,
        "이미지 저장 실패",
        f"이미지를 저장하지 못했습니다.\n{error}",
    )


def _save_menu(parent: QWidget, position: QPoint, save: Callable[[], None]) -> QMenu:
    # popup은 별도 이벤트 루프를 만들지 않아 포커스·창 닫기를 방해하지 않는다.
    menu = QMenu(parent)
    menu.setObjectName("cheatSheetSaveMenu")
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    action = menu.addAction("PNG 이미지 저장…")
    action.setObjectName("saveCheatSheetPng")
    action.triggered.connect(save)
    menu.popup(position)
    return menu


class _PosterGraphicsView(QGraphicsView):
    zoom_requested = Signal(float, bool)
    save_requested = Signal()
    viewport_resized = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._context_menu: QMenu | None = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if not delta:
            delta = event.pixelDelta().y()
        if delta:
            # 매우 큰 한 번의 휠 값도 유한한 확대율로 제한한다.
            steps = max(-8.0, min(8.0, delta / 120))
            self.zoom_requested.emit(1.25**steps, True)
        event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._context_menu = _save_menu(
            self, event.globalPos(), self.save_requested.emit
        )
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.viewport_resized.emit()


class PosterViewer(QDialog):
    """포스터 원본을 마우스 위치 기준으로 확대하고 드래그해 탐색한다."""

    def __init__(
        self, pixmap: QPixmap, image_bytes: bytes, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.image_bytes = image_bytes
        self._fit_mode = True
        self.setObjectName("posterViewer")
        self.setWindowTitle("Vim CheatSheet · 이미지 확대")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(_VIEWER_STYLESHEET)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("posterViewerToolbar")
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(18, 12, 18, 12)
        controls.setSpacing(10)
        controls.addWidget(label("Vim CheatSheet", "posterViewerTitle"))
        controls.addStretch()
        self.zoom_out_button = button("−", "posterZoomOut", enter_activates=True)
        self.zoom_out_button.setAccessibleName("CheatSheet 이미지 축소")
        self.zoom_out_button.clicked.connect(self.zoom_out)
        controls.addWidget(self.zoom_out_button)
        self.zoom_label = label("100%", "posterZoom")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setAccessibleName("CheatSheet 이미지 확대율")
        controls.addWidget(self.zoom_label)
        self.zoom_in_button = button("+", "posterZoomIn", enter_activates=True)
        self.zoom_in_button.setAccessibleName("CheatSheet 이미지 확대")
        self.zoom_in_button.clicked.connect(self.zoom_in)
        controls.addWidget(self.zoom_in_button)
        self.fit_button = button("화면 맞춤", "posterFit", enter_activates=True)
        self.fit_button.clicked.connect(self.fit_to_window)
        controls.addWidget(self.fit_button)
        self.actual_size_button = button(
            "100%", "posterActualSize", enter_activates=True
        )
        self.actual_size_button.clicked.connect(self.actual_size)
        controls.addWidget(self.actual_size_button)
        self.close_button = button("닫기 · Esc", "posterClose", enter_activates=True)
        self.close_button.clicked.connect(self.reject)
        controls.addWidget(self.close_button)
        outer.addWidget(toolbar)
        self.view = _PosterGraphicsView()
        self.view.setObjectName("posterCanvas")
        self.view.setAccessibleName("확대 가능한 한글 Vim CheatSheet 이미지")
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.view.setMouseTracking(True)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scene = QGraphicsScene(self)
        image_item = self.scene.addPixmap(pixmap)
        image_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene.setSceneRect(QRectF(pixmap.rect()))
        self.view.setScene(self.scene)
        self.view.zoom_requested.connect(self._zoom_by)
        self.view.save_requested.connect(self.save_image)
        self.view.viewport_resized.connect(self._viewport_resized)
        outer.addWidget(self.view, 1)
        outer.addWidget(
            label(
                "휠: 확대·축소  ·  드래그: 이동  ·  우클릭: PNG 저장  ·  Esc: 닫기",
                "posterHelp",
                wrap=True,
            )
        )

    @property
    def scale_factor(self) -> float:
        return self.view.transform().m11()

    def _viewport_resized(self) -> None:
        if self._fit_mode:
            QTimer.singleShot(0, self._fit_if_visible)

    def _fit_if_visible(self) -> None:
        if self.isVisible() and self._fit_mode:
            self.fit_to_window()

    def _refresh_zoom(self) -> None:
        self.zoom_label.setText(f"{self.scale_factor * 100:.0f}%")
        self.zoom_out_button.setEnabled(self.scale_factor > _MIN_SCALE + 1e-6)
        self.zoom_in_button.setEnabled(self.scale_factor < _MAX_SCALE - 1e-6)

    def _zoom_by(self, factor: float, under_mouse: bool = False) -> None:
        self._fit_mode = False
        self.view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
            if under_mouse
            else QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        target = max(_MIN_SCALE, min(_MAX_SCALE, self.scale_factor * factor))
        self.view.scale(target / self.scale_factor, target / self.scale_factor)
        self._refresh_zoom()

    def zoom_in(self) -> None:
        self._zoom_by(1.25)

    def zoom_out(self) -> None:
        self._zoom_by(1 / 1.25)

    def fit_to_window(self) -> None:
        self._fit_mode = True
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._refresh_zoom()

    def actual_size(self) -> None:
        self._fit_mode = False
        self.view.resetTransform()
        self._refresh_zoom()

    def save_image(self) -> None:
        _save_png(self.image_bytes, self)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_if_visible)
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
        else:
            super().keyPressEvent(event)


class CheatSheetPoster(QWidget):
    """폭 1200 이내의 포스터를 클릭하면 전체 화면 뷰어를 연다."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image_bytes, self.pixmap = _load_poster()
        self.viewer: PosterViewer | None = None
        self._preview = QPixmap()
        self._preview_key: tuple[int, int, float] | None = None
        self._context_menu: QMenu | None = None
        self.setObjectName("cheatSheetPoster")
        self.setMaximumWidth(_PREVIEW_WIDTH)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("한글 Vim CheatSheet 이미지 · 전체 화면으로 열기")
        self.setAccessibleDescription(
            "클릭하거나 Enter·Space로 확대합니다. 우클릭 메뉴에서 PNG를 저장합니다."
        )
        self.setToolTip("클릭: 전체 화면 확대 · 우클릭: 원본 PNG 저장")

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return (
            round(
                max(0, min(width, _PREVIEW_WIDTH) - 4)
                * (self.pixmap.height() / self.pixmap.width())
            )
            + 4
        )

    def sizeHint(self) -> QSize:
        return QSize(_PREVIEW_WIDTH, self.heightForWidth(_PREVIEW_WIDTH))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        available = self.rect().adjusted(2, 2, -2, -2)
        ratio = self.devicePixelRatioF()
        key = (available.width(), available.height(), ratio)
        if key != self._preview_key:
            self._preview = self.pixmap.scaled(
                QSize(
                    max(1, round(available.width() * ratio)),
                    max(1, round(available.height() * ratio)),
                ),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview.setDevicePixelRatio(ratio)
            self._preview_key = key
        size = self._preview.deviceIndependentSize()
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(QRectF(available).center())
        painter.drawPixmap(target.topLeft(), self._preview)
        painter.setPen(QPen(QColor("#c3ef85" if self.hasFocus() else "#435367"), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.open_viewer()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            if not event.isAutoRepeat():
                self.open_viewer()
            event.accept()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._context_menu = _save_menu(self, event.globalPos(), self.save_image)
        event.accept()

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.update()

    def open_viewer(self) -> None:
        if self.viewer is None:
            self.viewer = PosterViewer(self.pixmap, self.image_bytes, self)
            self.viewer.finished.connect(self._viewer_finished)
        self.viewer.showFullScreen()
        self.viewer.raise_()
        self.viewer.activateWindow()

    def _viewer_finished(self, result: int) -> None:
        self.viewer = None
        if self.isVisible():
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def save_image(self) -> None:
        parent: QWidget = self.viewer if self.viewer is not None else self
        _save_png(self.image_bytes, parent)

    def hideEvent(self, event: QHideEvent) -> None:
        if self.viewer is not None:
            self.viewer.close()
        super().hideEvent(event)
