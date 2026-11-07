"""여러 화면에서 사용하는 Qt 위젯과 스크롤 레이아웃."""

# Third party imports
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def label(text: str, role: str = "", *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


class _EnterButton(QPushButton):
    """포커스된 동작만 Enter 한 번으로 실행하고 누름 반복·키 해제는 무시한다."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if not event.isAutoRepeat() and modifiers == Qt.KeyboardModifier.NoModifier:
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            event.accept()
            return
        super().keyReleaseEvent(event)


def button(
    text: str,
    name: str = "",
    *,
    primary: bool = False,
    enter_activates: bool = False,
) -> QPushButton:
    widget = _EnterButton(text) if enter_activates else QPushButton(text)
    widget.setObjectName("primary" if primary else name)
    if name:
        widget.setAccessibleName(name)
    widget.setAutoDefault(False)
    return widget


def scroll_page(
    *, margins: tuple[int, int, int, int] = (28, 22, 28, 22), spacing: int = 10
) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    outer.addWidget(scroll)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    scroll.setWidget(content)
    return page, layout
