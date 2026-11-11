"""결과 화면에서 이어지는 해체 잔향과 점수 연출. 결과 자체는 읽기만 한다."""

# Standard library imports
import math

# Third party imports
from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import (
    QColor,
    QFont,
    QHideEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

# Local imports
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import EditingSessionResult, SessionState
from vim_key_trainer.ui.challenge_feedback import is_close_call


class ChallengeFinale(QWidget):
    """입력을 받거나 결과 화면 전환을 기다리지 않는 장식 카드."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = PresentationSettings()
        self.result: EditingSessionResult | None = None
        self.progress = 1.0
        self.setMinimumHeight(132)
        self.setMaximumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(1600)
        self.animation.valueChanged.connect(self._animate)
        self.hide()

    def _animate(self, value: float) -> None:
        self.progress = value
        self.update()

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.stop_effects()
        self.setVisible(settings.effects and self.result is not None)

    def present(self, result: EditingSessionResult) -> None:
        self.stop_effects()
        completed_free = (
            result.mode == "free" and result.state == SessionState.COMPLETED
        )
        self.result = result if result.challenge is not None or completed_free else None
        self.setVisible(self.settings.effects and self.result is not None)
        challenge = result.challenge
        if self.result is None:
            return
        expired_free = self._expired_free()
        if challenge is not None and not expired_free:
            summary = (
                f"해체 점수 {challenge.score:,}점 · "
                f"최고 연속 해체 {challenge.max_chain}"
            )
        else:
            summary = (
                f"입력 {result.key_count}/{result.baseline_keys}회 · "
                f"{result.elapsed_seconds:.1f}초"
            )
        self.setAccessibleName(f"{self._caption()} · {summary}")
        if (
            self.settings.effects
            and not self.settings.reduced_motion
            and not expired_free
        ):
            self.progress = 0.0
            self.animation.start()
        self.update()

    def clear(self) -> None:
        self.stop_effects()
        self.result = None
        self.hide()

    def stop_effects(self) -> None:
        self.animation.stop()
        self.progress = 1.0
        self.update()

    def hideEvent(self, event: QHideEvent) -> None:
        self.stop_effects()
        super().hideEvent(event)

    def _caption(self) -> str:
        challenge = self.result.challenge if self.result is not None else None
        if challenge is None:
            return "자유 복구 완료!" if self.result is not None else ""
        if self._expired_free():
            return "자유 복구 완료 · 제한시간 초과"
        if challenge.full_clear:
            caption = "복수 성공!" if challenge.revenge_of else "전 구간 해체 완료!"
            if challenge.segments and is_close_call(challenge.segments[-1]):
                caption = "간발의 해체! · " + caption
            return caption
        return "이번 도전 정산 · 놓친 구간은 복수전으로"

    def _expired_free(self) -> bool:
        result = self.result
        return bool(
            result is not None
            and result.mode == "free"
            and result.challenge is not None
            and result.challenge.timeout_count
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        result = self.result
        if result is None:
            return
        challenge = result.challenge
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        success = challenge is None or challenge.full_clear
        expired_free = self._expired_free()
        tint = QColor("#9ee5bb" if success else "#eeb99a")
        background = QLinearGradient(box.topLeft(), box.bottomRight())
        background.setColorAt(0, QColor("#203e36" if success else "#3d302b"))
        background.setColorAt(1, QColor("#17252e"))
        painter.setBrush(background)
        painter.setPen(QPen(tint.darker(180), 1))
        painter.drawRoundedRect(box, 14, 14)
        painter.setClipRect(box.adjusted(2, 2, -2, -2))
        phase = self.progress
        center = QPointF(self.width() * 0.5, self.height() * 0.5)
        if phase < 1 and not self.settings.reduced_motion:
            for index in range(22 if success else 8):
                angle = index * 2.39996
                distance = (30 + (index % 5) * 16) + phase * self.width() * 0.45
                position = center + QPointF(
                    math.cos(angle) * distance,
                    math.sin(angle) * distance * 0.3 + 35 * phase**2,
                )
                color = QColor(("#bff5d1", "#f1d383", "#c5b2f2")[index % 3])
                color.setAlphaF(max(0.0, (1 - phase) * 0.85))
                painter.setPen(QPen(color, 2.5))
                painter.drawLine(position, position + QPointF(4, -4))
            if phase < 0.22:
                slash = min(1.0, phase / 0.07)
                path = QPainterPath(QPointF(20, self.height() - 18))
                path.lineTo(QPointF(20 + (self.width() - 40) * slash, 20))
                painter.setPen(QPen(QColor("#e9ffe9"), 3 * (1 - phase / 0.22)))
                painter.drawPath(path)
        painter.setPen(tint)
        caption_font = QFont(self.font())
        caption_font.setPointSize(12)
        caption_font.setBold(True)
        painter.setFont(caption_font)
        painter.drawText(
            QRectF(16, 18, self.width() - 32, 25),
            Qt.AlignmentFlag.AlignCenter,
            self._caption(),
        )
        tally = 1 - (1 - min(1.0, phase / 0.75)) ** 3
        if challenge is not None and not expired_free:
            score = f"{round(challenge.score * tally):,} 점"
            detail = (
                f"직접 해체 {challenge.direct_count}곳  ·  "
                f"최고 연속 {challenge.max_chain}회"
            )
        else:
            score = (
                "복구 완료"
                if expired_free
                else "★" * result.stars + "☆" * (3 - result.stars)
            )
            detail = (
                f"입력 {result.key_count}회 / 기준 {result.baseline_keys}회  ·  "
                f"{result.elapsed_seconds:.1f}초"
            )
        score_font = QFont(self.font())
        score_font.setPointSize(27)
        score_font.setBold(True)
        painter.setFont(score_font)
        painter.setPen(QColor("#f3f1dc"))
        painter.drawText(
            QRectF(16, 48, self.width() - 32, 48),
            Qt.AlignmentFlag.AlignCenter,
            score,
        )
        painter.setFont(self.font())
        painter.setPen(QColor("#c5d6ce"))
        painter.drawText(
            QRectF(16, 102, self.width() - 32, 21),
            Qt.AlignmentFlag.AlignCenter,
            detail,
        )
