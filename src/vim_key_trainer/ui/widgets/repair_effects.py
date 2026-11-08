"""판정된 문서 구간의 칼질·체크 효과. 입력과 엔진을 다루지 않는다."""

# Standard library imports
import math
from dataclasses import dataclass

# Third party imports
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QHideEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison


@dataclass(frozen=True, slots=True)
class _RepairEvent:
    row: int
    direct: bool
    old_text: str = ""
    column: int = 0


class RepairEffects(QWidget):
    def __init__(self, comparison: EditComparison) -> None:
        super().__init__(comparison.current_scroll.viewport())
        self.comparison = comparison
        self.settings = PresentationSettings()
        self._attempt_id: str | None = None
        self._seen: set[str] = set()
        self._event: _RepairEvent | None = None
        self._progress = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(comparison.current_scroll.viewport().rect())
        comparison.current_scroll.viewport().installEventFilter(self)
        comparison.current_scroll.verticalScrollBar().valueChanged.connect(self.update)
        comparison.current_scroll.horizontalScrollBar().valueChanged.connect(
            self.update
        )
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(620)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._animate)
        self.animation.finished.connect(self._clear)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(650)
        self._clear_timer.timeout.connect(self._clear)
        self.hide()

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.stop_effects()

    def _animate(self, value: float) -> None:
        self._progress = value
        self.update()

    def _clear(self) -> None:
        self._event = None
        self.hide()

    def stop_effects(self) -> None:
        self.animation.stop()
        self._clear_timer.stop()
        self._clear()

    def set_session(self, session: EditingSession | None) -> None:
        if session is None or not session.bomb_enabled:
            self.stop_effects()
            return
        if session.attempt_id != self._attempt_id:
            self.stop_effects()
            self._seen.clear()
            self._attempt_id = session.attempt_id
        new = [
            result
            for result in session.segment_results
            if result.verdict != "pending" and result.segment_id not in self._seen
        ]
        self._seen.update(result.segment_id for result in new)
        if session.state in {SessionState.PAUSED, SessionState.ABORTED}:
            self.stop_effects()
            return
        if not new or not self.settings.effects:
            return
        result = new[-1]
        segment = next(
            item for item in session.segments if item.id == result.segment_id
        )
        example = next(
            (
                item
                for item in session.failure_examples
                if item.segment_id == segment.id
            ),
            None,
        )
        row = min(segment.target_start_row, len(session.engine.state.lines) - 1)
        old_text = (
            example.before_lines[
                min(segment.target_start_row, len(example.before_lines) - 1)
            ]
            if example is not None
            else ""
        )
        goal_text = (
            example.goal_lines[
                min(segment.target_start_row, len(example.goal_lines) - 1)
            ]
            if example is not None
            else ""
        )
        column = 0
        while (
            column < min(len(old_text), len(goal_text))
            and old_text[column] == goal_text[column]
        ):
            column += 1
        self.stop_effects()
        self._event = _RepairEvent(row, result.verdict == "direct", old_text, column)
        self._progress = 0.0
        self.setAccessibleName(
            f"{row + 1}행 · "
            + ("직접 해체 성공" if result.verdict == "direct" else "시간 초과 · 칼질")
        )
        self.show()
        self.raise_()
        if self.settings.reduced_motion:
            self._clear_timer.start()
        else:
            self.animation.start()
        self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.comparison.current_scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self.setGeometry(self.comparison.current_scroll.viewport().rect())
        return False

    def hideEvent(self, event: QHideEvent) -> None:
        self.animation.stop()
        self._clear_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        effect = self._event
        if effect is None:
            return
        document = self.comparison.practice_input
        metrics = document.document_metrics
        scroll = self.comparison.current_scroll
        y = 16 + effect.row * metrics.lineSpacing() - scroll.verticalScrollBar().value()
        guide = self.comparison.guide_overlay
        bottom = self.height() if guide.isHidden() else guide.y() - 6
        current_line = document.editor_state.lines[
            min(effect.row, len(document.editor_state.lines) - 1)
        ]
        x = (
            58
            + metrics.horizontalAdvance(current_line[: effect.column])
            - scroll.horizontalScrollBar().value()
        )
        detached = (
            y < 0
            or y + metrics.lineSpacing() > bottom
            or x < 18
            or x > self.width() - 90
        )
        # 다음 구간의 커서가 멀리 이동해도 실패한 원문 조각을 표시한다.
        # 화면 표시만 조정하며 문서 스크롤과 엔진 viewport는 건드리지 않는다.
        if detached:
            y = max(5.0, min(y, bottom - metrics.lineSpacing() * 2 - 12))
            x = 24.0
        else:
            x = max(18.0, min(x, self.width() - 90))
        painter = QPainter(self)
        painter.setClipRect(QRectF(0, 0, self.width(), max(0, bottom)))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        progress = self._progress
        opacity = 1.0 if self.settings.reduced_motion else min(1.0, (1 - progress) * 3)
        painter.setOpacity(opacity)
        box = QRectF(
            x - 4, y - 2, min(300, self.width() - x - 8), metrics.lineSpacing() + 4
        )
        if box.width() <= 0:
            return
        tint = QColor("#bff5d1" if effect.direct else "#ffc5ae")
        if detached:
            painter.setPen(tint)
            painter.drawText(
                QRectF(x, y, self.width() - x - 12, metrics.lineSpacing()),
                Qt.AlignmentFlag.AlignLeft,
                f"{effect.row + 1}행 · "
                + ("직접 해체" if effect.direct else "시간 초과 원문"),
            )
            y += metrics.lineSpacing()
            box.moveTop(y - 2)
        if self.settings.reduced_motion or effect.direct:
            # 표시는 줄 오른쪽에만 두어 본문과 기존 차이 강조를 보존한다.
            badge = QRectF(
                max(20, self.width() - 134), y - 3, 122, metrics.lineSpacing() + 6
            )
            painter.setBrush(QColor("#213b32" if effect.direct else "#49322d"))
            painter.setPen(QPen(tint, 1))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(tint)
            painter.drawText(
                badge,
                Qt.AlignmentFlag.AlignCenter,
                "✓ 직접 해체!" if effect.direct else "시간 초과",
            )
            if effect.direct and not self.settings.reduced_motion:
                for index in range(7):
                    angle = index * math.tau / 7
                    center = badge.center()
                    point = center + QPointF(
                        math.cos(angle) * (20 + 35 * progress),
                        math.sin(angle) * (8 + 15 * progress),
                    )
                    painter.drawLine(point - QPointF(2, 0), point + QPointF(2, 0))
                    painter.drawLine(point - QPointF(0, 2), point + QPointF(0, 2))
            return
        if effect.old_text and progress < 0.75:
            painter.save()
            painter.setOpacity(opacity * (1 - progress) * 0.8)
            painter.fillRect(box, QColor("#25202b"))
            painter.setFont(document.document_font)
            painter.setPen(QColor("#f2c5bd"))
            painter.drawText(
                box.adjusted(4, 2, 0, 0),
                Qt.AlignmentFlag.AlignLeft,
                effect.old_text[max(0, effect.column - 10) :],
            )
            painter.restore()
        center = QPointF(min(x + 95, self.width() - 55), y + metrics.lineSpacing() / 2)
        for index, delay in enumerate((0.0, 0.2)):
            cut = min(1.0, max(0.0, (progress - delay) / 0.45))
            if cut <= 0:
                continue
            start = center + QPointF(-75, 15 if index == 0 else -15)
            end = center + QPointF(75, -15 if index == 0 else 15)
            tip = start + (end - start) * cut
            path = QPainterPath(start)
            path.lineTo(tip)
            painter.setPen(
                QPen(
                    QColor("#fb9d86"),
                    8 * (1 - progress) + 1,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(path)
            painter.setPen(
                QPen(
                    QColor("#fff0d3"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap
                )
            )
            painter.drawPath(path)
        painter.setPen(QPen(tint, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for index in range(8):
            angle = index * math.tau / 8 + 0.1
            direction = QPointF(math.cos(angle), math.sin(angle))
            start = center + direction * (8 + 25 * progress)
            painter.drawLine(start, start + direction * 7)
