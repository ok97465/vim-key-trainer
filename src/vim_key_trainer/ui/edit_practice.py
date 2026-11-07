"""긴 편집 문서의 준비·가이드/자유 풀이·결과 화면."""

# Standard library imports
from collections.abc import Callable
from dataclasses import replace
from secrets import randbelow

# Third party imports
from PySide6.QtCore import QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.content.document_missions import (
    get_document_mission,
    list_document_missions,
    read_document_license,
)
from vim_key_trainer.domain.document_missions import (
    DocumentMission,
    DocumentPracticeSpec,
)
from vim_key_trainer.domain.edit_weights import EditTechniqueWeights
from vim_key_trainer.domain.editing import (
    EDIT_DOCUMENT_LENGTHS,
    EditLesson,
    EditMode,
    EditPracticeSpec,
)
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.engine import EditorState
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import ResultRepository
from vim_key_trainer.ui.components import button, label, scroll_page
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets.edit_comparison import EditComparison


class EditPracticePage(QWidget):
    leave_requested = Signal()

    def __init__(
        self,
        repository: ResultRepository,
        *,
        technique_weights: Callable[[], EditTechniqueWeights] | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self._technique_weights = technique_weights
        self.session: EditingSession | None = None
        self.last_result: EditingSessionResult | None = None
        self._switching = False
        self._started = False
        self._return_spec: EditPracticeSpec | None = None
        self._source_dialog: QDialog | None = None
        self._mission: DocumentMission | None = None
        self._random_documents = False
        self._documents = list_document_missions()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)
        self.practice_page = self._make_practice_page()
        self.result_page = self._make_result_page()
        self.stack.addWidget(self.practice_page)
        self.stack.addWidget(self.result_page)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._refresh_metrics)

    def _make_practice_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 10, 18, 10)
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
        self.comparison = EditComparison()
        self.practice_input = self.comparison.practice_input
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
        self.document_combo.addItem("무작위 문서", "")
        for document in self._documents:
            self.document_combo.addItem(document.title, document.id)
        self.document_combo.currentIndexChanged.connect(self._document_changed)
        options.addWidget(self.document_combo, 1)
        self.length_combo = QComboBox()
        self.length_combo.setAccessibleName("편집 문서 길이")
        for lines, title in zip(
            EDIT_DOCUMENT_LENGTHS, ("짧게", "보통", "길게"), strict=True
        ):
            self.length_combo.addItem(f"{title} · {lines}줄", lines)
        self.length_combo.setCurrentIndex(1)
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
        actions = QHBoxLayout(bar)
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
        for item in (
            self.start_button,
            self.pause_button,
            self.retry_button,
            self.new_problem_button,
            self.return_button,
            self.short_button,
            self.source_button,
            self.leave_button,
        ):
            actions.addWidget(item)
        actions.addStretch()
        return bar

    def _make_result_page(self) -> QWidget:
        page, layout = scroll_page()
        layout.addWidget(label("문서 수정 완료", "title"))
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
    ) -> None:
        self._switching = True
        try:
            self.abort()
            self.session = EditingSession(lesson, mode)
            self._started = False
            self._mission = (
                get_document_mission(lesson.id)
                if lesson.id.startswith("mission_")
                else None
            )
            if lesson.practice_spec is not None:
                spec = lesson.practice_spec
                if spec.document_lines > 12:
                    self._return_spec = spec
                elif (
                    self._return_spec is None
                    or self._return_spec.profile_id != spec.profile_id
                    or self._return_spec.seed != spec.seed
                ):
                    self._return_spec = replace(spec, document_lines=24)
            if random_document is not None:
                self._random_documents = random_document
            if self._mission is None:
                self._random_documents = False
            if font_size is not None:
                with QSignalBlocker(self.document_font_spin):
                    self.document_font_spin.setValue(font_size)
            self._show_problem_summary(lesson)
            self._reset_options(lesson, mode)
            self._reset_controls(lesson, mode)
            self.comparison.set_font_size(self.document_font_spin.value())
            self.comparison.set_language(
                self._mission.language if self._mission else "text"
            )
            self.comparison.set_paused(False)
            self.comparison.show_documents(
                lesson.initial, EditorState(lesson.goal_lines)
            )
            self.practice_input.setEnabled(False)
            self.feedback.setText("연습 시작 후 첫 입력부터 시간을 잽니다.")
            self.stack.setCurrentWidget(self.practice_page)
            self._refresh()
            self.start_button.setFocus()
        finally:
            self._switching = False

    def _show_problem_summary(self, lesson: EditLesson) -> None:
        self.title.setText(lesson.title)
        self.description.setText(lesson.description)
        if lesson.goal_cursor is not None:
            row, column = lesson.goal_cursor
            self.description.setText(
                self.description.text() + f" · 완료 커서 {row + 1}행 {column + 1}열"
            )

    def _reset_options(self, lesson: EditLesson, mode: EditMode) -> None:
        with QSignalBlocker(self.mode_combo):
            self.mode_combo.setCurrentIndex(0 if mode == "guided" else 1)
            model = self.mode_combo.model()
            if isinstance(model, QStandardItemModel):
                model.item(1).setEnabled(lesson.free_enabled)
            self.mode_combo.setEnabled(True)
        spec = lesson.practice_spec
        with QSignalBlocker(self.length_combo):
            if spec is not None:
                self.length_combo.setCurrentIndex(
                    self.length_combo.findData(spec.document_lines)
                )
            self.length_combo.setEnabled(spec is not None)
            self.length_combo.setVisible(spec is not None)
        with QSignalBlocker(self.document_combo):
            selected = "" if self._random_documents else lesson.id
            self.document_combo.setCurrentIndex(
                max(0, self.document_combo.findData(selected))
            )
            self.document_combo.setVisible(self._mission is not None)
            self.document_combo.setEnabled(self._mission is not None)

    def _reset_controls(self, lesson: EditLesson, mode: EditMode) -> None:
        self.start_button.show()
        self.pause_button.setText("일시정지")
        self.pause_button.setEnabled(False)
        self.return_button.setEnabled(False)
        self.return_button.setVisible(mode == "guided")
        generated = lesson.practice_spec is not None
        self.new_problem_button.setEnabled(generated or self._mission is not None)
        self.result_new_button.setEnabled(generated or self._mission is not None)
        self.short_button.setVisible(generated)
        spec = lesson.practice_spec
        self.short_button.setText(
            "짧게 7곳 연습" if spec and spec.document_lines > 12 else "긴 문서 연습"
        )
        self.source_button.setVisible(self._mission is not None)

    def _mode_changed(self) -> None:
        if self.session is not None and not self._started:
            mode: EditMode = "guided" if self.mode_combo.currentIndex() == 0 else "free"
            self.prepare(
                self.session.lesson, mode, font_size=self.practice_input.font_size
            )

    def _font_changed(self, size: int) -> None:
        self.comparison.set_font_size(size)
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
        if self._switching or session is None or self._mission is None:
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

    def _show_problem_error(self, error: ValueError) -> None:
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
        except ValueError as error:
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
        self.length_combo.setEnabled(False)
        self.practice_input.setEnabled(True)
        self.practice_input.setFocus()
        self.pause_button.setEnabled(True)
        self.return_button.setEnabled(True)
        self.feedback.setText("첫 입력을 기다리고 있습니다.")
        self._sync_viewport()
        self.timer.start()

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
        if session.state == SessionState.COMPLETED:
            self._finish()

    def _composition_blocked(self) -> None:
        self.feedback.setText("입력 제외 · 영문 입력 모드에서 한 키씩 눌러 주세요.")

    def _refresh(self) -> None:
        if self.session is None:
            return
        self.comparison.show_current(
            self.session.engine.state, follow_viewport=self._started
        )
        self.command_prompt.setText(self.session.engine.state.command_line)
        self.command_prompt.setVisible(bool(self.session.engine.state.command_line))
        self._show_repair_progress(self.comparison.remaining_changes)
        self._refresh_guide()
        self._refresh_metrics()

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
        self.timer.stop()
        self.comparison.set_paused(True)
        self.pause_button.setText("연습 재개")
        self.feedback.setText("일시정지 · 재개 버튼을 눌러 계속하세요.")
        self._refresh_metrics()

    def toggle_pause(self) -> None:
        if self.session is None:
            return
        if self.session.state == SessionState.PAUSED:
            self.session.resume()
            self.comparison.set_paused(False)
            self.pause_button.setText("일시정지")
            self.practice_input.setFocus()
            self.feedback.setText("이어서 입력하세요.")
            self.timer.start()
        else:
            self.pause()

    def return_to_step(self) -> None:
        if self.session is not None and self.session.return_to_step():
            self.feedback.setText(
                "단계 복귀 · 입력 수와 시간은 유지하고 콤보는 초기화합니다."
            )
            self._refresh()
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
        self._close_source_dialog()
        if self.session is not None:
            self.session.abort()
            result = self.session.result
            if (
                result is not None
                and result.state == SessionState.ABORTED
                and self.session.key_count
            ):
                self.repository.save(result)

    def retry(self) -> None:
        if self.session is not None:
            self.prepare(
                self.session.lesson,
                self.session.mode,
                font_size=self.practice_input.font_size,
            )

    def toggle_short_practice(self) -> None:
        session = self.session
        if session is None or session.lesson.practice_spec is None:
            return
        spec = session.lesson.practice_spec
        lines = (
            12
            if spec.document_lines > 12
            else (self._return_spec.document_lines if self._return_spec else 24)
        )
        self._prepare_generated_problem(replace(spec, document_lines=lines))

    def new_problem(self) -> None:
        session = self.session
        if session is None:
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
        self._prepare_generated_problem(
            replace(
                previous,
                seed=self._fresh_seed(previous.seed),
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
        if self._mission is None:
            return
        self._close_source_dialog()
        self.pause()
        source = self._mission.source
        dialog = QDialog(self)
        dialog.setWindowTitle("문서 출처와 라이선스")
        dialog.resize(680, 500)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            label(
                f"{source.project} · {source.title}\n{source.url}\n"
                f"라이선스 {source.license_id}\n고정 버전 {source.revision}\n"
                f"원문 SHA-256 {source.sha256}",
                "muted",
                wrap=True,
            )
        )
        license_view = QTextBrowser()
        license_view.setPlainText(read_document_license(source.id))
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
