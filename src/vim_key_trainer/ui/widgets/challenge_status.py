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
    QTimer,
    QVariantAnimation,
    Signal,
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
from vim_key_trainer.ui.challenge_feedback import (
    chain_level,
    is_close_call,
    segment_technique,
)
from vim_key_trainer.ui.components import label
from vim_key_trainer.ui.game_resources import game_resource_path


class _Mascot(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(50, 50)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pixmap = QPixmap(game_resource_path("bomb-mascot.png"))
        self.progress = 1.0
        self.verdict = ""
        self.expired = False
        self.reduced_motion = False
        self.appearance = AppearanceSettings()
        self.pressure = 0.0
        self.motion_phase = 0.0
        self.boss_progress: float | None = None
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(560)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._animate)

    def configure_appearance(self, settings: AppearanceSettings) -> None:
        self.appearance = settings
        self._pixmap = QPixmap(
            game_resource_path(
                "cat-mascot.png" if settings.mascot == "cat" else "bomb-mascot.png"
            )
        )
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
        if not reduced_motion and not self.isHidden():
            self.animation.start()
        self.update()

    def stop(self) -> None:
        self.animation.stop()
        self.progress = 1.0
        self.verdict = ""
        self.expired = False
        self.update()

    def hideEvent(self, event: QHideEvent) -> None:
        self.stop()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(self.width() / 62, self.height() / 62)
        phase = self.progress
        bounce = 0.0 if self.reduced_motion else 3.5 * math.sin(phase * math.pi)
        jitter = (
            0.0
            if self.reduced_motion
            else math.sin(self.motion_phase * 5) * self.pressure * 1.5
        )
        painter.drawPixmap(
            QRectF(5 + jitter, 3 - bounce, 52, 55),
            self._pixmap,
            QRectF(self._pixmap.rect()),
        )
        if self.expired:
            # 시간은 끝났어도 문서는 계속 고칠 수 있다. 처진 눈썹과 시계만 남긴다.
            painter.setPen(
                QPen(
                    QColor("#d6d1bc"),
                    1.7,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(QPointF(22, 28), QPointF(27, 30))
            painter.drawLine(QPointF(35, 30), QPointF(40, 28))
            painter.setBrush(QColor("#d9d0ac"))
            painter.setPen(QPen(QColor("#8f957f"), 1.2))
            painter.drawEllipse(QPointF(51, 48), 9, 9)
            painter.setPen(
                QPen(
                    QColor("#344442"),
                    1.8,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(QPointF(51, 48), QPointF(51, 42))
            painter.drawLine(QPointF(51, 48), QPointF(55, 50))
            return
        if self.pressure > 0:
            # 캐릭터 위의 눈썹과 땀방울만 움직인다. 문서와 커서는 고정한다.
            painter.setPen(QPen(QColor("#fff1cf"), 1.8))
            for x in (24.0, 37.0):
                painter.drawArc(
                    QRectF(x - 4, 23 - self.pressure * 3, 8, 6), 0, 180 * 16
                )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#9cdef0"))
            painter.drawEllipse(QPointF(47 + jitter, 25), 1.7, 3.5)
        if self.boss_progress is not None:
            damage = self.boss_progress
            painter.setPen(QPen(QColor("#f4ce99"), 1.6))
            for index in range(round(damage * 5)):
                start = QPointF(18 + index * 7, 17 + index % 2 * 9)
                crack = QPainterPath(start)
                crack.lineTo(start + QPointF(4, 5))
                crack.lineTo(start + QPointF(1, 9))
                crack.lineTo(start + QPointF(6, 13))
                painter.drawPath(crack)
            if phase < 1 and not self.reduced_motion:
                painter.setBrush(QColor("#d8b28c"))
                for index in range(3):
                    painter.drawRect(QRectF(15 + index * 13, 25 + phase * 30, 3, 4))
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
        self.pressure = 0.0
        self.motion_phase = 0.0
        self.setFixedHeight(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(3, 4, self.width() - 6, 4)
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
            point = QPointF(min(self.width() - 3.0, fill.right()), 6)
            glow = QColor("#ffc36e")
            glow.setAlpha(45 + round(45 * (1 + math.sin(self.motion_phase))))
            painter.setBrush(glow)
            painter.drawEllipse(point, 8 + self.pressure * 3, 6)
            painter.setBrush(QColor("#ffe4a2"))
            painter.drawEllipse(point, 3, 3)
            painter.setPen(QPen(QColor("#ffe4a2"), 1.3))
            for index in range(3):
                angle = self.motion_phase + index * math.tau / 3
                painter.drawLine(
                    point + QPointF(math.cos(angle) * 5, math.sin(angle) * 3),
                    point + QPointF(math.cos(angle) * 9, math.sin(angle) * 5),
                )
        # 왼쪽 폭탄 쪽으로 불꽃이 다가온다는 방향을 고정해 보여 준다.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f5af9b" if self.pressure > 0.6 else "#a2b7ad"))
        painter.drawEllipse(QPointF(3, 6), 2.5, 2.5)


class ChallengeStatus(QFrame):
    """상태 줄 연출은 점수·시간·입력·엔진을 변경하지 않는다."""

    pressure_changed = Signal(float)

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
        self._session: EditingSession | None = None
        self.pressure = 0.0
        self.motion_phase = 0.0
        self.motion_timer = QTimer(self)
        self.motion_timer.setInterval(33)
        self.motion_timer.timeout.connect(self._advance_motion)
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
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.addWidget(self.title, 1)
        self.chain_badge = label("", "eyebrow")
        self.chain_badge.hide()
        heading.addWidget(self.chain_badge)
        middle.addLayout(heading)
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
        self.mascot.reduced_motion = settings.reduced_motion
        if self._session is not None:
            self.set_session(self._session)

    def configure_appearance(self, settings: AppearanceSettings) -> None:
        self.appearance = settings
        self.mascot.configure_appearance(settings)
        self.fuse.color = settings.fuse
        self.fuse.update()

    def stop_effects(self) -> None:
        self.motion_timer.stop()
        self.mascot.stop()
        self.mascot.pressure = 0.0
        self.audio.stop()
        self.fuse.spark = False
        self._set_pressure(0.0)
        self.fuse.update()

    def _set_pressure(self, pressure: float) -> None:
        if self.pressure != pressure:
            self.pressure = pressure
            self.pressure_changed.emit(pressure)
        self.update()

    def _advance_motion(self) -> None:
        self.motion_phase += 0.12 + self.pressure * 0.22
        self.mascot.motion_phase = self.motion_phase
        self.fuse.motion_phase = self.motion_phase
        self.mascot.update()
        self.fuse.update()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.pressure:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pulse = (
            0.5
            if self.settings.reduced_motion
            else (1 + math.sin(self.motion_phase)) / 2
        )
        tint = QColor("#f28c79" if self.pressure > 0.6 else "#efc47f")
        tint.setAlpha(round(75 + 120 * pulse * self.pressure))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(tint, 1.5 + self.pressure * pulse))
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5), 11, 11
        )

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
        count = len(session.segments)
        active_index = session.active_segment_index
        index = min(active_index + 1, count) if active_index is not None else count
        active = session.state == SessionState.RUNNING
        paused = session.state == SessionState.PAUSED
        free = session.mode == "free"
        free_expired = free and session.timeout_count > 0
        boss = (
            session.lesson.activity is not None
            and session.lesson.activity.kind == "boss"
        )
        settled = sum(result.verdict != "pending" for result in session.segment_results)
        boss_stage = min(3, 1 + settled * 3 // max(1, count))
        if free:
            if paused:
                title = "일시정지 · 자유 풀이"
            elif free_expired:
                title = "시간 종료 · 자유 풀이"
            else:
                title = "자유 풀이 · 문서 전체 타이머"
            detail = (
                "시간 초과 · 계속 고쳐서 마무리하세요"
                if free_expired
                else "문서 전체 제한시간 · 원하는 순서로 복구하세요"
            )
        else:
            title = "일시정지" if paused else "보스 문서" if boss else "폭탄 도전"
            if boss:
                title += f" · 단계 {boss_stage}/3"
            title += f" · 구간 {index} / {count}"
            detail = (
                f"직접 해결 {session.direct_count} · 시간 초과 {session.timeout_count}"
                f" · 자동 복구 {session.auto_repair_count}"
            )
            if session.chain:
                detail += f" · 연속 해체 {session.chain}"
        self.title.setText(title)
        self.detail.setText(detail)
        self.setToolTip(
            "자유 풀이는 문서 전체에 제한시간 하나를 사용합니다. "
            "시간이 끝나도 계속 연습할 수 있으며 시간 초과 판정은 유지합니다."
            if free
            else "이동·검색·수정·Esc까지 한 구간입니다. 기준 풀이는 최단 보장이 없는 "
            "시간 산정 기준이며, 오타를 입력해도 제한시간은 늘어나지 않습니다."
        )
        remaining = session.remaining_seconds
        if paused:
            countdown = "멈춤"
        elif free_expired:
            countdown = "계속 연습"
        elif remaining is None:
            countdown = "직접 마무리" if session.timeout_count else "준비"
        else:
            countdown = f"{max(0, remaining):.1f}초"
        self.countdown.setText(countdown)
        self.countdown.setStyleSheet(
            "color: #ffb9a5;"
            if remaining is not None and remaining <= 3
            else "color: #dcf5e6;"
        )
        limit = session.segment_limit_seconds
        self.fuse.ratio = (
            0.0
            if free_expired
            else min(1.0, max(0.0, remaining / limit))
            if remaining is not None and limit
            else 1.0
        )
        pressure = (
            max(0.0, min(1.0, (0.6 - self.fuse.ratio) / 0.6))
            if remaining is not None and active and self.settings.effects
            else 0.0
        )
        if (
            remaining is not None
            and remaining <= 3
            and active
            and self.settings.effects
        ):
            pressure = max(pressure, 0.8)
        self._set_pressure(pressure)
        self.mascot.pressure = pressure
        self.mascot.reduced_motion = self.settings.reduced_motion
        self.mascot.expired = free_expired and active and self.settings.effects
        self.mascot.setAccessibleName(
            "시간 종료 · 계속 연습할 수 있어요"
            if self.mascot.expired
            else "해체 도우미"
        )
        self.mascot.boss_progress = (
            settled / max(1, count) if boss and self.settings.effects else None
        )
        self.fuse.pressure = pressure
        animate = (
            active
            and not free_expired
            and self.settings.effects
            and not self.settings.reduced_motion
        )
        self.fuse.spark = animate
        if animate:
            if not self.motion_timer.isActive():
                self.motion_timer.start()
        else:
            self.motion_timer.stop()
        self.audio.set_pressure(remaining, self.fuse.ratio, active)
        level = chain_level(session.chain) if self.settings.effects else 0
        self.chain_badge.setVisible(session.chain > 0)
        self.chain_badge.setText(f"{'✦ ' * level}연속 해체 {session.chain}")
        latest = next(
            (
                item
                for item in reversed(session.segment_results)
                if item.verdict != "pending"
            ),
            None,
        )
        if self.settings.effects and latest is not None and is_close_call(latest):
            self.chain_badge.setText("간발의 해체! · " + self.chain_badge.text())
            self.chain_badge.show()
        badge_color = ("#bff5d1", "#e8d28d", "#f6bb84", "#e5b3ef")[level]
        self.chain_badge.setStyleSheet(
            f"color: {badge_color}; font-size: {11 + level}px;"
        )
        self.fuse.update()
        self.mascot.update()
        for result in session.segment_results:
            if result.verdict == "pending" or result.segment_id in self._seen_results:
                continue
            self._seen_results.add(result.segment_id)
            if active:
                if self.settings.effects and not free_expired:
                    self.mascot.celebrate(result.verdict, self.settings.reduced_motion)
                self.audio.play(
                    "success"
                    if result.verdict == "direct"
                    else "expired"
                    if free
                    else "timeout",
                    chain=session.chain,
                    technique=segment_technique(session, result.segment_id),
                    close_call=is_close_call(result),
                )
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
