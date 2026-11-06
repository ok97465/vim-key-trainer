"""여러 화면에서 사용하는 Qt 위젯과 스크롤 레이아웃."""

# Third party imports
from PySide6.QtCore import Qt
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


def button(text: str, name: str = "", *, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
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
