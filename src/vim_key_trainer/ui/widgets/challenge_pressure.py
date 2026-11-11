"""본문 위치를 바꾸지 않는 문서 바깥의 시간 압박 테두리."""

# Standard library imports
import math

# Third party imports
from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QHideEvent, QPainter, QPaintEvent, QPen
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
        color = QColor("#f4977e" if self.pressure >= 0.7 else "#e4bd79")
        pulse = (
            0.65 if self.settings.reduced_motion else 0.55 + 0.25 * math.sin(self.phase)
        )
        color.setAlphaF(min(1.0, 0.2 + self.pressure * pulse))
        painter.setPen(QPen(color, 1.5 + 2 * self.pressure))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 7, 7)
