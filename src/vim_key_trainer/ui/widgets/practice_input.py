"""Qt 기본 편집 기능을 사용하지 않는 전용 입력·목표 표시 위젯."""

# Third party imports
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontDatabase,
    QInputMethodEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Local imports
from vim_key_trainer.ui.qt_input import NormalizedKey, normalize_key_event


class PracticeInput(QWidget):
    key_received = Signal(object)
    key_released = Signal()
    focus_lost = Signal(object)
    composition_blocked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("practiceInput")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self.setMinimumHeight(180)
        self.setAccessibleName("연습 키 입력 영역")
        self.target = ""
        self.position = 0
        self.display_width = 20
        self.font_size = 23
        self.paused = False
        self.diagnostic = False

    def show_target(self, target: str, position: int, display_width: int) -> None:
        self.target = target
        self.position = position
        self.display_width = display_width
        self.setAccessibleDescription(
            f"총 {len(target)}자 중 {position}자 완료. "
            f"다음 문자: {target[position : position + 1]}"
        )
        self.update()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        # QWidget 기본 Tab 포커스 이동보다 먼저 한 곳에서 채점한다.
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.key_received.emit(self.normalize_event(event))
        event.accept()

    def normalize_event(self, event: QKeyEvent) -> NormalizedKey:
        return normalize_key_event(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat():
            self.key_released.emit()
        event.accept()

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        self.composition_blocked.emit()
        event.accept()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.focus_lost.emit(event.reason())
        self.update()

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#819e5f" if self.hasFocus() else "#354458"), 2))
        painter.setBrush(QColor("#151d28"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        if self.paused or self.diagnostic:
            painter.setPen(QColor("#e8edf3"))
            font = self.font()
            font.setPointSize(18)
            painter.setFont(font)
            message = (
                "일시정지 · 재개 버튼을 눌러 주세요"
                if self.paused
                else "이 영역을 클릭하고 키를 눌러 보세요"
            )
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, message)
            return

        start = (self.position // self.display_width) * self.display_width
        block = self.target[start : start + self.display_width]
        columns = min(self.display_width, 20)
        rows = (len(block) + columns - 1) // columns if block else 1
        cell_width = min(42.0, (self.width() - 40) / columns)
        cell_height = 58.0
        left = (self.width() - columns * cell_width) / 2
        top = (self.height() - rows * cell_height) / 2
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(min(float(self.font_size), cell_width * 0.63))
        font.setStyleHint(QFont.StyleHint.Monospace)
        painter.setFont(font)
        for index, character in enumerate(block):
            absolute = start + index
            current = absolute == self.position
            done = absolute < self.position
            box = QRectF(
                left + (index % columns) * cell_width + 2,
                top + (index // columns) * cell_height,
                cell_width - 4,
                cell_height - 8,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor("#c3ef85" if current else "#223327" if done else "#1b2532")
            )
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(
                QColor("#18220e" if current else "#b9de91" if done else "#bdc8d6")
            )
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, character)
            if current:
                painter.setPen(QPen(QColor("#e8edf3"), 2))
                painter.drawLine(box.bottomLeft(), box.bottomRight())
