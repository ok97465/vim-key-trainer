"""판정된 구간의 절단·분리·잔흔. 복제 그림만 움직이고 입력은 받지 않는다."""

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
from PySide6.QtGui import (
    QBrush,
    QColor,
    QHideEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

# Local imports
from vim_key_trainer.domain.free_repair_progress import FreeRepairEvent
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.challenge_feedback import (
    chain_level,
    is_close_call,
    segment_technique,
)
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison


@dataclass(frozen=True, slots=True)
class _RepairEvent:
    row: int
    direct: bool
    old_text: str
    column: int
    chain: int
    technique: str
    close_call: bool
    revenge: bool
    free: bool = False
    batch_size: int = 1
    source_column: int | None = None


def _phase(value: float, start: float, end: float) -> float:
    return min(1.0, max(0.0, (value - start) / (end - start)))


def _fragment_text(effect: _RepairEvent) -> tuple[str, str]:
    source_column = (
        effect.source_column if effect.source_column is not None else effect.column
    )
    start = max(0, source_column - 5)
    return effect.old_text[start : start + 26] or "·", effect.old_text[
        start:source_column
    ]


class RepairEffects(QWidget):
    """선형 시간축에서 절단·파편·표식의 수명을 따로 조절한다."""

    def __init__(self, comparison: EditComparison) -> None:
        super().__init__(comparison.current_scroll.viewport())
        self.comparison = comparison
        self.settings = PresentationSettings()
        self._attempt_id: str | None = None
        self._seen: set[str] = set()
        self._free_seen: set[str] = set()
        self._events: tuple[_RepairEvent, ...] = ()
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
        self.animation.setDuration(1250)
        # 이동의 easing을 불투명도에 재사용하면 조각이 너무 일찍 사라진다.
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.valueChanged.connect(self._animate)
        self.animation.finished.connect(self.stop_effects)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(1250)
        self._clear_timer.timeout.connect(self.stop_effects)
        self.hide()

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.stop_effects()

    def _animate(self, value: float) -> None:
        self._progress = value
        self.update()

    def stop_effects(self) -> None:
        self.animation.stop()
        self._clear_timer.stop()
        self._events = ()
        self.hide()

    def set_session(self, session: EditingSession | None) -> None:
        if session is None:
            self.stop_effects()
            return
        if session.attempt_id != self._attempt_id:
            self.stop_effects()
            self._seen.clear()
            self._free_seen.clear()
            self._attempt_id = session.attempt_id
        if session.state in {
            SessionState.READY,
            SessionState.PAUSED,
            SessionState.ABORTED,
        }:
            self._seen.update(
                result.segment_id
                for result in session.segment_results
                if result.verdict != "pending"
            )
            self.stop_effects()
            return
        if not session.bomb_enabled:
            if session.mode != "free":
                self.stop_effects()
            return
        new = [
            result
            for result in session.segment_results
            if result.verdict != "pending" and result.segment_id not in self._seen
        ]
        self._seen.update(result.segment_id for result in new)
        # 자유 풀이의 문서 전체 판정은 특정 수정 행을 가리키지 않는다.
        # 성공은 결과 피날레, 시간 초과는 상태 줄에 맡겨 엉뚱한 행을 자르지 않는다.
        if session.mode == "free":
            if new:
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
        before = (
            session.lesson.guide[segment.start_step - 1].expected.lines
            if segment.start_step
            else session.lesson.initial.lines
        )
        after = session.lesson.guide[segment.end_step - 1].expected.lines
        if example is not None:
            before, after = example.before_lines, example.goal_lines
        row = min(segment.target_start_row, len(session.engine.state.lines) - 1)
        old_text = before[min(segment.target_start_row, len(before) - 1)]
        goal_text = after[min(segment.target_start_row, len(after) - 1)]
        column = 0
        while (
            column < min(len(old_text), len(goal_text))
            and old_text[column] == goal_text[column]
        ):
            column += 1
        effect = _RepairEvent(
            row,
            result.verdict == "direct",
            old_text,
            column,
            session.chain,
            segment_technique(session, result.segment_id),
            result.verdict == "direct" and is_close_call(result),
            bool(session.revenge_segments),
        )
        self._present(
            (effect,),
            f"{row + 1}행 · "
            + ("직접 해체 성공" if result.verdict == "direct" else "시간 초과 · 파손")
            + (" · 간발의 해체" if effect.close_call else "")
            + (" · 복수 성공" if effect.revenge and effect.direct else ""),
        )

    def show_free_repairs(self, events: tuple[FreeRepairEvent, ...]) -> None:
        """시도 안에서 처음 해결한 곳을 입력을 멈추지 않고 함께 표시한다."""
        fresh = tuple(event for event in events if event.id not in self._free_seen)
        self._free_seen.update(event.id for event in events)
        if not fresh or not self.settings.effects:
            return
        effects = tuple(
            _RepairEvent(
                row=event.row,
                direct=True,
                old_text=event.old_text,
                column=event.column,
                chain=event.first_solved_total,
                technique=event.technique,
                close_call=False,
                revenge=False,
                free=True,
                batch_size=len(fresh),
                source_column=event.source_column,
            )
            for event in fresh
        )
        self._present(
            effects,
            f"자유 풀이 · {len(fresh)}곳 복구 · "
            + ", ".join(f"{event.row + 1}행" for event in fresh),
        )

    def _present(self, events: tuple[_RepairEvent, ...], description: str) -> None:
        self.stop_effects()
        self._events = events
        self._progress = 0.0
        self.setAccessibleName(description)
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
        self._events = ()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        events = self._events
        if not events:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        guide = self.comparison.guide_overlay
        bottom = self.height() if guide.isHidden() else guide.y() - 6
        painter.setClipRect(QRectF(0, 0, self.width(), max(0, bottom)))
        metrics = self.comparison.practice_input.document_metrics
        offset = self.comparison.current_scroll.verticalScrollBar().value()
        cursor_row = self.comparison.practice_input.editor_state.row

        def display_priority(effect: _RepairEvent) -> tuple[bool, int, int]:
            y = 16 + effect.row * metrics.lineSpacing() - offset
            return not 0 <= y < bottom, abs(effect.row - cursor_row), effect.column

        capacity = max(1, min(4, int(bottom / (metrics.lineSpacing() * 2 + 12))))
        selected = sorted(events, key=display_priority)[:capacity]
        for index, effect in enumerate(selected):
            self._draw_effect(painter, effect, index, draw_badge=len(events) == 1)
        if len(events) > 1:
            primary = max(events, key=lambda effect: effect.chain)
            level = chain_level(primary.chain)
            self._draw_badge(painter, primary, 6, self._tint(primary), level)

    @staticmethod
    def _tint(effect: _RepairEvent) -> QColor:
        level = chain_level(effect.chain) if effect.direct else 0
        return QColor(
            ("#bff5d1", "#a7ecf5", "#ffe1a1", "#d9c0ff")[level]
            if effect.direct
            else "#ffc5ae"
        )

    def _draw_effect(
        self,
        painter: QPainter,
        effect: _RepairEvent,
        slot: int,
        *,
        draw_badge: bool,
    ) -> None:
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
            y < 0 or y + metrics.lineSpacing() > bottom or not 0 <= x < self.width()
        )
        if detached:
            y = max(
                5.0,
                min(
                    5 + slot * (metrics.lineSpacing() * 2 + 12),
                    bottom - metrics.lineSpacing() * 3 - 24,
                ),
            )
            x = 24.0
        level = chain_level(effect.chain) if effect.direct else 0
        tint = self._tint(effect)
        if detached:
            painter.setPen(tint)
            painter.drawText(
                QRectF(x, y, self.width() - x - 12, metrics.lineSpacing()),
                Qt.AlignmentFlag.AlignLeft,
                f"{effect.row + 1}행 · "
                + (
                    "자유 복구"
                    if effect.free
                    else "직접 해체"
                    if effect.direct
                    else "시간 초과 원문"
                ),
            )
            y += metrics.lineSpacing()
        fragment, prefix = _fragment_text(effect)
        leading = 6 + metrics.horizontalAdvance(prefix)
        box = QRectF(
            x - max(13.0, leading),
            y - 2,
            min(
                240.0, max(50.0, leading + 16, metrics.horizontalAdvance(fragment) + 19)
            ),
            metrics.lineSpacing() + 4,
        )
        center = QPointF(x, box.center().y())
        if not self.settings.reduced_motion:
            self._draw_fragments(painter, effect, box, center, fragment, leading, tint)
            if effect.direct:
                self._draw_cut(painter, effect, center, tint, level)
                if effect.revenge:
                    self._draw_broken_failure(painter, center)
            else:
                self._draw_fracture(painter, center, tint)
            self._draw_sparks(painter, effect, center, tint, level)
        elif effect.free and effect.batch_size > 1:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(tint, 1.5))
            painter.drawRoundedRect(box, 4, 4)
            marker = box.topLeft() + QPointF(-12, box.height() / 2)
            path = QPainterPath(marker + QPointF(-3, 0))
            path.lineTo(marker + QPointF(0, 3))
            path.lineTo(marker + QPointF(5, -4))
            painter.drawPath(path)
        if draw_badge:
            self._draw_badge(painter, effect, y, tint, level, anchor_x=x)

    def _draw_fragments(
        self,
        painter: QPainter,
        effect: _RepairEvent,
        box: QRectF,
        center: QPointF,
        text: str,
        leading: float,
        tint: QColor,
    ) -> None:
        if self._progress >= 0.74:
            return
        travel = _phase(self._progress, 0.04, 0.74)
        spread = 1 - (1 - travel) ** 3
        opacity = 0.82 * (1 - _phase(self._progress, 0.18, 0.74))
        source = QRectF(0, 0, box.width(), box.height())
        split = center.x() - box.left()
        top = QPointF(split + 8, 0)
        bottom = QPointF(split - 8, source.bottom())
        seam = (
            [top, bottom]
            if effect.direct
            else [
                top,
                QPointF(split - 3, source.height() * 0.36),
                QPointF(split + 5, source.height() * 0.57),
                bottom,
            ]
        )
        for side in (-1, 1):
            edge_x = 0.0 if side < 0 else source.right()
            mask = QPainterPath()
            mask.addPolygon(
                QPolygonF([QPointF(edge_x, 0), *seam, QPointF(edge_x, source.bottom())])
            )
            mask.closeSubpath()
            painter.save()
            painter.setOpacity(opacity)
            painter.translate(
                center
                + QPointF(
                    side * (2 + (37 if effect.direct else 12) * spread),
                    -side * 11 * spread + (58 if effect.direct else 90) * travel**2,
                )
            )
            painter.rotate(side * (13 if effect.direct else 29) * spread)
            painter.translate(-split, -source.height() / 2)
            painter.setClipPath(mask, Qt.ClipOperation.IntersectClip)
            painter.setBrush(QColor("#263d36" if effect.direct else "#4b302b"))
            edge = QColor(tint)
            edge.setAlpha(140)
            painter.setPen(QPen(edge, 1))
            painter.drawPath(mask)
            painter.setFont(self.comparison.practice_input.document_font)
            painter.setPen(tint)
            painter.drawText(
                source.adjusted(split - leading + 6, 0, -2, 0),
                Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            painter.restore()

    def _draw_cut(
        self,
        painter: QPainter,
        effect: _RepairEvent,
        center: QPointF,
        tint: QColor,
        level: int,
    ) -> None:
        if self._progress >= 0.39:
            return
        heavy = effect.technique == "delete"
        span = 47 + level * 8 + (10 if heavy else 0)
        count = 2 if heavy or effect.close_call else 1
        for index in range(count):
            delay = index * 0.042
            if self._progress < delay:
                continue
            sweep = _phase(self._progress, delay, 0.10 + delay)
            travel = 1 - 0.88 * (1 - sweep) ** 2
            start = center + QPointF(-span, 16 + index * 9)
            end = center + QPointF(span, -16 + index * 9)
            tip = start + (end - start) * travel
            trail = QPainterPath(start)
            trail.quadTo(start + (tip - start) * 0.42 + QPointF(0, 5), tip)
            painter.save()
            painter.setOpacity(1 - _phase(self._progress, 0.13, 0.39))
            glow = QColor(tint)
            glow.setAlpha(155)
            trail_color = QLinearGradient(start, tip)
            trail_color.setColorAt(0, Qt.GlobalColor.transparent)
            trail_color.setColorAt(0.60, glow)
            trail_color.setColorAt(1, tint)
            painter.setPen(
                QPen(
                    QBrush(trail_color),
                    (10 + 2 * level) if index == 0 else 5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(trail)
            trail_color.setColorAt(1, QColor("#fff8e9"))
            painter.setPen(QPen(QBrush(trail_color), 2.0))
            painter.drawPath(trail)
            painter.restore()

    def _draw_fracture(self, painter: QPainter, center: QPointF, tint: QColor) -> None:
        fade = 1 - _phase(self._progress, 0.19, 0.51)
        if not fade:
            return
        reach = 1 - 0.68 * (1 - _phase(self._progress, 0, 0.09)) ** 2
        fracture = QPainterPath()
        for arm in (
            [(-10, -5), (-18, -4), (-25, -13), (-36, -10)],
            [(9, 3), (18, -2), (27, 11), (37, 8)],
            [(2, -8), (-3, -12), (4, -20)],
            [(-4, 7), (1, 15), (-5, 23)],
        ):
            fracture.moveTo(center)
            for x, y in arm:
                fracture.lineTo(center + QPointF(x, y) * reach)
        painter.save()
        painter.setOpacity(fade)
        painter.setPen(QPen(QColor("#943e31"), 5))
        painter.drawPath(fracture)
        painter.setPen(QPen(tint, 1.8))
        painter.drawPath(fracture)
        painter.restore()

    def _draw_sparks(
        self,
        painter: QPainter,
        effect: _RepairEvent,
        center: QPointF,
        tint: QColor,
        level: int,
    ) -> None:
        if self._progress >= 0.72:
            return
        travel = _phase(self._progress, 0, 0.72)
        spread = 1 - (1 - travel) ** 2
        painter.save()
        painter.setOpacity(1 - _phase(self._progress, 0.24, 0.72))
        painter.setPen(QPen(tint, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if not effect.direct:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tint)
        count = 9 + level * 3
        fall = (26 if effect.direct else 65) * travel**2
        for index in range(count):
            angle = index * math.tau / count + 0.2
            direction = QPointF(math.cos(angle), math.sin(angle))
            distance = 7 + (29 + level * 6 + 7 * (index % 3)) * spread
            start = center + direction * distance + QPointF(0, fall)
            if not effect.direct:
                painter.drawPolygon(
                    QPolygonF([start, start + QPointF(-4, -2), start + QPointF(2, 5)])
                )
            elif effect.technique == "number":
                painter.drawLine(start, start + QPointF(4, -5))
                painter.drawLine(start + QPointF(4, -5), start + QPointF(8, -2))
            elif effect.technique == "insert":
                painter.drawEllipse(start, 1.8, 1.8)
            else:
                painter.drawLine(start, start + direction * (7 + level * 2))
        if effect.direct and travel < 0.33:
            painter.setOpacity((1 - travel / 0.33) * 0.55)
            painter.drawEllipse(center, 9 + spread * (55 + 12 * level), 4 + spread * 21)
        painter.restore()

    def _draw_broken_failure(self, painter: QPainter, center: QPointF) -> None:
        travel = _phase(self._progress, 0, 0.5)
        if travel >= 1:
            return
        painter.save()
        painter.setOpacity(1 - travel)
        painter.setPen(
            QPen(QColor("#f4a18b"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        for side in (-1, 1):
            offset = QPointF(side * (8 + travel * 35), travel * 24)
            for vertical in (-1, 1):
                painter.drawLine(
                    center + offset + QPointF(side * 8, vertical * 8), center + offset
                )
        painter.restore()

    def _draw_badge(
        self,
        painter: QPainter,
        effect: _RepairEvent,
        y: float,
        tint: QColor,
        level: int,
        *,
        anchor_x: float | None = None,
    ) -> None:
        text = (
            f"✓ {effect.batch_size}곳 연쇄 복구!"
            if effect.free and effect.batch_size > 1
            else "✓ 자유 복구!"
            if effect.free
            else (
                "복수 성공!"
                if effect.revenge
                else "간발의 해체!"
                if effect.close_call
                else "✓ 직접 해체!"
            )
            if effect.direct
            else "! 시간 초과"
        )
        if effect.direct and level:
            text += (
                f" · 누적 {effect.chain}곳" if effect.free else f" · {effect.chain}연속"
            )
        metrics = self.fontMetrics()
        width = min(self.width() - 30, metrics.horizontalAdvance(text) + 24)
        right_x = self.width() - width - 14
        left_x = 14 if anchor_x is not None and anchor_x + 32 > right_x else right_x
        badge = QRectF(
            left_x,
            max(4.0, y - 3),
            width,
            self.comparison.practice_input.document_metrics.lineSpacing() + 8,
        )
        painter.save()
        if not self.settings.reduced_motion:
            # 이 반동은 장식 배지만 움직인다. 본문 좌표와 커서는 고정이다.
            pulse = math.sin(_phase(self._progress, 0, 0.16) * math.pi)
            painter.translate(0, -4 * pulse)
            painter.setOpacity(1 - _phase(self._progress, 0.86, 1.0))
        painter.setBrush(QColor("#213b32" if effect.direct else "#49322d"))
        painter.setPen(QPen(tint, 1.5 + level * 0.35))
        painter.drawRoundedRect(badge, 7, 7)
        painter.setPen(tint)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
