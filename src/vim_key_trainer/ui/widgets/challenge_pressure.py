"""본문 위치를 바꾸지 않는 현재 문서의 시간 압박 테두리."""

# Standard library imports
import math

# Third party imports
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings


class ChallengePressure(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.settings = PresentationSettings()
        self.pressure = 0.0
        self.phase = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)
        self.hide()

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.set_pressure(self.pressure)

    def set_pressure(self, pressure: float) -> None:
        self.pressure = max(0.0, min(1.0, pressure))
        self.setVisible(self.settings.effects and self.pressure > 0)
        if not self.isHidden():
            self.raise_()
        self.update()

    def set_phase(self, phase: float) -> None:
        self.phase = phase
        if not self.isHidden() and not self.settings.reduced_motion:
            self.update()

    def stop_effects(self) -> None:
        self.pressure = 0.0
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and isinstance(watched, QWidget):
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def hideEvent(self, event: QHideEvent) -> None:
        self.phase = 0.0
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self.settings.effects or self.pressure <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#ff9c81" if self.pressure >= 0.7 else "#f4c378")
        pulse = (
            0.7 if self.settings.reduced_motion else 0.65 + 0.20 * math.sin(self.phase)
        )
        color.setAlphaF(0.18 + self.pressure * pulse * 0.82)
        frame = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        painter.setPen(QPen(color, 1 + self.pressure * 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame, 4, 4)
        # 폭탄과 맞닿은 위쪽에 빛을 모으고 본문과 가이드 영역은 비워 둔다.
        glow = QLinearGradient(frame.topLeft(), QPointF(frame.right(), frame.top()))
        glow.setColorAt(0, color)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawRect(
            QRectF(5, 1, max(0.0, frame.width() - 9), 1 + 3 * self.pressure)
        )
