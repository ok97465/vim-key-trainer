"""문서를 가리지 않는 폭탄 상태 줄. 서비스 상태를 읽기만 하는 연출 계층."""

# Standard library imports
import math

# Third party imports
from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.domain.preferences import AppearanceSettings, PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.ui.challenge_audio import ChallengeAudio
from vim_key_trainer.ui.components import label
from vim_key_trainer.ui.game_resources import game_resource_path


class _Mascot(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(50, 50)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        try:
            self._pixmap = QPixmap(game_resource_path("bomb-mascot.png"))
        except (OSError, ValueError):
            self._pixmap = QPixmap()
        self.progress = 1.0
        self.verdict = ""
        self.reduced_motion = False
        self.appearance = AppearanceSettings()
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(560)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._animate)

    def configure_appearance(self, settings: AppearanceSettings) -> None:
        self.appearance = settings
        try:
            self._pixmap = QPixmap(
                game_resource_path(
                    "cat-mascot.png" if settings.mascot == "cat" else "bomb-mascot.png"
                )
            )
        except (OSError, ValueError):
            self._pixmap = QPixmap()
        self.setVisible(settings.decorations)
        self.update()

    def _animate(self, value: float) -> None:
        self.progress = value
        self.update()

    def celebrate(self, verdict: str, reduced_motion: bool) -> None:
        self.animation.stop()
        self.verdict = verdict
        self.reduced_motion = reduced_motion
        self.progress = 1.0
        if not reduced_motion:
            self.animation.start()
        self.update()

    def stop(self) -> None:
        self.animation.stop()
        self.progress = 1.0
        self.verdict = ""
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(self.width() / 62, self.height() / 62)
        phase = self.progress
        bounce = 0.0 if self.reduced_motion else 3.5 * math.sin(phase * math.pi)
        painter.drawPixmap(
            QRectF(5, 3 - bounce, 52, 55), self._pixmap, QRectF(self._pixmap.rect())
        )
        if self.verdict:
            success = self.verdict == "direct"
            tint = QColor("#bff5d1" if success else "#ffb9a5")
            if phase < 1 and not self.reduced_motion:
                for index in range(8):
                    angle = index * math.tau / 8 - math.pi / 2
                    radius = 17 + 20 * phase
                    point = QPointF(
                        31 + math.cos(angle) * radius, 31 + math.sin(angle) * radius
                    )
                    tint.setAlphaF(1 - phase)
                    painter.setPen(
                        QPen(tint, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                    )
                    if success:
                        painter.drawLine(point - QPointF(2, 0), point + QPointF(2, 0))
                        painter.drawLine(point - QPointF(0, 2), point + QPointF(0, 2))
                    else:
                        painter.drawEllipse(point, 1.5, 2.5)
            tint.setAlpha(255)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            if success and self.appearance.stamp == "star":
                star = QPainterPath()
                for index in range(10):
                    angle = index * math.pi / 5 - math.pi / 2
                    radius = 10 if index % 2 == 0 else 6.5
                    point = QPointF(
                        52 + math.cos(angle) * radius, 48 + math.sin(angle) * radius
                    )
                    if index:
                        star.lineTo(point)
                    else:
                        star.moveTo(point)
                star.closeSubpath()
                painter.drawPath(star)
            elif success and self.appearance.stamp == "flower":
                for index in range(5):
                    angle = index * math.tau / 5 - math.pi / 2
                    painter.drawEllipse(
                        QPointF(52 + 5 * math.cos(angle), 48 + 5 * math.sin(angle)),
                        5,
                        5,
                    )
            else:
                painter.drawEllipse(QRectF(43, 39, 18, 18))
            painter.setPen(
                QPen(
                    QColor("#172a26"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap
                )
            )
            if success:
                path = QPainterPath(QPointF(47, 48))
                path.lineTo(51, 52)
                path.lineTo(57, 45)
                painter.drawPath(path)
            else:
                painter.drawLine(52, 43, 52, 49)
                painter.drawPoint(52, 53)


class _Fuse(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.ratio = 1.0
        self.spark = False
        self.color = "mint"
        self.setMinimumHeight(10)
        self.setMaximumHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 3, self.width(), 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2b3a44"))
        painter.drawRoundedRect(track, 2, 2)
        fill = QRectF(track)
        fill.setWidth(max(0, track.width() * self.ratio))
        gradient = QLinearGradient(0, 0, self.width(), 0)
        color = {"mint": "#74cca7", "peach": "#eeaf99", "lilac": "#c1ade9"}[self.color]
        gradient.setColorAt(0, QColor(color))
        gradient.setColorAt(1, QColor("#e9d898" if self.ratio > 0.25 else "#f5af9b"))
        painter.setBrush(gradient)
        painter.drawRoundedRect(fill, 2, 2)
        if self.spark and self.ratio > 0:
            painter.setBrush(QColor("#ffe4a2"))
            painter.drawEllipse(QPointF(min(self.width() - 3.0, fill.right()), 5), 3, 3)


class ChallengeStatus(QFrame):
    """상태 줄 연출은 점수·시간·입력·엔진을 변경하지 않는다."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("challengeStatus")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QFrame#challengeStatus { background: #1b2b30; border: 1px solid #35554e;"
            " border-radius: 12px; }"
        )
        self.settings = PresentationSettings()
        self.appearance = AppearanceSettings()
        self.audio = ChallengeAudio(self)
        self._attempt_id: str | None = None
        self._seen_results: set[str] = set()
        self._last_tick: tuple[str, int] | None = None
        self._session: EditingSession | None = None
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 16, 2)
        row.setSpacing(12)
        self.mascot = _Mascot(self)
        row.addWidget(self.mascot)
        middle = QVBoxLayout()
        middle.setSpacing(0)
        self.title = label("폭탄 도전", "eyebrow")
        self.detail = label("첫 입력부터 시작", wrap=True)
        self.detail.setAccessibleName("폭탄 구간과 판정")
        middle.addWidget(self.title)
        middle.addWidget(self.detail)
        self.fuse = _Fuse(self)
        middle.addWidget(self.fuse)
        row.addLayout(middle, 1)
        self.countdown: QLabel = label("—", "metric")
        self.countdown.setMinimumWidth(82)
        self.countdown.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.countdown.setAccessibleName("폭탄 남은 시간")
        row.addWidget(self.countdown)
        self.setToolTip(
            "이동·검색·수정·Esc까지 한 구간입니다. 기준 풀이는 최단 보장이 없는 "
            "시간 산정 기준이며, 오타를 입력해도 제한시간은 늘어나지 않습니다."
        )
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(620, max(56, self.fontMetrics().height() * 3 + 4))

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.audio.configure(settings)
        self.mascot.stop()
        if self._session is not None:
            self.set_session(self._session)

    def configure_appearance(self, settings: AppearanceSettings) -> None:
        self.appearance = settings
        self.mascot.configure_appearance(settings)
        self.fuse.color = settings.fuse
        self.fuse.update()

    def stop_effects(self) -> None:
        self.mascot.stop()
        self.audio.stop()
        self.fuse.spark = False
        self.fuse.update()

    def set_session(self, session: EditingSession | None) -> None:
        self._session = session
        enabled = session is not None and session.bomb_enabled
        self.setVisible(enabled)
        if session is None or not enabled:
            self.stop_effects()
            return
        if self._attempt_id != session.attempt_id:
            self.stop_effects()
            self._attempt_id = session.attempt_id
            self._seen_results.clear()
            self._last_tick = None
        count = len(session.segments)
        active_index = session.active_segment_index
        index = min(active_index + 1, count) if active_index is not None else count
        active = session.state == SessionState.RUNNING
        paused = session.state == SessionState.PAUSED
        self.title.setText(
            ("일시정지" if paused else "폭탄 도전") + f" · 구간 {index} / {count}"
        )
        chain = f" · 연속 해체 {session.chain}" if session.chain else ""
        self.detail.setText(
            f"직접 해결 {session.direct_count} · 시간 초과 {session.timeout_count}"
            f" · 자동 복구 {session.auto_repair_count}{chain}"
        )
        remaining = session.remaining_seconds
        self.countdown.setText(
            "멈춤"
            if paused
            else "직접 마무리"
            if remaining is None and session.timeout_count
            else "준비"
            if remaining is None
            else f"{max(0, remaining):.1f}초"
        )
        self.countdown.setStyleSheet(
            "color: #ffb9a5;"
            if remaining is not None and remaining <= 3
            else "color: #dcf5e6;"
        )
        limit = session.segment_limit_seconds
        self.fuse.ratio = (
            min(1.0, max(0.0, remaining / limit))
            if remaining is not None and limit
            else 1.0
        )
        self.fuse.spark = (
            active and self.settings.effects and not self.settings.reduced_motion
        )
        self.fuse.update()
        for result in session.segment_results:
            if result.verdict == "pending" or result.segment_id in self._seen_results:
                continue
            self._seen_results.add(result.segment_id)
            if active:
                if self.settings.effects:
                    self.mascot.celebrate(result.verdict, self.settings.reduced_motion)
                self.audio.play("success" if result.verdict == "direct" else "timeout")
        if remaining is not None and active:
            tick = (str(session.active_segment_index), math.ceil(remaining))
            if 0 < tick[1] <= 3 and tick != self._last_tick:
                self.audio.play("countdown")
            self._last_tick = tick
        if session.state in {
            SessionState.PAUSED,
            SessionState.ABORTED,
            SessionState.READY,
        }:
            self.stop_effects()
        self.setAccessibleName(
            self.title.text()
            + " · "
            + self.detail.text()
            + " · "
            + self.countdown.text()
        )

    def hideEvent(self, event: QHideEvent) -> None:
        self.stop_effects()
        super().hideEvent(event)
