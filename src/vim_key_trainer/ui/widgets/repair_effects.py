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
from PySide6.QtGui import QColor, QHideEvent, QPainter, QPainterPath, QPaintEvent, QPen
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


def _fragment_text(effect: _RepairEvent) -> str:
    source_column = (
        effect.source_column if effect.source_column is not None else effect.column
    )
    return effect.old_text[max(0, source_column - 5) :][:26] or "·"


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
            + ("직접 해체 성공" if result.verdict == "direct" else "시간 초과 · 칼질")
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
            y < 0
            or y + metrics.lineSpacing() > bottom
            or x < 18
            or x > self.width() - 150
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
        else:
            x = max(18.0, min(x, self.width() - 150))
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
        fragment = _fragment_text(effect)
        box = QRectF(
            x - 4,
            y - 2,
            min(
                240,
                max(70, metrics.horizontalAdvance(fragment) + 12),
                self.width() - x - 8,
            ),
            metrics.lineSpacing() + 4,
        )
        if box.width() <= 0:
            return
        if not self.settings.reduced_motion:
            self._draw_fragments(painter, effect, box, tint)
            self._draw_cut(painter, effect, box, tint, level)
            self._draw_sparks(painter, effect, box.center(), tint, level)
            if effect.revenge and effect.direct:
                self._draw_broken_failure(painter, box.center())
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
            self._draw_badge(painter, effect, y, tint, level)

    def _draw_fragments(
        self, painter: QPainter, effect: _RepairEvent, box: QRectF, tint: QColor
    ) -> None:
        if self._progress >= 0.8:
            return
        text = _fragment_text(effect)
        travel = _phase(self._progress, 0.065, 0.8)
        opacity = 0.94 * (1 - _phase(self._progress, 0.49, 0.8))
        source = QRectF(0, 0, box.width(), box.height())
        for side in (-1, 1):
            painter.save()
            painter.setOpacity(opacity)
            painter.translate(
                box.center()
                + QPointF(
                    side * (3 + 35 * travel),
                    -5 * math.sin(travel * math.pi) + 62 * travel**2,
                )
            )
            painter.rotate(side * 18 * travel)
            painter.translate(-source.width() / 2, -source.height() / 2)
            half = QRectF(source)
            half.setWidth(source.width() / 2)
            if side > 0:
                half.moveLeft(source.width() / 2)
            painter.setClipRect(half, Qt.ClipOperation.IntersectClip)
            painter.fillRect(source, QColor("#253b34" if effect.direct else "#49322d"))
            painter.setFont(self.comparison.practice_input.document_font)
            painter.setPen(tint)
            painter.drawRoundedRect(source.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            painter.drawText(
                source.adjusted(4, 1, -2, -1), Qt.AlignmentFlag.AlignVCenter, text
            )
            painter.restore()

    def _draw_cut(
        self,
        painter: QPainter,
        effect: _RepairEvent,
        box: QRectF,
        tint: QColor,
        level: int,
    ) -> None:
        if self._progress >= 0.55:
            return
        opacity = 1 - _phase(self._progress, 0.42, 0.55)
        center = box.center()
        span = min(95.0, box.width() / 2)
        count = 2 if not effect.direct or effect.technique == "delete" else 1
        weight = 2 if effect.technique == "delete" else 1
        for index in range(count):
            cut = _phase(self._progress, index * 0.035, 0.11 + index * 0.035)
            if cut <= 0:
                continue
            slope = 17 if index == 0 else -17
            start = center + QPointF(-span, slope)
            end = center + QPointF(span, -slope)
            tip = start + (end - start) * cut
            path = QPainterPath(start)
            path.quadTo(center + QPointF(0, -slope * 0.4), tip)
            painter.save()
            painter.setOpacity(opacity)
            glow = QColor(tint if effect.direct else "#fb9d86")
            painter.setPen(
                QPen(
                    glow,
                    10 + 2 * level + weight,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(path)
            painter.setPen(
                QPen(
                    QColor("#fff0d3"),
                    2.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(path)
            # 칼끝은 먼저 도착하고 빛의 꼬리는 잠시 같은 자리에 남는다.
            if self._progress < 0.16:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#fff9e6"))
                painter.drawEllipse(tip, 5 + level, 5 + level)
            painter.restore()

    def _draw_sparks(
        self,
        painter: QPainter,
        effect: _RepairEvent,
        center: QPointF,
        tint: QColor,
        level: int,
    ) -> None:
        if not 0.04 < self._progress < 0.8:
            return
        travel = _phase(self._progress, 0.04, 0.8)
        painter.save()
        painter.setOpacity(1 - _phase(self._progress, 0.5, 0.8))
        painter.setPen(QPen(tint, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        count = 8 + level * 3
        for index in range(count):
            angle = index * math.tau / count + 0.2
            direction = QPointF(math.cos(angle), math.sin(angle))
            start = center + direction * (12 + 54 * travel) + QPointF(0, 32 * travel**2)
            if effect.technique == "number":
                painter.drawLine(start, start + QPointF(4, -5))
                painter.drawLine(start + QPointF(4, -5), start + QPointF(8, -2))
            elif effect.technique == "insert":
                painter.drawEllipse(start, 2, 2)
            else:
                painter.drawLine(start, start + direction * (6 + level))
        if travel < 0.3:
            painter.setOpacity((1 - travel / 0.3) * 0.65)
            painter.drawEllipse(center, 10 + travel * 100, 5 + travel * 30)
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
            else "시간 초과"
        )
        if effect.direct and level:
            text += (
                f" · 누적 {effect.chain}곳" if effect.free else f" · {effect.chain}연속"
            )
        metrics = self.fontMetrics()
        width = min(self.width() - 30, metrics.horizontalAdvance(text) + 24)
        badge = QRectF(
            max(15, self.width() - width - 14),
            y - 3,
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
