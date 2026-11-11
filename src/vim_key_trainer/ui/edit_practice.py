"""긴 편집 문서의 준비·가이드/자유 풀이·결과 화면."""

# Standard library imports
from collections.abc import Callable
from dataclasses import replace
from difflib import unified_diff
from secrets import randbelow

# Third party imports
from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QHideEvent,
    QPixmap,
    QResizeEvent,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources, read_code_license
from vim_key_trainer.content.document_missions import (
    get_document_mission,
    list_document_missions,
    read_document_license,
)
from vim_key_trainer.domain.activities import BONUS_TITLES, BonusObjective
from vim_key_trainer.domain.challenge import (
    ChallengeOptions,
    TimerGuard,
    bomb_unavailable_reason,
)
from vim_key_trainer.domain.document_display import compare_documents
from vim_key_trainer.domain.document_missions import (
    DocumentMission,
    DocumentPracticeSpec,
)
from vim_key_trainer.domain.document_types import DocumentLanguage
from vim_key_trainer.domain.edit_generator import EditProfile, get_edit_profile
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.editing import (
    EditLesson,
    EditMode,
    EditPracticeSpec,
    random_edit_document_lines,
)
from vim_key_trainer.domain.preferences import AppearanceSettings, PresentationSettings
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.engine import EditorState
from vim_key_trainer.services.activity_problem_factory import create_boss_problem
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import ResultRepository
from vim_key_trainer.ui.challenge_audio import ChallengeAudio
from vim_key_trainer.ui.components import button, label, scroll_page
from vim_key_trainer.ui.game_resources import game_resource_path
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets.challenge_rival import ChallengeRivalStatus
from vim_key_trainer.ui.widgets.challenge_status import ChallengeStatus
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison
from vim_key_trainer.ui.widgets.repair_effects import RepairEffects


