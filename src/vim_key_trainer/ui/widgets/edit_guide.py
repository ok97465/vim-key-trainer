"""문서 위에서 입력 진행을 보여 주는 포커스 없는 반투명 가이드."""

# Third party imports
from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPaintEvent,
    QTextLayout,
)
from PySide6.QtWidgets import QWidget

# Local imports
from vim_key_trainer.domain.keys import KeyToken


class EditGuideOverlay(QWidget):
    """문서가 아닌 viewport에 붙어 스크롤·입력·포커스에 관여하지 않는다."""

    def __init__(self, viewport: QWidget) -> None:
        super().__init__(viewport)
        self.setObjectName("editGuideOverlay")
        self.setStyleSheet("#editGuideOverlay { background: transparent; }")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("현재 단계 가이드")
        self.keys: tuple[KeyToken, ...] = ()
        self.completed = 0
        self.description = ""
        self.progress = ""
        self._paused = False
        viewport.installEventFilter(self)
        self.hide()

    def show_guide(
        self,
        keys: tuple[KeyToken, ...],
        completed: int,
        *,
        description: str,
        progress: str,
    ) -> None:
        self.keys = keys
        self.completed = min(len(keys), max(0, completed))
        self.description = description
        self.progress = progress
        next_key = (
            keys[self.completed].display if self.completed < len(keys) else "없음"
        )
        self.setAccessibleDescription(
            f"{progress} · {description}\n"
            + "".join(token.display for token in keys)
            + f"\n{self.completed}/{len(keys)}키 완료 · 다음 키: {next_key}"
        )
        self._place()
        self.setVisible(bool(keys) and not self._paused)
        self.raise_()
        self.update()

    def clear_guide(self) -> None:
        self.keys = ()
        self.completed = 0
        self.description = self.progress = ""
        self.setAccessibleDescription("")
        self.hide()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.setVisible(bool(self.keys) and not paused)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
            self._place()
        return super().eventFilter(watched, event)

    def _place(self) -> None:
        viewport = self.parentWidget()
        if viewport is None:
            return
        margin = min(10, max(0, viewport.width() // 12))
        height = min(40, viewport.height())
        self.setGeometry(
            margin,
            max(0, viewport.height() - height - 4),
            max(1, viewport.width() - 2 * margin),
            height,
        )

    def _command_font(self) -> QFont:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSizeF(18)
        if self.keys and self.completed < len(self.keys):
            width = QFontMetricsF(font).horizontalAdvance(
                self.keys[self.completed].display
            )
            available = max(1, self.width() - 24)
            if width > available:
                font.setPointSizeF(max(1.0, 18 * available / width))
        return font

    def _content_rects(self) -> tuple[QRectF, QRectF]:
        available = max(1.0, self.width() - 24.0)
        metrics = QFontMetricsF(self._command_font())
        active = min(self.completed, max(0, len(self.keys) - 1))
        next_width = (
            metrics.horizontalAdvance(self.keys[active].display) if self.keys else 0
        )
        # Reserve symmetric side space so the command stays at the bar's center.
        required = min(available, max(80.0, next_width))
        details_width = min(
            180.0, available * 0.3, max(0.0, (available - required) / 2 - 8)
        )
        inset = details_width + 8 if details_width else 0.0
        return (
            QRectF(12 + inset, 0, available - 2 * inset, self.height()),
            QRectF(self.width() - 12 - details_width, 0, details_width, self.height()),
        )

    def _token_rects(self) -> tuple[QRectF, ...]:
        metrics = QFontMetricsF(self._command_font())
        widths = [metrics.horizontalAdvance(token.display) for token in self.keys]
        command_rect, _ = self._content_rects()
        available = command_rect.width()
        active = min(self.completed, max(0, len(widths) - 1))
        before = sum(widths[:active])
        # Keep some preceding input visible while fitting the entire next logical key.
        offset = max(0.0, before + (widths[active] if widths else 0) - available)
        x = command_rect.left() + max(0.0, (available - sum(widths)) / 2) - offset
        boxes: list[QRectF] = []
        for width in widths:
            boxes.append(QRectF(x, 0, width, self.height()))
            x += width
        return tuple(boxes)

    def token_rect(self, index: int) -> QRectF:
        """표시 창 기준 키 영역. 긴 명령도 다음 논리 키는 전체가 보인다."""
        return self._token_rects()[index]

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 19, 28, 170))
        painter.drawRoundedRect(QRectF(self.rect()), 8, 8)
        painter.setFont(self._command_font())
        command_rect, details_rect = self._content_rects()
        painter.save()
        painter.setClipRect(command_rect)
        for index, (token, box) in enumerate(
            zip(self.keys, self._token_rects(), strict=True)
        ):
            color = (
                QColor(204, 220, 235, 55)
                if index < self.completed
                else QColor(195, 239, 133, 225)
                if index == self.completed
                else QColor(222, 232, 243, 180)
            )
            painter.setPen(color)
            painter.drawText(box, Qt.AlignmentFlag.AlignVCenter, token.display)
        painter.restore()
        font = QFont(self.font())
        font.setPointSizeF(10)
        painter.setFont(font)
        painter.setPen(QColor(190, 204, 219, 155))
        details = " · ".join(
            value for value in (self.progress, self.description) if value
        )
        if details_rect.width() < 1 or not details:
            return
        text_layout = QTextLayout(details, font)
        text_layout.beginLayout()
        first_line = text_layout.createLine()
        first_line.setLineWidth(details_rect.width())
        split = first_line.textLength()
        text_layout.endLayout()
        remaining = details[split:].strip()
        details = details[:split].rstrip()
        if remaining:
            details += "\n" + painter.fontMetrics().elidedText(
                remaining, Qt.TextElideMode.ElideRight, int(details_rect.width())
            )
        painter.drawText(
            details_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            details,
        )
