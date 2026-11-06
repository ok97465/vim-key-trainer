"""명령 목록과 논리 키의 부분 입력을 표시하는 전용 입력 위젯."""

# Standard library imports
from functools import lru_cache

# Third party imports
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPaintEvent,
    QPen,
)

# Local imports
from vim_key_trainer.domain.commands import CommandItem
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.ui.widgets.practice_input import PracticeInput


@lru_cache(maxsize=128)
def _fit_tokens(
    tokens: tuple[KeyToken, ...], width: float, height: float, font_size: int
) -> tuple[QFont, tuple[QRectF, ...]]:
    """키 표기를 최대 두 줄에 배치하고 같은 크기의 배치는 재사용한다."""
    candidates: list[tuple[QFont, tuple[QRectF, ...]]] = []
    fallback: tuple[QFont, tuple[QRectF, ...]] | None = None
    for max_rows in (1, 2):
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(float(font_size))
        metrics = QFontMetricsF(font)
        font.setPointSizeF(font_size * min(1.0, height / (metrics.height() * max_rows)))
        for _ in range(32):
            metrics = QFontMetricsF(font)
            widths = tuple(metrics.horizontalAdvance(token.display) for token in tokens)
            widest = max(widths)
            if widest > width:
                font.setPointSizeF(max(1.0, font.pointSizeF() * width / widest * 0.98))
                continue
            x = 0.0
            row = 0
            cells: list[QRectF] = []
            for token_width in widths:
                if x and x + token_width > width:
                    row += 1
                    x = 0.0
                cells.append(
                    QRectF(x, row * metrics.height(), token_width, metrics.height())
                )
                x += token_width
            top = max(0.0, (height - (row + 1) * metrics.height()) / 2)
            fallback = (QFont(font), tuple(cell.translated(0, top) for cell in cells))
            if row < max_rows:
                candidates.append(
                    (font, tuple(cell.translated(0, top) for cell in cells))
                )
                break
            if font.pointSizeF() <= 1.0:
                break
            font.setPointSizeF(max(1.0, font.pointSizeF() * 0.9))
    if not candidates:
        assert fallback is not None
        return fallback
    return max(candidates, key=lambda candidate: candidate[0].pointSizeF())


def _fit_hint(text: str, metrics: QFontMetricsF, width: float, height: float) -> str:
    flags = Qt.TextFlag.TextWordWrap
    bounds = QRectF(0, 0, width, 10_000)
    if metrics.boundingRect(bounds, int(flags), text).height() <= height:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = text[:middle].rstrip() + "…"
        if metrics.boundingRect(bounds, int(flags), candidate).height() <= height:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"


class CommandInput(PracticeInput):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("commandInput")
        self.setMinimumWidth(400)
        self.setAccessibleName("Vim 명령 입력 영역")
        self.items: tuple[CommandItem, ...] = ()
        self.command_index = 0
        self.token_index = 0
        self.display_count = 10
        self.completed_offset = 0

    def event(self, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.DevicePixelRatioChange,
        }:
            _fit_tokens.cache_clear()
            self.update()
        return super().event(event)

    def show_commands(
        self,
        items: tuple[CommandItem, ...],
        command_index: int,
        token_index: int,
        display_count: int,
        completed_offset: int = 0,
    ) -> None:
        self.items = items
        self.command_index = command_index
        self.token_index = token_index
        self.display_count = display_count
        self.completed_offset = completed_offset
        row_height = max(42, self.font_size * 2)
        self.setMinimumHeight(((display_count + 1) // 2) * row_height + 12)
        current = items[command_index] if command_index < len(items) else None
        self.setAccessibleDescription(
            f"명령 {completed_offset + command_index}개 완료. "
            + (
                f"현재 명령 {current.display}, "
                f"다음 키 {current.tokens[token_index].display}. "
                f"뜻: {current.brief_meaning}"
                if current is not None
                else "모든 명령 완료"
            )
        )
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.paused:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#819e5f" if self.hasFocus() else "#354458"), 2))
        painter.setBrush(QColor("#151d28"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        if not self.items:
            return
        start = (min(self.command_index, len(self.items) - 1) // self.display_count) * (
            self.display_count
        )
        visible = self.items[start : start + self.display_count]
        rows = (len(visible) + 1) // 2
        width = (self.width() - 30) / 2
        height = (self.height() - 16) / max(rows, 1)
        for offset, item in enumerate(visible):
            absolute = start + offset
            current = absolute == self.command_index
            done = absolute < self.command_index
            box = QRectF(
                10 + (offset % 2) * (width + 10),
                8 + (offset // 2) * height,
                width,
                height - 6,
            )
            painter.setPen(QPen(QColor("#c3ef85" if current else "#354458"), 1))
            painter.setBrush(QColor("#223327" if done else "#1b2532"))
            painter.drawRoundedRect(box, 6, 6)
            font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            font.setPointSize(10)
            painter.setFont(font)
            painter.setPen(QColor("#b9de91" if done else "#8998aa"))
            number = "✓" if done else f"{self.completed_offset + absolute + 1:02}"
            prefix_width = max(35.0, QFontMetricsF(font).horizontalAdvance(number) + 16)
            painter.drawText(
                QRectF(box.left() + 8, box.top(), prefix_width - 8, box.height()),
                Qt.AlignmentFlag.AlignVCenter,
                number,
            )
            available = max(1.0, box.width() - prefix_width - 11)
            hint_width = min(220.0, available * 0.50)
            command_width = max(1.0, available - hint_width - 12)
            font, token_rects = _fit_tokens(
                item.tokens, command_width, box.height() - 6, self.font_size
            )
            painter.setFont(font)
            for index, (token, relative) in enumerate(
                zip(item.tokens, token_rects, strict=True)
            ):
                token_box = relative.translated(
                    box.left() + prefix_width, box.top() + 3
                )
                active = current and index == self.token_index
                accepted = done or (current and index < self.token_index)
                if active:
                    painter.fillRect(token_box, QColor("#c3ef85"))
                painter.setPen(
                    QColor(
                        "#17220e" if active else "#b9de91" if accepted else "#bdc8d6"
                    )
                )
                painter.drawText(token_box, Qt.AlignmentFlag.AlignCenter, token.display)
                if active:
                    painter.setPen(QPen(QColor("#e8edf3"), 2))
                    painter.drawLine(token_box.bottomLeft(), token_box.bottomRight())
            hint_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
            hint_font.setPointSizeF(max(1.0, min(9.5, font.pointSizeF() * 0.75)))
            hint_box = QRectF(
                box.right() - hint_width - 9,
                box.top() + 4,
                hint_width,
                box.height() - 8,
            )
            hint_color = QColor("#bdc8d6")
            hint_color.setAlphaF(0.62)
            painter.setPen(hint_color)
            painter.setFont(hint_font)
            painter.drawText(
                hint_box,
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap,
                _fit_hint(
                    item.brief_meaning,
                    QFontMetricsF(hint_font),
                    hint_box.width(),
                    hint_box.height(),
                ),
            )
