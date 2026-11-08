"""개인 기록 비교의 수동 상태 표시. 입력·시간·문서를 변경하지 않는다."""

# Third party imports
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QSizePolicy, QWidget

# Local imports
from vim_key_trainer.services.challenge_rival import (
    ChallengeRival,
    RivalProgress,
    rival_for_session,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import ResultRepository
from vim_key_trainer.ui.components import label


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
        self.reference_progress = QProgressBar()
        self.reference_progress.setRange(0, 1000)
        self.reference_progress.setValue(0)
        self.reference_progress.setTextVisible(False)
        self.reference_progress.setFixedSize(72, 5)
        self.reference_progress.setAccessibleName("개인 기록의 구간 진행")
        self.reference_progress.setStyleSheet(
            "QProgressBar { background: #2b3a44; border: 0; border-radius: 2px; }"
            " QProgressBar::chunk { background: #a79bd4; border-radius: 2px; }"
        )
        row.addWidget(self.reference_progress)

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
        self.reference_progress.setValue(
            round(progress.reference_progress * 1000) if progress else 0
        )
        self.setToolTip(
            (
                f"정산 구간 {progress.completed_segments}/{progress.total_segments} · "
                f"이번 누적 {progress.checkpoint_seconds:.1f}초 · "
                f"개인 기록 누적 {progress.reference_checkpoint_seconds:.1f}초. "
                "보라색 막대는 같은 활성 시간에서 개인 기록의 진행입니다."
            )
            if progress
            else "문제·난이도·자동 수정·힌트·단계 복귀·일시정지 조건이 같은 "
            "전체 클리어 기록의 구간별 요약 시간만 비교합니다."
        )
