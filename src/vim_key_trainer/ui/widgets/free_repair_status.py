"""자유 풀이의 부분 복구를 나타내는 읽기 전용 진행 표시."""

# Standard library imports
import math

# Third party imports
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QHideEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

# Local imports
from vim_key_trainer.domain.free_repair_progress import FreeRepairSnapshot
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.ui.challenge_feedback import chain_level


class FreeRepairStatus(QWidget):
    """현재 복구와 시도 내 최초 복구를 구분하며 점수나 완료를 판정하지 않는다."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = PresentationSettings()
        self.snapshot: FreeRepairSnapshot | None = None
        self.message = ""
        self._seen: set[str] = set()
        self._batch_size = 0
        self._pulse = 1.0
        self.setMinimumHeight(42)
        self.setMaximumHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setToolTip(
            "처음 문서의 수정 지점을 어떤 순서로 풀어도 반응합니다. "
            "되돌리면 현재 복구 수는 줄고 같은 지점의 효과는 반복하지 않습니다. "
            "복구 수와 연출은 점수·키 콤보·폭탄 해체 판정에 영향을 주지 않습니다."
        )
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(560)
        self.animation.valueChanged.connect(self._animate)
        self.hide()

    def _animate(self, value: float) -> None:
        self._pulse = value
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(520, 42)

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.stop_effects()

    def set_progress(self, snapshot: FreeRepairSnapshot) -> None:
        previous = self.snapshot
        self.snapshot = snapshot
        new_events = tuple(
            event for event in snapshot.events if event.id not in self._seen
        )
        self._seen.update(event.id for event in snapshot.events)
        if new_events:
            self._batch_size = len(new_events)
            self.stop_effects()
            if self.settings.effects and not self.settings.reduced_motion:
                self._pulse = 0.0
                self.animation.start()
        elif previous is not None and snapshot.solved < previous.solved:
            self._batch_size = 0
            self.stop_effects()
        if snapshot.remaining_changes == 0:
            self.message = "문서 일치 · Normal 모드에서 마무리"
        elif snapshot.solved == snapshot.total and snapshot.total:
            self.message = (
                f"남은 문서 차이 {snapshot.remaining_changes}곳 · 원래 지점 복구"
            )
        elif self._batch_size > 1:
            self.message = (
                f"{self._batch_size}곳 동시 복구! · 누적 {snapshot.first_solved}곳"
            )
        elif new_events or self._batch_size:
            self.message = f"복구 성공! · 누적 {snapshot.first_solved}곳"
        else:
            self.message = f"남은 문서 차이 {snapshot.remaining_changes}곳"
        self.setAccessibleName(
            f"자유 복구 {snapshot.solved}/{snapshot.total}곳 · "
            f"최초 복구 누적 {snapshot.first_solved}곳 · {self.message}"
        )
        self.show()
        self.update()

    def stop_effects(self) -> None:
        self.animation.stop()
        self._pulse = 1.0
        self.update()

    def clear(self) -> None:
        self.stop_effects()
        self.snapshot = None
        self._seen.clear()
        self._batch_size = 0
        self.message = ""
        self.setAccessibleName("")
        self.hide()

    def hideEvent(self, event: QHideEvent) -> None:
        self.stop_effects()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        level = chain_level(snapshot.first_solved) if self.settings.effects else 0
        tint = QColor(("#bff5d1", "#a7ecf5", "#ffe1a1", "#d9c0ff")[level])
        painter.setPen(QPen(tint.darker(210), 1))
        painter.setBrush(QColor("#1a2d31"))
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8
        )
        painter.setClipRect(QRectF(self.rect()).adjusted(8, 1, -8, -1))
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSizeF(9)
        painter.setFont(title_font)
        painter.setPen(tint)
        title = f"자유 복구 · {snapshot.solved}/{snapshot.total}곳"
        title_width = painter.fontMetrics().horizontalAdvance(title) + 18
        painter.drawText(
            QRectF(12, 4, title_width, 21), Qt.AlignmentFlag.AlignVCenter, title
        )
        detail_font = QFont(self.font())
        detail_font.setPointSizeF(8.5)
        painter.setFont(detail_font)
        painter.setPen(QColor("#c0d1cb"))
        available = max(0, self.width() - title_width - 36)
        detail = painter.fontMetrics().elidedText(
            self.message, Qt.TextElideMode.ElideRight, available
        )
        painter.drawText(
            QRectF(title_width + 16, 4, available, 21),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            detail,
        )
        track = QRectF(13, 31, max(0, self.width() - 26), 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#34484a"))
        painter.drawRoundedRect(track, 1.5, 1.5)
        ratio = snapshot.solved / snapshot.total if snapshot.total else 0
        filled = QRectF(track)
        filled.setWidth(track.width() * ratio)
        painter.setBrush(tint)
        painter.drawRoundedRect(filled, 1.5, 1.5)
        # 작은 문제는 복구 수를 구슬로, 긴 문제는 막대로 표시한다.
        if 0 < snapshot.total <= 24:
            spacing = track.width() / max(1, snapshot.total - 1)
            for index in range(snapshot.total):
                center = QPointF(
                    track.center().x()
                    if snapshot.total == 1
                    else track.left() + index * spacing,
                    track.center().y(),
                )
                painter.setBrush(tint if index < snapshot.solved else QColor("#52635f"))
                painter.drawEllipse(center, 2.5, 2.5)
        if (
            self._pulse < 1
            and self.settings.effects
            and not self.settings.reduced_motion
            and snapshot.solved
        ):
            bounce = math.sin(self._pulse * math.pi)
            center = QPointF(filled.right(), track.center().y())
            ring = QColor(tint)
            ring.setAlphaF(0.7 * bounce)
            painter.setPen(QPen(ring, 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 3 + 9 * bounce, 3 + 4 * bounce)
