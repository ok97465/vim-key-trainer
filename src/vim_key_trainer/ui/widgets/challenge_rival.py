"""개인 기록 비교의 수동 상태 표시. 입력·시간·문서를 변경하지 않는다."""

# Third party imports
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

# Local imports
from vim_key_trainer.services.challenge_rival import (
    ChallengeRival,
    RivalProgress,
    rival_for_session,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import ResultRepository
from vim_key_trainer.ui.components import label


class _RaceTrack(QWidget):
    """내 정산 진도와 같은 활성 시간의 최고 기록 진도를 나란히 그린다."""

    def __init__(self) -> None:
        super().__init__()
        self.progress: RivalProgress | None = None
        self.setMinimumWidth(140)
        self.setMaximumWidth(260)
        self.setFixedHeight(34)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("내 해체 진도와 최고 기록의 두 주자 트랙")

    def sizeHint(self) -> QSize:
        return QSize(210, 34)

    def set_progress(self, progress: RivalProgress | None) -> None:
        self.progress = progress
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        progress = self.progress
        own = (
            progress.completed_segments / max(1, progress.total_segments)
            if progress is not None
            else 0.0
        )
        reference = progress.reference_progress if progress is not None else 0.0
        if progress is None or not progress.eligible:
            painter.setOpacity(0.38)
        start, finish = 54.0, self.width() - 9.0
        for y, caption, ratio, color in (
            (9.0, "내 해체", own, "#91e6bc"),
            (26.0, "최고 기록", reference, "#b9a4ee"),
        ):
            painter.setPen(QColor(color))
            font = painter.font()
            font.setPointSizeF(8)
            painter.setFont(font)
            painter.drawText(
                QRectF(0, y - 8, 50, 16), Qt.AlignmentFlag.AlignVCenter, caption
            )
            painter.setPen(QPen(QColor("#3b4b53"), 2))
            painter.drawLine(QPointF(start, y), QPointF(finish, y))
            painter.setPen(QPen(QColor(color), 2.5))
            x = start + (finish - start) * min(1.0, max(0.0, ratio))
            painter.drawLine(QPointF(start, y), QPointF(x, y))
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x, y), 4, 4)
            painter.setPen(QPen(QColor("#e2e9e0"), 1))
            painter.drawLine(QPointF(finish, y - 5), QPointF(finish, y + 5))


class ChallengeRivalStatus(QWidget):
    def __init__(
        self, repository: ResultRepository, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._selection: tuple[str, int, int, bool] | None = None
        self._rival: ChallengeRival | None = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.message = label("개인 기록 대결 꺼짐", "muted")
        self.message.setMinimumWidth(190)
        row.addWidget(self.message, 1)
        self.race_track = _RaceTrack()
        row.addWidget(self.race_track, 1)

    def set_session(
        self,
        session: EditingSession | None,
        *,
        enabled: bool,
    ) -> None:
        visible = session is not None and session.bomb_enabled
        self.setVisible(visible)
        if session is None or not visible:
            self._selection = None
            self._rival = None
            return
        selection = (
            session.attempt_id,
            session.extra_hints,
            session.step_returns,
            session.pause_count > 0,
        )
        if enabled and selection != self._selection:
            self._rival = rival_for_session(session, self.repository.results)
            self._selection = selection
        self.set_progress(
            self._rival.progress(session) if enabled and self._rival else None,
            enabled=enabled,
        )

    def set_progress(self, progress: RivalProgress | None, *, enabled: bool) -> None:
        if not enabled:
            text = "개인 기록 대결 꺼짐"
        elif progress is None:
            text = "같은 조건의 클리어 기록 없음"
        elif not progress.eligible:
            text = "시간 초과 · 기록 대결 종료"
        elif progress.delta_seconds is None:
            text = "개인 기록과 나란히 시작"
        elif abs(progress.delta_seconds) < 0.05:
            text = "개인 기록과 같은 페이스"
        else:
            pace = "빠름" if progress.delta_seconds < 0 else "늦음"
            text = f"개인 기록보다 {abs(progress.delta_seconds):.1f}초 {pace}"
        self.message.setText(text)
        self.setAccessibleName(text)
        self.race_track.set_progress(progress)
        self.setToolTip(
            (
                f"정산 구간 {progress.completed_segments}/{progress.total_segments} · "
                f"이번 누적 {progress.checkpoint_seconds:.1f}초 · "
                f"개인 기록 누적 {progress.reference_checkpoint_seconds:.1f}초. "
                "민트 주자는 직접 정산한 구간 진도, 보라색 주자는 같은 활성 "
                "시간에서 최고 기록의 구간별 요약 진도입니다."
            )
            if progress
            else "문제·난이도·자동 수정·힌트·단계 복귀·일시정지 조건이 같은 "
            "전체 클리어 기록의 구간별 요약 시간만 비교합니다."
        )