class EditPracticePage(QWidget):
    leave_requested = Signal()
    preferences_changed = Signal()

    def __init__(
        self,
        repository: ResultRepository,
        *,
        technique_weights: Callable[[], EditTechniqueWeights] | None = None,
        challenge: ChallengeOptions | None = None,
        presentation: PresentationSettings | None = None,
        record_rival: bool = False,
        appearance: AppearanceSettings | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self._technique_weights = technique_weights
        self.default_challenge = challenge or ChallengeOptions()
        self.presentation = presentation or PresentationSettings()
        self.record_rival_enabled = record_rival
        self.appearance = appearance or AppearanceSettings()
        self.result_audio = ChallengeAudio(self)
        self.result_audio.configure(self.presentation)
        self._timer_guard: TimerGuard | None = None
        self._guide_goal_positions: dict[int, tuple[int, int] | None] = {}
        self.session: EditingSession | None = None
        self.last_result: EditingSessionResult | None = None
        self._switching = False
        self._started = False
        self._return_spec: EditPracticeSpec | None = None
        self._source_dialog: QDialog | None = None
        self._mission: DocumentMission | None = None
        self._random_documents = False
        self._documents = list_document_missions()
        try:
            self._code_sources = load_code_sources()
        except (ValueError, OSError):
            self._code_sources = ()
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        root.addWidget(self.stack)
        self.practice_page = self._make_practice_page()
        self.result_page = self._make_result_page()
        self.stack.addWidget(self.practice_page)
        self.stack.addWidget(self.result_page)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

    def _make_practice_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(4)
        self.title = label("문서 수정 연습", "sectionTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.title)
        self.description = label("", "muted", wrap=True)
        self.description.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.description.setMaximumHeight(32)
        layout.addWidget(self.description)
        self.code_source_summary = label("", "muted", wrap=True)
        self.code_source_summary.setAccessibleName("코드 원문 출처")
        self.code_source_summary.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.code_source_summary.setMaximumHeight(32)
        self.code_source_summary.hide()
        layout.addWidget(self.code_source_summary)
        self.mission_progress = label("", "eyebrow", wrap=True)
        self.mission_progress.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.mission_progress.setToolTip(
            "목표 강조: 노랑은 교체, 파랑은 추가, 분홍은 삭제 위치입니다. "
            "밑줄과 줄 옆 표식도 함께 표시합니다."
        )
        layout.addWidget(self.mission_progress)
        layout.addLayout(self._make_options())
        layout.addWidget(self._make_challenge_options())
        layout.addWidget(self._make_activity_options())
        self.challenge_status = ChallengeStatus()
        self.challenge_status.configure_effects(self.presentation)
        self.challenge_status.configure_appearance(self.appearance)
        self.challenge_status.hide()
        layout.addWidget(self.challenge_status)
        self.comparison = EditComparison()
        self.repair_effects = RepairEffects(self.comparison)
        self.repair_effects.configure_effects(self.presentation)
        self.practice_input = self.comparison.practice_input
        self.practice_input.set_yank_enabled(self.presentation.effects)
        self.goal_document = self.comparison.goal_document
        self.document_scroll = self.comparison.current_scroll
        self.practice_input.key_received.connect(self._receive_key)
        self.practice_input.focus_lost.connect(self._focus_lost)
        self.practice_input.composition_blocked.connect(self._composition_blocked)
        layout.addWidget(self.comparison, 1)
        self.command_prompt = label("", "eyebrow")
        self.command_prompt.setAccessibleName("검색·Ex 명령 입력")
        self.command_prompt.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.command_prompt.hide()
        layout.addWidget(self.command_prompt)
        layout.addLayout(self._make_metrics())
        self.feedback = label("", "muted", wrap=True)
        self.feedback.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.feedback.setMinimumHeight(18)
        self.feedback.setMaximumHeight(32)
        layout.addWidget(self.feedback)
        self.action_bar = self._make_actions()
        layout.addWidget(self.action_bar)
        return page

    def _make_options(self) -> QHBoxLayout:
        options = QHBoxLayout()
        self._options_layout = options
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName("편집 풀이 방식")
        self.mode_combo.addItem("가이드 풀이", "guided")
        self.mode_combo.addItem("자유 풀이", "free")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        options.addWidget(self.mode_combo)
        self.document_combo = QComboBox()
        self.document_combo.setAccessibleName("연습 문서 선택")
        self.document_combo.setMinimumContentsLength(12)
        self.document_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.document_combo.currentIndexChanged.connect(self._document_changed)
        options.addWidget(self.document_combo, 1)
        self.length_combo = QComboBox()
        self.length_combo.setAccessibleName("편집 문서 길이")
        self.length_combo.currentIndexChanged.connect(self._length_changed)
        options.addWidget(self.length_combo)
        self.document_font_spin = QSpinBox()
        self.document_font_spin.setAccessibleName("문서 글씨 크기")
        self.document_font_spin.setRange(10, 30)
        self.document_font_spin.setValue(12)
        self.document_font_spin.setSuffix(" pt")
        self.document_font_spin.valueChanged.connect(self._font_changed)
        options.addWidget(self.document_font_spin)
        return options

    def _make_challenge_options(self) -> QWidget:
        self.challenge_options_bar = QWidget()
        row = QHBoxLayout(self.challenge_options_bar)
        row.setContentsMargins(0, 0, 0, 0)
        self.challenge_combo = QComboBox()
        self.challenge_combo.setAccessibleName("문서 수정 도전 종류")
        self.challenge_combo.addItem("일반 연습", "normal")
        self.challenge_combo.addItem("폭탄 도전", "bomb")
        self.challenge_combo.setCurrentIndex(
            self.challenge_combo.findData(self.default_challenge.kind)
        )
        self._options_layout.insertWidget(1, self.challenge_combo)
        self.difficulty_combo = QComboBox()
        self.difficulty_combo.setAccessibleName("폭탄 제한시간 난이도")
        for title, value in (
            ("여유", "relaxed"),
            ("보통", "normal"),
            ("도전", "challenge"),
        ):
            self.difficulty_combo.addItem(title, value)
        self.difficulty_combo.setCurrentIndex(
            self.difficulty_combo.findData(self.default_challenge.difficulty)
        )
        self.auto_repair_check = QCheckBox("시간 초과 자동 수정")
        self.auto_repair_check.setChecked(self.default_challenge.auto_repair)
        self.auto_repair_check.setToolTip(
            "시간 초과는 실패로 남고 검증된 구간 종료 상태로 복구합니다."
        )
        for widget in (self.difficulty_combo, self.auto_repair_check):
            row.addWidget(widget)
        self.personal_record_check = QCheckBox("기록 대결")
        self.personal_record_check.setAccessibleName("개인 기록 대결")
        self.personal_record_check.setChecked(self.record_rival_enabled)
        self.personal_record_check.toggled.connect(self._rival_changed)
        row.addWidget(self.personal_record_check)
        self.rival_status = ChallengeRivalStatus(self.repository)
        self.rival_status.message.setMinimumWidth(0)
        self.rival_status.message.setWordWrap(True)
        self.rival_status.reference_progress.setFixedWidth(40)
        row.addWidget(self.rival_status, 1)
        self.challenge_combo.currentIndexChanged.connect(self._challenge_changed)
        self.difficulty_combo.currentIndexChanged.connect(self._challenge_changed)
        self.auto_repair_check.toggled.connect(self._challenge_changed)
        return self.challenge_options_bar

    def _rival_changed(self) -> None:
        self.record_rival_enabled = self.personal_record_check.isChecked()
        self.preferences_changed.emit()
        self._refresh_metrics()
        if self._started:
            self._refocus()

    def _make_activity_options(self) -> QWidget:
        self.activity_options = QWidget()
        row = QHBoxLayout(self.activity_options)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label("선택 목표", "eyebrow"))
        self._bonus_checks: dict[BonusObjective, QCheckBox] = {}
        for objective, title in BONUS_TITLES.items():
            check = QCheckBox(title)
            check.toggled.connect(self._bonus_changed)
            self._bonus_checks[objective] = check
            row.addWidget(check)
        row.addStretch()
        self.activity_options.hide()
        return self.activity_options

    def _bonus_changed(self) -> None:
        session = self.session
        if (
            self._switching
            or session is None
            or self._started
            or session.lesson.activity is None
        ):
            return
        objectives = tuple(
            objective
            for objective, check in self._bonus_checks.items()
            if check.isChecked()
        )
        lesson = replace(
            session.lesson,
            activity=replace(session.lesson.activity, objectives=objectives),
        )
        self.prepare(lesson, session.mode, challenge=session.challenge)

    def _selected_challenge(self) -> ChallengeOptions:
        return ChallengeOptions(
            kind="bomb" if self.challenge_combo.currentData() == "bomb" else "normal",
            difficulty=(
                "relaxed"
                if self.difficulty_combo.currentData() == "relaxed"
                else "challenge"
                if self.difficulty_combo.currentData() == "challenge"
                else "normal"
            ),
            auto_repair=self.auto_repair_check.isChecked(),
        )

    def _challenge_changed(self) -> None:
        if self._switching:
            return
        self.default_challenge = self._selected_challenge()
        self.preferences_changed.emit()
        if self.session is not None and not self._started:
            lesson = self.session.lesson
            if self.default_challenge.kind == "normal" and lesson.activity is not None:
                lesson = replace(
                    lesson,
                    activity=replace(
                        lesson.activity,
                        objectives=tuple(
                            objective
                            for objective in lesson.activity.objectives
                            if objective != "all_direct"
                        ),
                    ),
                )
            self.prepare(
                lesson,
                self.session.mode,
                font_size=self.practice_input.font_size,
                challenge=self.default_challenge,
            )

    def configure_effects(self, presentation: PresentationSettings) -> None:
        self.presentation = presentation
        self.challenge_status.configure_effects(presentation)
        self.repair_effects.configure_effects(presentation)
        self.practice_input.set_yank_enabled(presentation.effects)
        self.result_audio.configure(presentation)

    def configure_appearance(self, appearance: AppearanceSettings) -> None:
        self.appearance = appearance
        self.challenge_status.configure_appearance(appearance)
        self._load_result_mascot()

    def _load_result_mascot(self) -> None:
        source = QPixmap(
            game_resource_path(
                "cat-mascot.png"
                if self.appearance.mascot == "cat"
                else "bomb-mascot.png"
            )
        )
        scale = max(2.0, self.devicePixelRatioF())
        mascot = source.scaled(
            QSize(round(112 * scale), round(112 * scale)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        mascot.setDevicePixelRatio(scale)
        self.result_mascot.setPixmap(mascot)

    def _make_metrics(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.metrics: dict[str, QLabel] = {}
        for key in ("mode", "keys", "time", "guide"):
            value = label("—", wrap=True)
            value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.metrics[key] = value
            row.addWidget(value, 2 if key == "keys" else 1)
        self.metrics["keys"].setToolTip(
            "기준 입력 횟수는 같은 조건에서 재생 검증한 효율적인 풀이의 길이입니다. "
            "더 짧은 풀이도 가능합니다."
        )
        return row

    def _make_actions(self) -> QWidget:
        bar = QWidget()
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        actions = QGridLayout(bar)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.start_button = button(
            "연습 시작", "startEditing", primary=True, enter_activates=True
        )
        self.start_button.clicked.connect(self.start_practice)
        self.pause_button = button("일시정지", "pauseEditing")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.retry_button = button("같은 문제 다시", "retryEditing")
        self.retry_button.clicked.connect(self.retry)
        self.new_problem_button = button("다른 문제", "newEditProblem")
        self.new_problem_button.clicked.connect(self.new_problem)
        self.return_button = button("단계 처음으로", "returnEditStep")
        self.return_button.clicked.connect(self.return_to_step)
        self.short_button = button("짧게 7곳 연습", "shortEditPractice")
        self.short_button.clicked.connect(self.toggle_short_practice)
        self.source_button = button("원문·라이선스", "documentSource")
        self.source_button.clicked.connect(self.show_source)
        self.leave_button = button("문서 수정 선택", "leaveEditing")
        self.leave_button.clicked.connect(self.leave_requested.emit)
        self._action_buttons = (
            self.start_button,
            self.pause_button,
            self.retry_button,
            self.new_problem_button,
            self.return_button,
            self.short_button,
            self.source_button,
            self.leave_button,
        )
        self._actions = actions
        self._actions_initialized = False
        self._reflow_actions()
        return bar

    def _reflow_actions(self) -> None:
        while self._actions.count():
            self._actions.takeAt(0)
        visible = [
            item
            for item in self._action_buttons
            if not self._actions_initialized or not item.isHidden()
        ]
        required = sum(item.minimumSizeHint().width() for item in visible)
        required += self._actions.spacing() * max(0, len(visible) - 1)
        available = self.width() - 36
        columns = (
            max(1, len(visible))
            if available >= required
            else 4
            if available >= 500
            else 2
        )
        for index, item in enumerate(visible):
            self._actions.addWidget(item, index // columns, index % columns)
        self._actions_initialized = True
        bar = self._actions.parentWidget()
        if bar is not None:
            bar.setFixedHeight(self._actions.sizeHint().height())
            bar.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_actions"):
            self._reflow_actions()
        if hasattr(self, "description"):
            compact = event.size().height() < 680
            self.description.setVisible(not compact)
            self.mission_progress.setVisible(not compact)
            if hasattr(self, "comparison"):
                self.comparison.setMinimumHeight(120 if compact else 180)
            self.code_source_summary.setVisible(
                not compact
                and self.session is not None
                and self.session.lesson.code_excerpt is not None
            )

    def hideEvent(self, event: QHideEvent) -> None:
        try:
            self.result_audio.stop()
            self.challenge_status.stop_effects()
            self.repair_effects.stop_effects()
        except RuntimeError:
            # QApplication 종료 시에는 자식 Qt 객체가 먼저 해제될 수 있다.
            pass
        super().hideEvent(event)

    def _make_result_page(self) -> QWidget:
        page, layout = scroll_page()
        heading = QHBoxLayout()
        self.result_title = label("문서 수정 완료", "title")
        self.result_title.setWordWrap(True)
        heading.addWidget(self.result_title, 1)
        self.result_mascot = QLabel()
        self.result_mascot.setAccessibleName("해체를 응원하는 작은 폭탄 도우미")
        self.result_mascot.setFixedSize(112, 112)
        self._load_result_mascot()
        self.result_mascot.hide()
        heading.addWidget(self.result_mascot)
        layout.addLayout(heading)
        self.result_context = label("", "muted", wrap=True)
        layout.addWidget(self.result_context)
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        scores = QHBoxLayout(card)
        scores.setContentsMargins(22, 20, 22, 20)
        scores.setSpacing(24)
        self.result_stars = label("", "stars")
        scores.addWidget(self.result_stars)
        counts = QVBoxLayout()
        counts.addWidget(label("입력 횟수 / 기준 입력 횟수", "muted"))
        self.result_summary = label("", "metric")
        self.result_summary.setToolTip(self.metrics["keys"].toolTip())
        counts.addWidget(self.result_summary)
        self.result_difference = label("", "muted")
        counts.addWidget(self.result_difference)
        scores.addLayout(counts, 1)
        timing = QVBoxLayout()
        timing.addWidget(label("소요 시간", "muted"))
        self.result_time = label("", "metric")
        timing.addWidget(self.result_time)
        timing.addStretch()
        scores.addLayout(timing, 1)
        layout.addWidget(card)
        self.result_accuracy = label("", "muted")
        layout.addWidget(self.result_accuracy)
        self.result_note = label("", "muted", wrap=True)
        layout.addWidget(self.result_note)
        self.result_challenge = label("", "sectionTitle", wrap=True)
        self.result_challenge.hide()
        layout.addWidget(self.result_challenge)
        self.result_bonus = label("", "muted", wrap=True)
        self.result_bonus.hide()
        layout.addWidget(self.result_bonus)
        self.failure_examples = QTextBrowser()
        self.failure_examples.setAccessibleName("시간 초과 구간과 수정 예")
        self.failure_examples.setMinimumHeight(160)
        self.failure_examples.setMaximumHeight(300)
        self.failure_examples.hide()
        layout.addWidget(self.failure_examples)
        actions = QHBoxLayout()
        self.result_new_button = button(
            "다른 문제", "newEditResult", primary=True, enter_activates=True
        )
        self.result_new_button.clicked.connect(self.new_problem)
        actions.addWidget(self.result_new_button)
        self.result_retry_button = button(
            "같은 과제 재도전", "retryEditingResult", enter_activates=True
        )
        self.result_retry_button.clicked.connect(self.retry)
        actions.addWidget(self.result_retry_button)
        self.revenge_button = button("놓친 구간 복수전", "revengeEditing")
        self.revenge_button.clicked.connect(self.start_revenge)
        self.revenge_button.hide()
        actions.addWidget(self.revenge_button)
        home = button("문서 수정 선택", "editingResultHome")
        home.clicked.connect(self.leave_requested.emit)
        actions.addWidget(home)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def prepare(
        self,
        lesson: EditLesson,
        mode: EditMode = "guided",
        *,
        font_size: int | None = None,
        random_document: bool | None = None,
        challenge: ChallengeOptions | None = None,
        prepared_session: EditingSession | None = None,
    ) -> None:
        selected = challenge or self.default_challenge
        reason = bomb_unavailable_reason(lesson, mode)
        if selected.kind == "bomb" and reason:
            selected = replace(selected, kind="normal")
        if mode == "free":
            selected = replace(selected, auto_repair=False)
        next_session = prepared_session or EditingSession(
            lesson, mode, challenge=selected
        )
        self._switching = True
        try:
            self.abort()
            self.session = next_session
            self._guide_goal_positions.clear()
            self._started = False
            self._mission = (
                get_document_mission(lesson.id)
                if lesson.id.startswith("mission_")
                else None
            )
            spec = lesson.practice_spec
            profile = get_edit_profile(spec.profile_id) if spec is not None else None
            if spec is not None and profile is not None and profile.language == "text":
                if spec.document_lines > profile.document_lengths[0]:
                    self._return_spec = spec
                elif (
                    self._return_spec is None
                    or self._return_spec.profile_id != spec.profile_id
                    or self._return_spec.seed != spec.seed
                ):
                    self._return_spec = replace(
                        spec, document_lines=profile.default_document_lines
                    )
            if random_document is not None:
                self._random_documents = random_document
            if self._mission is None:
                self._random_documents = False
            if font_size is not None:
                with QSignalBlocker(self.document_font_spin):
                    self.document_font_spin.setValue(font_size)
            self._show_problem_summary(lesson)
            self._reset_options(lesson, mode, profile)
            self._reset_controls(lesson, mode, profile)
            self._reset_challenge_controls(reason)
            activity = lesson.activity
            self.activity_options.setVisible(activity is not None)
            for objective, check in self._bonus_checks.items():
                with QSignalBlocker(check):
                    check.setChecked(
                        activity is not None and objective in activity.objectives
                    )
                check.setEnabled(objective != "all_direct" or self.session.bomb_enabled)
            if activity is not None:
                self.length_combo.hide()
                self.document_combo.hide()
                self.short_button.hide()
                self.new_problem_button.setEnabled(activity.kind == "boss")
                self.result_new_button.setEnabled(activity.kind == "boss")
            self.comparison.set_font_size(self.document_font_spin.value())
            language: DocumentLanguage = "text"
            if self._mission is not None:
                language = self._mission.language
            elif profile is not None:
                language = profile.language
            self.comparison.set_language(language)
            self.comparison.set_paused(False)
            self.comparison.show_documents(
                lesson.initial, EditorState(lesson.goal_lines)
            )
            self.practice_input.setEnabled(False)
            self.feedback.setText(
                f"일반 연습 · {reason}"
                if reason
                else "연습 시작 후 첫 입력부터 시간을 잽니다."
            )
            self.stack.setCurrentWidget(self.practice_page)
            self._refresh()
            self.start_button.setFocus()
        finally:
            self._switching = False

    def _reset_challenge_controls(self, reason: str | None = None) -> None:
        session = self.session
        if session is None:
            return
        options = session.challenge
        with QSignalBlocker(self.challenge_combo):
            self.challenge_combo.setCurrentIndex(
                self.challenge_combo.findData(options.kind)
            )
            model = self.challenge_combo.model()
            if isinstance(model, QStandardItemModel):
                model.item(1).setEnabled(not bool(reason))
        with QSignalBlocker(self.difficulty_combo):
            self.difficulty_combo.setCurrentIndex(
                self.difficulty_combo.findData(options.difficulty)
            )
        with QSignalBlocker(self.auto_repair_check):
            self.auto_repair_check.setChecked(options.auto_repair)
        self.challenge_combo.setEnabled(True)
        self.difficulty_combo.setEnabled(session.bomb_enabled)
        self.auto_repair_check.setEnabled(
            session.bomb_enabled and session.mode == "guided"
        )
        self.challenge_combo.setToolTip(
            reason
            or (
                "문서 전체 제한시간 · 시간 초과 후에는 추가 학습으로 계속합니다."
                if session.bomb_enabled and session.mode == "free"
                else "첫 입력부터 · 이동과 수정을 한 구간으로 해체하세요."
                if session.bomb_enabled
                else "제한시간 없이 차근차근 연습합니다."
            )
        )
        self.challenge_options_bar.setVisible(session.bomb_enabled)
        self.challenge_status.setVisible(session.bomb_enabled)
        self._reflow_actions()

    def _show_problem_summary(self, lesson: EditLesson) -> None:
        self.title.setText(lesson.title)
        self.description.setText(lesson.description)
        excerpt = lesson.code_excerpt
        self.code_source_summary.setVisible(excerpt is not None)
        if excerpt is not None:
            source = excerpt.source
            spec = lesson.practice_spec
            self.code_source_summary.setText(
                f"{source.project} · {source.title} · "
                f"원문 {excerpt.start_line}~{excerpt.end_line}행"
            )
            self.code_source_summary.setToolTip(
                f"{source.url}\n고정 버전 {source.revision}\n"
                + (
                    "다른 문제에서도 선택한 코드 문서를 유지하고 "
                    "발췌 구간·손상을 바꿉니다."
                    if spec is not None and spec.code_source_id is not None
                    else "다른 문제에서 프로젝트·발췌 구간·손상이 새로 선택됩니다."
                )
            )
        if lesson.goal_cursor is not None:
            row, column = lesson.goal_cursor
            self.description.setText(
                self.description.text() + f" · 완료 커서 {row + 1}행 {column + 1}열"
            )

    def _reset_options(
        self, lesson: EditLesson, mode: EditMode, profile: EditProfile | None
    ) -> None:
        with QSignalBlocker(self.mode_combo):
            self.mode_combo.setCurrentIndex(0 if mode == "guided" else 1)
            model = self.mode_combo.model()
            if isinstance(model, QStandardItemModel):
                model.item(1).setEnabled(lesson.free_enabled)
            self.mode_combo.setEnabled(True)
        spec = lesson.practice_spec
        with QSignalBlocker(self.length_combo):
            self.length_combo.clear()
            if spec is not None and profile is not None and profile.language == "text":
                for lines, title in zip(
                    profile.document_lengths, ("짧게", "보통", "길게"), strict=True
                ):
                    self.length_combo.addItem(f"{title} · {lines}줄", lines)
                self.length_combo.setCurrentIndex(
                    self.length_combo.findData(spec.document_lines)
                )
            adjustable = spec is not None and self.length_combo.count() > 1
            self.length_combo.setEnabled(adjustable)
            self.length_combo.setVisible(adjustable)
        with QSignalBlocker(self.document_combo):
            self.document_combo.clear()
            if self._mission is not None:
                self.document_combo.setAccessibleName("연습 문서 선택")
                self.document_combo.addItem("무작위 문서", "")
                for document in self._documents:
                    self.document_combo.addItem(document.title, document.id)
                selected = "" if self._random_documents else lesson.id
            elif lesson.code_excerpt is not None and spec is not None:
                self.document_combo.setAccessibleName("연습 코드 문서 선택")
                self.document_combo.addItem("무작위 코드 문서", "")
                for entry in self._code_sources:
                    source = entry.source
                    if source.language == lesson.code_excerpt.source.language:
                        self.document_combo.addItem(
                            f"{source.project} · {source.title}", source.id
                        )
                selected = spec.code_source_id or ""
            else:
                selected = ""
            self.document_combo.setCurrentIndex(
                max(0, self.document_combo.findData(selected))
            )
            selectable = self._mission is not None or lesson.code_excerpt is not None
            self.document_combo.setVisible(selectable)
            self.document_combo.setEnabled(selectable)

    def _reset_controls(
        self, lesson: EditLesson, mode: EditMode, profile: EditProfile | None
    ) -> None:
        self.start_button.show()
        self.pause_button.setText("일시정지")
        self.pause_button.setEnabled(False)
        self.return_button.setEnabled(False)
        self.return_button.setVisible(mode == "guided")
        generated = lesson.practice_spec is not None
        self.new_problem_button.setEnabled(generated or self._mission is not None)
        self.result_new_button.setEnabled(generated or self._mission is not None)
        spec = lesson.practice_spec
        self.short_button.setVisible(profile is not None and profile.language == "text")
        self.short_button.setText(
            "짧게 7곳 연습"
            if spec is not None
            and profile is not None
            and spec.document_lines > profile.document_lengths[0]
            else "긴 문서 연습"
        )
        self.source_button.setVisible(
            self._mission is not None or lesson.code_excerpt is not None
        )

    def _mode_changed(self) -> None:
        if self.session is not None and not self._started:
            mode: EditMode = "guided" if self.mode_combo.currentIndex() == 0 else "free"
            self.prepare(
                self.session.lesson, mode, font_size=self.practice_input.font_size
            )

    def _font_changed(self, size: int) -> None:
        self.comparison.set_font_size(size)
        self.preferences_changed.emit()
        if self.session is not None:
            self._refresh()

    @staticmethod
    def _fresh_seed(previous: int | None = None) -> int:
        seed = randbelow(2**32)
        return (seed + 1) % 2**32 if seed == previous else seed

    def _choose_document(self, *, exclude: str | None = None) -> str:
        choices = [document for document in self._documents if document.id != exclude]
        if not choices:
            choices = list(self._documents)
        if not choices:
            raise ValueError("사용할 수 있는 연습 문서가 없습니다.")
        return choices[randbelow(len(choices))].id

    def _document_changed(self) -> None:
        session = self.session
        if self._switching or session is None:
            return
        if self._mission is None:
            self._code_document_changed(session)
            return
        try:
            selection = str(self.document_combo.currentData())
            random_document = not selection
            mission_id = selection or self._choose_document(exclude=self._mission.id)
            previous = session.lesson.document_spec
            spec = DocumentPracticeSpec(
                mission_id,
                self._fresh_seed(previous.seed if previous else None),
                max(7, previous.change_count) if previous else 7,
                technique_weights=self._new_technique_weights(),
            )
        except ValueError as error:
            self._show_problem_error(error)
        else:
            if self._prepare_generated_problem(spec, random_document=random_document):
                return
        with QSignalBlocker(self.document_combo):
            selected = "" if self._random_documents else self._mission.id
            self.document_combo.setCurrentIndex(self.document_combo.findData(selected))

    def _code_document_changed(self, session: EditingSession) -> None:
        previous = session.lesson.practice_spec
        if previous is None or session.lesson.code_excerpt is None:
            return
        try:
            selection = str(self.document_combo.currentData()) or None
            seed = self._fresh_seed(previous.seed)
            spec = replace(
                previous,
                seed=seed,
                document_lines=random_edit_document_lines(previous.profile_id, seed),
                technique_weights=self._new_technique_weights(),
                code_source_id=selection,
            )
        except ValueError as error:
            self._show_problem_error(error)
        else:
            if self._prepare_generated_problem(spec):
                return
        with QSignalBlocker(self.document_combo):
            self.document_combo.setCurrentIndex(
                self.document_combo.findData(previous.code_source_id or "")
            )

    def _show_problem_error(self, error: ValueError | OSError) -> None:
        note = (
            self.result_note
            if self.stack.currentWidget() is self.result_page
            else self.feedback
        )
        note.setText(f"과제 열기 실패 · {error}")
        note.show()

    def _length_changed(self) -> None:
        session = self.session
        if session is None or self._started or session.lesson.practice_spec is None:
            return
        spec = replace(
            session.lesson.practice_spec,
            document_lines=int(self.length_combo.currentData()),
        )
        if not self._prepare_generated_problem(spec):
            with QSignalBlocker(self.length_combo):
                self.length_combo.setCurrentIndex(
                    self.length_combo.findData(
                        session.lesson.practice_spec.document_lines
                    )
                )

    def _prepare_generated_problem(
        self,
        spec: EditPracticeSpec | DocumentPracticeSpec,
        *,
        random_document: bool | None = None,
    ) -> bool:
        """새 문제 검증에 성공한 뒤에만 현재 시도를 교체한다."""
        session = self.session
        if session is None:
            return False
        try:
            lesson = (
                create_edit_problem(spec)
                if isinstance(spec, EditPracticeSpec)
                else create_random_document_problem(spec)
            )
        except (ValueError, OSError) as error:
            self._show_problem_error(error)
            return False
        mode = session.mode if lesson.free_enabled else "guided"
        self.prepare(
            lesson,
            mode,
            font_size=self.practice_input.font_size,
            random_document=random_document,
        )
        return True

    def start_practice(self) -> None:
        if self.session is None or self._started:
            return
        self._started = True
        self.start_button.hide()
        self.mode_combo.setEnabled(False)
        self.challenge_combo.setEnabled(False)
        self.difficulty_combo.setEnabled(False)
        self.auto_repair_check.setEnabled(False)
        for check in self._bonus_checks.values():
            check.setEnabled(False)
        self.length_combo.setEnabled(False)
        self.practice_input.setEnabled(True)
        self.practice_input.setFocus()
        self.pause_button.setEnabled(True)
        self.return_button.setEnabled(True)
        self.feedback.setText("첫 입력을 기다리고 있습니다.")
        self._sync_viewport()
        self.timer.start()

    def _tick(self) -> None:
        session = self.session
        if session is None:
            return
        if session.check_deadline(self._timer_guard):
            self.feedback.setText(session.message)
            self._refresh()
            self._handle_session_state()
        else:
            self._refresh_metrics()

    def _sync_viewport(self) -> None:
        if self.session is not None:
            self.session.engine.set_viewport(
                self.comparison.viewport_rows, self.comparison.viewport_top
            )

    def _receive_key(self, normalized: NormalizedKey) -> None:
        session = self.session
        if (
            session is None
            or not self._started
            or session.state
            not in {
                SessionState.READY,
                SessionState.RUNNING,
            }
        ):
            return
        if normalized.token is not None:
            self._sync_viewport()
        outcome = session.submit(normalized.token)
        if outcome == InputResult.IGNORED:
            self.feedback.setText("입력 제외 · 영문 입력 모드에서 한 키씩 눌러 주세요.")
        else:
            self.feedback.setText(
                session.message
                or (
                    ""
                    if outcome == InputResult.ACCEPTED
                    else "기대 키 또는 허용 명령을 확인하세요."
                )
            )
        self._refresh()
        if outcome == InputResult.ACCEPTED:
            self.practice_input.show_yank(session.yanked_spans)
        self._handle_session_state()

    def _handle_session_state(self) -> None:
        session = self.session
        if session is None:
            return
        if session.state == SessionState.COMPLETED:
            self._finish()
        elif session.state == SessionState.PAUSED:
            self.timer.stop()
            self.challenge_status.stop_effects()
            self.repair_effects.stop_effects()
            self.comparison.set_paused(True)
            self.pause_button.setText(
                "복구 오류" if session.recovery_error else "연습 재개"
            )
            self.pause_button.setEnabled(not bool(session.recovery_error))

    def _composition_blocked(self) -> None:
        self.feedback.setText("입력 제외 · 영문 입력 모드에서 한 키씩 눌러 주세요.")

    def _refresh(self) -> None:
        if self.session is None:
            return
        self._timer_guard = self.session.timer_guard
        self.comparison.show_current(
            self.session.engine.state,
            follow_viewport=self._started,
            goal_position=self._guide_goal_position(),
        )
        self.practice_input.show_recovery_marks(
            tuple(
                (mark.row, f"{mark.segment_id} · {mark.text}")
                for mark in self.session.recovery_marks
            )
        )
        self.practice_input.show_success_marks(
            tuple(
                (mark.row, f"{mark.segment_id} · {mark.text}")
                for mark in self.session.success_marks
            )
        )
        self.command_prompt.setText(self.session.engine.state.command_line)
        self.command_prompt.setVisible(bool(self.session.engine.state.command_line))
        self._show_repair_progress(self.comparison.remaining_changes)
        self._refresh_guide()
        self.repair_effects.set_session(self.session)
        self._refresh_metrics()

    def _guide_goal_position(self) -> tuple[int, int] | None:
        session = self.session
        if (
            session is None
            or session.mode != "guided"
            or session.lesson.practice_spec is None
            or not session.lesson.id.startswith("code_")
        ):
            return None
        if session.step_index in self._guide_goal_positions:
            return self._guide_goal_positions[session.step_index]
        # 코드는 단계 종료 시 줄 수를 유지한다. 현재 입력 중의 dd·p 사이에는
        # 줄 수가 달라질 수 있으므로 검증된 단계 경계에서 다음 수정 위치를 찾는다.
        before = (
            session.lesson.initial.lines
            if session.step_index == 0
            else session.lesson.guide[session.step_index - 1].expected.lines
        )
        for step in session.lesson.guide[session.step_index :]:
            if before != step.expected.lines:
                change = compare_documents(before, step.expected.lines)
                span = change.goal_spans[0]
                position = span.row, span.start
                self._guide_goal_positions[session.step_index] = position
                return position
            before = step.expected.lines
        self._guide_goal_positions[session.step_index] = None
        return None

    def _show_repair_progress(self, remaining: int) -> None:
        spec = self.session.lesson.document_spec if self.session else None
        count = (
            spec.change_count
            if spec
            else self._mission.repair_count
            if self._mission
            else 0
        )
        prefix = f"{count}곳 복구 · " if self._mission else ""
        if self.session and self.session.lesson.id == "editing_undo":
            message = "변경·복원 가이드를 모두 마치세요."
        elif remaining:
            message = f"남은 차이 {remaining}곳"
        else:
            message = (
                "문서 일치 · Normal 모드에서 가이드를 모두 마치면 완료합니다."
                if self.session and self.session.mode == "guided"
                else "문서 일치 · Normal 모드에서 미완성 명령을 마치면 완료합니다."
            )
        self.mission_progress.setText(prefix + message)

    def _refresh_guide(self) -> None:
        session = self.session
        if session is None or session.mode == "free" or session.current_step is None:
            self.comparison.clear_guide()
            return
        self.comparison.show_guide(
            session.current_step.keys,
            session.token_index,
            description=session.current_step.text,
            progress=f"단계 {session.step_index + 1}/{len(session.lesson.guide)}",
        )

    def _refresh_metrics(self) -> None:
        session = self.session
        if session is None:
            return
        self.challenge_status.set_session(session)
        self.rival_status.set_session(session, enabled=self.record_rival_enabled)
        editor = session.engine.state
        self.metrics["mode"].setText(
            editor.mode.upper()
            + (
                f" / {editor.pending}"
                if editor.pending and not editor.command_line
                else ""
            )
        )
        self.metrics["keys"].setText(
            f"입력 횟수 {session.key_count}회\n기준 입력 횟수 {session.baseline_keys}회"
        )
        self.metrics["time"].setText(f"소요 시간 {session.elapsed_seconds:.1f}초")
        self.metrics["guide"].setText(
            ("—" if session.accuracy is None else f"{session.accuracy:.1f}%")
            + f" / 콤보 {session.combo}"
            if session.mode == "guided"
            else "자유 풀이"
        )

    def _focus_lost(self, reason: Qt.FocusReason) -> None:
        if reason == Qt.FocusReason.MouseFocusReason and QApplication.focusWidget() in (
            self.pause_button,
            self.return_button,
            self.personal_record_check,
        ):
            return
        if not self._switching and self._started:
            self.pause()

    def pause(self) -> None:
        if (
            self.session is None
            or not self._started
            or self.session.state
            not in {
                SessionState.READY,
                SessionState.RUNNING,
            }
        ):
            return
        self.session.pause()
        self.feedback.setText(
            self.session.message
            if self.session.recovery_error
            else "일시정지 · 재개 버튼을 눌러 계속하세요."
        )
        self._refresh()
        self._handle_session_state()

    def toggle_pause(self) -> None:
        if self.session is None:
            return
        if self.session.state == SessionState.PAUSED:
            self.session.resume()
            if self.session.state == SessionState.PAUSED:
                self.feedback.setText(self.session.message)
                return
            self.comparison.set_paused(False)
            self.pause_button.setText("일시정지")
            self.practice_input.setFocus()
            self.feedback.setText("이어서 입력하세요.")
            self._refresh()
            self.timer.start()
        else:
            self.pause()

    def return_to_step(self) -> None:
        session = self.session
        if session is not None:
            self.practice_input.clear_yank_highlight()
            session.return_to_step()
            self.feedback.setText(session.message)
            self._refresh()
            self._handle_session_state()
        self._refocus()

    def _refocus(self) -> None:
        if self.session is not None and self.session.state in {
            SessionState.READY,
            SessionState.RUNNING,
        }:
            self.practice_input.setFocus()

    def _close_source_dialog(self) -> None:
        if self._source_dialog is not None:
            self._source_dialog.close()
            self._source_dialog.deleteLater()
            self._source_dialog = None

    def abort(self) -> None:
        self.timer.stop()
        self.practice_input.clear_yank_highlight()
        self.result_audio.stop()
        self.challenge_status.stop_effects()
        self.repair_effects.stop_effects()
        self._close_source_dialog()
        if self.session is not None:
            self.session.abort()
            result = self.session.result
            if result is not None and self.session.key_count:
                self.repository.save(result)

    def retry(self) -> None:
        if self.session is not None:
            fresh = self.session.retry()
            self.prepare(
                fresh.lesson,
                fresh.mode,
                font_size=self.practice_input.font_size,
                challenge=fresh.challenge,
                prepared_session=fresh,
            )

    def start_revenge(self) -> None:
        session = self.session
        if session is None:
            return
        try:
            fresh = session.create_revenge()
        except ValueError as error:
            self._show_problem_error(error)
            return
        self.prepare(
            fresh.lesson,
            fresh.mode,
            font_size=self.practice_input.font_size,
            challenge=fresh.challenge,
            prepared_session=fresh,
        )

    def toggle_short_practice(self) -> None:
        session = self.session
        if session is None or session.lesson.practice_spec is None:
            return
        spec = session.lesson.practice_spec
        profile = get_edit_profile(spec.profile_id)
        if profile.language != "text":
            return
        lines = (
            profile.document_lengths[0]
            if spec.document_lines > profile.document_lengths[0]
            else (
                self._return_spec.document_lines
                if self._return_spec
                else profile.default_document_lines
            )
        )
        self._prepare_generated_problem(replace(spec, document_lines=lines))

    def new_problem(self) -> None:
        session = self.session
        if session is None:
            return
        activity = session.lesson.activity
        if activity is not None:
            if activity.kind == "boss":
                try:
                    lesson = create_boss_problem(
                        self._fresh_seed(activity.seed), objectives=activity.objectives
                    )
                except (ValueError, OSError) as error:
                    self._show_problem_error(error)
                else:
                    self.prepare(lesson, session.mode)
            return
        try:
            weights = self._new_technique_weights()
        except ValueError as error:
            self._show_problem_error(error)
            return
        if self._mission is not None:
            previous_document = session.lesson.document_spec
            count = max(7, previous_document.change_count) if previous_document else 7
            mission_id = (
                self._choose_document(exclude=self._mission.id)
                if self._random_documents
                else self._mission.id
            )
            seed = self._fresh_seed(
                previous_document.seed if previous_document else None
            )
            self._prepare_generated_problem(
                DocumentPracticeSpec(mission_id, seed, count, technique_weights=weights)
            )
            return
        if session.lesson.practice_spec is None:
            return
        previous = session.lesson.practice_spec
        seed = self._fresh_seed(previous.seed)
        self._prepare_generated_problem(
            replace(
                previous,
                seed=seed,
                document_lines=(
                    previous.document_lines
                    if get_edit_profile(previous.profile_id).language == "text"
                    else random_edit_document_lines(previous.profile_id, seed)
                ),
                technique_weights=weights,
            )
        )

    def _new_technique_weights(self) -> EditTechniqueWeights | None:
        if self._technique_weights is not None:
            return self._technique_weights()
        if self.session is not None:
            lesson = self.session.lesson
            spec = lesson.practice_spec or lesson.document_spec
            if spec is not None:
                return spec.technique_weights
        return None

    def show_source(self) -> None:
        excerpt = self.session.lesson.code_excerpt if self.session else None
        if self._mission is not None:
            source = self._mission.source
        elif excerpt is not None:
            source = excerpt.source
        else:
            return
        try:
            license_text = (
                read_code_license(source.id)
                if excerpt is not None
                else read_document_license(source.id)
            )
        except (ValueError, OSError) as error:
            self._show_problem_error(error)
            return
        self._close_source_dialog()
        self.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("문서 출처와 라이선스")
        dialog.resize(680, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            label(
                f"{source.project} · {source.title}\n{source.url}\n"
                f"라이선스 {source.license_id}\n고정 버전 {source.revision}\n"
                + (
                    f"발췌 {excerpt.start_line}~{excerpt.end_line}행\n"
                    if excerpt is not None
                    else ""
                )
                + f"표시 변환: {source.transformation}",
                "muted",
                wrap=True,
            )
        )
        license_view = QTextBrowser()
        license_view.setPlainText(license_text)
        layout.addWidget(license_view, 1)
        actions = QHBoxLayout()
        original = button("웹에서 원문 보기", "openOriginalDocument")
        original.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(source.url)))
        actions.addWidget(original)
        close = button("닫기", "closeDocumentSource")
        close.clicked.connect(dialog.close)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._source_dialog = dialog
        dialog.show()

    def _finish(self) -> None:
        session = self.session
        if session is None or session.result is None:
            return
        result = session.result
        self.last_result = result
        new_best = self.repository.save(result)
        self.timer.stop()
        self.challenge_status.stop_effects()
        self.repair_effects.stop_effects()
        challenge = result.challenge
        if challenge is not None and challenge.segments:
            final = challenge.segments[-1]
            self.result_audio.play(
                "success" if final.verdict == "direct" else "timeout"
            )
        self.result_mascot.setVisible(
            challenge is not None and self.appearance.decorations
        )
        self.result_bonus.setVisible(bool(result.bonus_objectives))
        self.result_bonus.setText(
            "선택 목표 · "
            + " · ".join(
                f"{'✓' if objective.achieved else '○'} {BONUS_TITLES[objective.id]}"
                for objective in result.bonus_objectives
            )
            + f"\n보너스 {result.bonus_points:,}점"
        )
        self.result_title.setText(
            "문서 수정 완료"
            if challenge is None
            else "복수전 완료"
            if challenge.revenge_of and challenge.full_clear
            else "폭탄 도전 클리어!"
            if challenge.full_clear
            else "놓친 구간을 다시 연습해요"
        )
        self.result_challenge.setVisible(challenge is not None)
        self.failure_examples.setVisible(bool(session.failure_examples))
        self.revenge_button.setVisible(
            challenge is not None
            and challenge.timeout_count > 0
            and session.mode == "guided"
        )
        if challenge is not None:
            self.result_challenge.setText(
                f"직접 해결 {challenge.direct_count} / "
                f"시간 초과 {challenge.timeout_count}"
                f" · 자동 복구 {challenge.auto_repair_count}\n"
                f"해체 점수 {challenge.score:,} · 최고 연속 해체 {challenge.max_chain}"
            )
        examples: list[str] = []
        for failure in session.failure_examples:
            difference = "\n".join(
                list(
                    unified_diff(
                        failure.before_lines,
                        failure.goal_lines,
                        fromfile="시간 초과 당시",
                        tofile="수정 예",
                        lineterm="",
                        n=1,
                    )
                )[:80]
            )
            keys = "".join(key.display for key in failure.guide_keys)
            examples.append(
                f"{failure.segment_id} · 시간 초과\n{difference}\n기준 가이드: {keys}"
            )
        self.failure_examples.setPlainText("\n\n".join(examples))
        self.failure_examples.setToolTip(
            "실패 당시 내용은 현재 시도에서만 표시하며 기록에 저장하지 않습니다."
        )
        self.result_stars.setText("★" * result.stars + "☆" * (3 - result.stars))
        self.result_context.setText(
            f"{session.lesson.title} · "
            + ("가이드 풀이" if session.mode == "guided" else "자유 풀이")
        )
        self.result_summary.setText(f"{result.key_count} / {result.baseline_keys}회")
        self.result_difference.setText(
            "기준과 같음"
            if result.delta == 0
            else f"기준보다 {abs(result.delta)}회 "
            + ("적게 입력" if result.delta < 0 else "더 입력")
        )
        if not result.efficiency_eligible:
            self.result_difference.setText("부분 도전 · 입력 효율 비교 제외")
        self.result_time.setText(f"{result.elapsed_seconds:.1f}초")
        self.result_accuracy.setText(
            f"가이드 정확도 {result.accuracy:.1f}%"
            if result.accuracy is not None
            else ""
        )
        self.result_accuracy.setVisible(result.accuracy is not None)
        self.result_note.setText("개인 기록 갱신" if new_best else "")
        self.result_note.setVisible(new_best)
        self._switching = True
        try:
            self.stack.setCurrentWidget(self.result_page)
            (
                self.result_new_button
                if self.result_new_button.isEnabled()
                else self.result_retry_button
            ).setFocus()
        finally:
            self._switching = False
