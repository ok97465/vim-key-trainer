"""앱 가장자리에 한 번만 남기는 조용한 시간 종료 알림."""

# Third party imports
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QHideEvent,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings


class ExpirationEffect(QWidget):
    """본문 중앙은 투명하게 두고 입력·포커스·레이아웃을 받지 않는다."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.settings = PresentationSettings()
        self.progress = 1.0
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAccessibleName("시간 종료 · 계속 연습할 수 있어요")
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(1150)
        self.animation.valueChanged.connect(self._animate)
        self.animation.finished.connect(self.stop_effects)
        self.static_timer = QTimer(self)
        self.static_timer.setSingleShot(True)
        self.static_timer.setInterval(1150)
        self.static_timer.timeout.connect(self.stop_effects)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.hide()

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.stop_effects()

    def _animate(self, value: float) -> None:
        self.progress = value
        self.update()

    def trigger(self, target: QWidget | None = None) -> None:
        self.stop_effects()
        if not self.settings.effects:
            return
        if target is not None and target is not self.parentWidget():
            previous = self.parentWidget()
            if previous is not None:
                previous.removeEventFilter(self)
            self.setParent(target)
            target.installEventFilter(self)
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self.progress = 0.25 if self.settings.reduced_motion else 0.0
        self.show()
        self.raise_()
        if self.settings.reduced_motion:
            self.static_timer.start()
        else:
            self.animation.start()
        self.update()

    def stop_effects(self) -> None:
        self.animation.stop()
        self.static_timer.stop()
        self.progress = 1.0
        self.hide()

    def hideEvent(self, event: QHideEvent) -> None:
        self.animation.stop()
        self.static_timer.stop()
        self.progress = 1.0
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and isinstance(watched, QWidget):
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self.settings.effects or self.progress >= 1:
            return
        # 180ms가량 천천히 나타나고 잠시 머문 뒤 한 번만 사라진다.
        strength = min(
            1.0,
            self.progress / 0.16,
            (1 - self.progress) / 0.58,
        )
        if strength <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        band = max(24.0, min(80.0, min(self.width(), self.height()) * 0.08))
        tint = QColor("#d4b98c")
        tint.setAlpha(round(40 * strength))
        transparent = QColor(tint)
        transparent.setAlpha(0)
        if not self.settings.reduced_motion:
            for rect, start, end in (
                (
                    QRectF(0, 0, self.width(), band),
                    QPointF(0, 0),
                    QPointF(0, band),
                ),
                (
                    QRectF(0, self.height() - band, self.width(), band),
                    QPointF(0, self.height()),
                    QPointF(0, self.height() - band),
                ),
                (
                    QRectF(0, 0, band, self.height()),
                    QPointF(0, 0),
                    QPointF(band, 0),
                ),
                (
                    QRectF(self.width() - band, 0, band, self.height()),
                    QPointF(self.width(), 0),
                    QPointF(self.width() - band, 0),
                ),
            ):
                gradient = QLinearGradient(start, end)
                gradient.setColorAt(0, tint)
                gradient.setColorAt(1, transparent)
                painter.fillRect(rect, QBrush(gradient))
        border = QColor("#d4b98c")
        border.setAlpha(round(135 * strength))
        painter.setPen(QPen(border, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bounds, 8, 8)
        # 짧은 안내는 위쪽에 고정하고 본문 중앙과 입력 위치는 건드리지 않는다.
        font = QFont(self.font())
        font.setPointSizeF(10.5)
        painter.setFont(font)
        caption = "시간 종료 · 계속 연습할 수 있어요"
        width = min(
            max(0, self.width() - 32),
            painter.fontMetrics().horizontalAdvance(caption) + 62,
        )
        badge = QRectF((self.width() - width) / 2, 18, width, 38)
        painter.setOpacity(strength)
        painter.setBrush(QColor("#263038"))
        painter.setPen(QPen(QColor("#bca783"), 1))
        painter.drawRoundedRect(badge, 10, 10)
        clock = QPointF(badge.left() + 20, badge.center().y())
        painter.setPen(QPen(QColor("#decba8"), 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(clock, 7, 7)
        painter.drawLine(clock, clock + QPointF(0, -4))
        painter.drawLine(clock, clock + QPointF(3, 2))
        painter.drawText(
            badge.adjusted(38, 0, -12, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            caption,
        )
