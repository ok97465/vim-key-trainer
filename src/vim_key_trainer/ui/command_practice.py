"""Vim 명령 타이핑의 준비·입력·결과 화면."""

# Standard library imports
from secrets import randbelow

# Third party imports
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.domain.command_generator import CommandProfile
from vim_key_trainer.domain.commands import CommandLesson, CommandSpec
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.services.command_session import (
    CommandSession,
    ContinuousCommandSession,
)
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.components import button, label, scroll_page
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets.command_input import CommandInput


def _number(value: float | None, suffix: str = "") -> str:
    return "—" if value is None else f"{value:.1f}{suffix}"


class CommandPracticePage(QWidget):
    leave_requested = Signal()

    def __init__(self, repository: MemoryResultRepository) -> None:
        super().__init__()
        self.repository = repository
        self.session: CommandSession | None = None
        self.last_result: CommandSessionResult | None = None
        self._switching = False
        self._font_size = 23
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
        page, layout = scroll_page()
        layout.addWidget(label("02 / VIM COMMANDS", "eyebrow"))
        self.title = label("Vim 명령 연습", "sectionTitle")
        layout.addWidget(self.title)
        self.instruction = label("", "muted", wrap=True)
        layout.addWidget(self.instruction)
        metric_row = QHBoxLayout()
        self.metrics: dict[str, QLabel] = {}
        for key, name in (
            ("progress", "완료 명령"),
            ("accuracy", "정확도"),
            ("speed", "명령/분"),
            ("combo", "콤보"),
            ("time", "활성 시간"),
        ):
            column = QVBoxLayout()
            column.addWidget(label(name, "muted"))
            value = label("—", "sectionTitle")
            self.metrics[key] = value
            column.addWidget(value)
            metric_row.addLayout(column, 1)
        layout.addLayout(metric_row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)
        self.practice_input = CommandInput()
        self.practice_input.key_received.connect(self._receive_key)
        self.practice_input.focus_lost.connect(self._focus_lost)
        self.practice_input.composition_blocked.connect(self._composition_blocked)
        layout.addWidget(self.practice_input)
        self.feedback = label("", "muted", wrap=True)
        self.feedback.setMinimumHeight(22)
        actions = QHBoxLayout()
        self.start_button = button("연습 시작", "startCommands", primary=True)
        self.start_button.clicked.connect(self.start_practice)
        actions.addWidget(self.start_button)
        self.pause_button = button("일시정지", "pauseCommands")
        self.pause_button.clicked.connect(self.toggle_pause)
        actions.addWidget(self.pause_button)
        self.retry_button = button("같은 문제 다시", "retryCommands")
        self.retry_button.clicked.connect(self.retry)
        actions.addWidget(self.retry_button)
        self.new_problem_button = button("다른 문제", "newCommandProblem")
        self.new_problem_button.clicked.connect(self.new_problem)
        actions.addWidget(self.new_problem_button)
        self.finish_button = button("연습 마치기", "finishCommands")
        self.finish_button.setToolTip("연속 연습을 끝내고 결과를 봅니다.")
        self.finish_button.clicked.connect(self.finish_practice)
        actions.addWidget(self.finish_button)
        actions.addStretch()
        leave = button("Vim 명령 선택", "leaveCommands")
        leave.clicked.connect(self.leave_requested.emit)
        actions.addWidget(leave)
        layout.addLayout(actions)
        layout.addWidget(self.feedback)
        layout.addWidget(
            label(
                "명령 암기 연습입니다. 항목마다 독립된 문맥이며 문서를 편집하거나 "
                "매크로·클립보드를 실행하지 않습니다.\n"
                "<Esc>·<Enter>·<Backspace>는 실제 키, <C-r>는 실제 Control+R입니다. "
                "macOS에서도 Command가 아닌 Control을 누르세요.",
                "muted",
                wrap=True,
            )
        )
        layout.addStretch()
        return page

    def _make_result_page(self) -> QWidget:
        page, result_layout = scroll_page()
        result_layout.addWidget(label("COMMAND PRACTICE COMPLETE", "eyebrow"))
        result_layout.addWidget(label("명령 연습을 마쳤어요!", "title"))
        self.result_stars = label("", "stars")
        result_layout.addWidget(self.result_stars)
        self.result_summary = label("", wrap=True)
        result_layout.addWidget(self.result_summary)
        result_actions = QHBoxLayout()
        self.result_retry_button = button(
            "같은 문제 재도전", "retryCommandResult", primary=True
        )
        self.result_retry_button.clicked.connect(self.retry)
        result_actions.addWidget(self.result_retry_button)
        self.new_button = button("새 문제로 연습", "newCommands")
        self.new_button.clicked.connect(self.new_problem)
        result_actions.addWidget(self.new_button)
        home = button("Vim 명령 선택", "commandResultHome")
        home.clicked.connect(self.leave_requested.emit)
        result_actions.addWidget(home)
        result_layout.addLayout(result_actions)
        self.result_times_title = label("명령별 완료 시간", "sectionTitle")
        result_layout.addWidget(self.result_times_title)
        self.result_times = label("", wrap=True)
        result_layout.addWidget(self.result_times)
        self.result_errors = label("", "muted", wrap=True)
        result_layout.addWidget(self.result_errors)
        result_layout.addWidget(
            label(
                "별: 연습 완료 ★ · 정확도 95% 이상 ★★ · 100% ★★★\n"
                "같은 생성 규칙·seed·완료 명령 수·입력 조건에서 "
                "정확도, 활성 시간 순으로 개인 기록을 비교합니다.\n"
                "기록은 이번 실행 동안만 유지됩니다.",
                "muted",
                wrap=True,
            )
        )
        result_layout.addStretch()
        return page

    def prepare(
        self,
        lesson: CommandLesson | CommandProfile,
        spec: CommandSpec | None = None,
        *,
        font_size: int = 23,
    ) -> None:
        self._switching = True
        try:
            self.abort()
            if isinstance(lesson, CommandProfile):
                spec = spec or CommandSpec(lesson.id, seed=randbelow(2**32))
                self.session = ContinuousCommandSession(lesson, spec)
            else:
                self.session = CommandSession(lesson, spec)
            self.last_result = None
            self._font_size = font_size
            self.title.setText(lesson.title)
            self.instruction.setText(
                f"{lesson.display_count}개씩 무작위 조합 · 자동 보충 · "
                "연습 마치기까지 계속됩니다. 항목 사이 공백·줄바꿈은 입력하지 않습니다."
                if self.session.continuous
                else f"{len(self.session.items)}개 명령 · "
                f"{lesson.display_count}개씩 표시 · "
                "강조된 키부터 순서대로 입력하세요. "
                "항목 사이 공백·줄바꿈은 입력하지 않습니다."
            )
            self.feedback.setText("연습 시작 후 첫 정답 또는 오타부터 시간을 잽니다.")
            self.practice_input.font_size = font_size
            self.practice_input.paused = False
            self.practice_input.setEnabled(False)
            self.start_button.show()
            self.pause_button.setEnabled(False)
            self.pause_button.setText("일시정지")
            self.finish_button.setVisible(self.session.continuous)
            self.finish_button.setEnabled(False)
            self.finish_button.setText("연습 마치기")
            self.progress.setVisible(not self.session.continuous)
            self.progress.setRange(0, len(self.session.target))
            self.stack.setCurrentWidget(self.practice_page)
            self._refresh()
            self.start_button.setFocus()
        finally:
            self._switching = False

    def start_practice(self) -> None:
        if self.session is None or self.session.state != SessionState.READY:
            return
        self.start_button.hide()
        self.practice_input.setEnabled(True)
        self.practice_input.setFocus()
        self.pause_button.setEnabled(True)
        self.feedback.setText("강조된 키부터 입력하세요. 첫 입력을 기다리고 있습니다.")
        self.timer.start()

    def _receive_key(self, normalized: NormalizedKey) -> None:
        session = self.session
        if session is None or self.start_button.isVisible():
            return
        if session.state not in {SessionState.READY, SessionState.RUNNING}:
            return
        expected = session.expected_token
        outcome = session.submit(normalized.token, keypad=normalized.keypad)
        if outcome == InputResult.ACCEPTED:
            self.feedback.setText("✓ 정확해요. 다음 키를 이어서 입력하세요.")
        elif outcome == InputResult.REJECTED and expected is not None:
            self.feedback.setText(
                f"! 다음 목표는 {expected.display}입니다. "
                "같은 위치에서 다시 입력하세요."
            )
        else:
            reasons = {
                "auto_repeat": "길게 누르기의 자동 반복은 제외합니다.",
                "paste": "붙여넣기 대신 한 키씩 입력하세요.",
                "multiple_characters": "한 번에 여러 문자를 입력할 수 없습니다.",
                "non_ascii": "영문 입력 모드로 전환해 주세요.",
                "modifier": "Shift·Control 등은 단독으로 세지 않습니다.",
                "unsupported_key": "이 키는 연습에서 사용하지 않습니다.",
            }
            self.feedback.setText(
                "입력 제외 · "
                + reasons.get(
                    normalized.reason or "", "Backspace는 목표일 때만 입력합니다."
                )
            )
        self._refresh()
        if session.state == SessionState.COMPLETED:
            self._finish()
        elif isinstance(session, ContinuousCommandSession) and session.finish_requested:
            self.feedback.setText(
                "현재 명령을 끝내면 결과를 표시합니다. 강조된 키를 이어서 입력하세요."
            )

    def _composition_blocked(self) -> None:
        self.feedback.setText("입력 제외 · 영문 입력 모드에서 한 키씩 눌러 주세요.")

    def _refresh(self) -> None:
        session = self.session
        if session is None:
            return
        self.practice_input.show_commands(
            session.items,
            session.command_index,
            session.token_index,
            session.lesson.display_count,
            session.page_start_count
            if isinstance(session, ContinuousCommandSession)
            else 0,
        )
        self._refresh_metrics()

    def _refresh_metrics(self) -> None:
        session = self.session
        if session is None:
            return
        for key, value in {
            "progress": (
                f"{session.completed_commands}개"
                if session.continuous
                else f"{session.completed_commands}/{len(session.items)}"
            ),
            "accuracy": _number(session.accuracy, "%"),
            "speed": _number(session.commands_per_minute),
            "combo": str(session.combo),
            "time": f"{session.elapsed_seconds:.1f}초",
        }.items():
            self.metrics[key].setText(value)
        if not session.continuous:
            self.progress.setValue(session.position)
        self.finish_button.setEnabled(
            session.continuous
            and session.state in {SessionState.RUNNING, SessionState.PAUSED}
            and session.position + session.incorrect > 0
        )
        finish_pending = (
            isinstance(session, ContinuousCommandSession)
            and session.finish_requested
            and self.finish_button.isEnabled()
        )
        if self.finish_button.property("emphasized") != finish_pending:
            self.finish_button.setProperty("emphasized", finish_pending)
            style = self.finish_button.style()
            style.unpolish(self.finish_button)
            style.polish(self.finish_button)
            self.finish_button.update()
        self.finish_button.setText(
            "현재 명령 후 마치기" if finish_pending else "연습 마치기"
        )

    def _focus_lost(self, reason: Qt.FocusReason) -> None:
        # 버튼 클릭은 clicked에서 정지·종료한다. 그 밖의 포커스 이동은 정지한다.
        if reason == Qt.FocusReason.MouseFocusReason and QApplication.focusWidget() in (
            self.pause_button,
            self.finish_button,
        ):
            return
        if not self._switching and not self.start_button.isVisible():
            self.pause()

    def pause(self) -> None:
        if self.session is None or self.session.state not in {
            SessionState.READY,
            SessionState.RUNNING,
        }:
            return
        self.session.pause()
        self.timer.stop()
        self.practice_input.paused = True
        self.practice_input.update()
        self.pause_button.setText("연습 재개")
        self.feedback.setText(
            "일시정지 · 이 시간은 연습 시간에서 제외됩니다. 재개 버튼으로 돌아오세요."
        )
        self._refresh_metrics()

    def toggle_pause(self) -> None:
        if self.session is None:
            return
        if self.session.state == SessionState.PAUSED:
            self.session.resume()
            self.practice_input.paused = False
            self.practice_input.update()
            self.pause_button.setText("일시정지")
            self.feedback.setText("이어서 입력하세요. 일시정지 전의 콤보는 유지됩니다.")
            self.practice_input.setFocus()
            self.timer.start()
        else:
            self.pause()

    def abort(self) -> None:
        self.timer.stop()
        if self.session is not None:
            self.session.abort()

    def finish_practice(self) -> None:
        session = self.session
        if not isinstance(session, ContinuousCommandSession):
            return
        finished = session.finish()
        self._refresh_metrics()
        if finished:
            self._refresh()
            self._finish()
        elif session.finish_requested:
            self.feedback.setText(
                "현재 명령을 끝내면 결과를 표시합니다. "
                + (
                    "연습 재개를 눌러 이어서 입력하세요."
                    if session.state == SessionState.PAUSED
                    else "강조된 키를 이어서 입력하세요."
                )
            )
            if session.state == SessionState.RUNNING:
                self.practice_input.setFocus()

    def _finish(self) -> None:
        session = self.session
        if session is None or session.result is None:
            return
        result = session.result
        self.last_result = result
        new_best = self.repository.save(result)
        self.timer.stop()
        self.result_stars.setText("★" * result.stars + "☆" * (3 - result.stars))
        completed = (
            f"{result.completed_commands}개 명령 완료"
            if session.continuous
            else f"{result.completed_commands}/{len(session.items)}개 완료"
        )
        record_message = (
            "같은 조건의 개인 기록을 세웠어요!" if new_best else "연습을 완료했어요."
        )
        self.result_summary.setText(
            f"{session.lesson.title} · {completed}\n"
            f"정확도 {_number(result.accuracy, '%')} · "
            f"명령/분 {_number(result.commands_per_minute)}\n"
            f"활성 연습 시간 {result.elapsed_seconds:.1f}초 · "
            f"최대 콤보 {result.max_combo} · "
            f"정답 {result.correct}키 / 오답 {result.incorrect}키\n"
            f"{record_message}"
        )
        if session.continuous:
            self.result_times_title.setText(
                f"최근 {len(result.command_samples)}개 명령의 완료 시간"
            )
            start_number = result.completed_commands - len(result.command_samples) + 1
            self.result_times.setText(
                "\n".join(
                    f"{start_number + index:02}. {sample.display}  ·  "
                    f"{sample.seconds:.2f}초"
                    for index, sample in enumerate(result.command_samples)
                )
            )
        else:
            self.result_times_title.setText("명령별 완료 시간")
            items = {item.id: item for item in session.items}
            self.result_times.setText(
                "\n".join(
                    f"{index + 1:02}. {items[item_id].display}  ·  {seconds:.2f}초"
                    for index, (item_id, seconds) in enumerate(result.command_times)
                )
            )
        errors = sorted(result.errors.items(), key=lambda item: item[1], reverse=True)[
            :5
        ]
        self.result_errors.setText(
            (
                "다시 살펴볼 목표 키: "
                + " · ".join(f"{key} {count}회" for key, count in errors)
                if errors
                else "오타 없이 완주했어요!"
            )
            + f"\n일시정지 {result.pause_count}회 · "
            "명령 시간은 첫 채점 입력부터 완료까지이며 일시정지를 제외합니다."
        )
        self._switching = True
        try:
            self.stack.setCurrentWidget(self.result_page)
        finally:
            self._switching = False

    def retry(self) -> None:
        if self.session is not None:
            self.prepare(
                self.session.profile
                if isinstance(self.session, ContinuousCommandSession)
                else self.session.lesson,
                self.session.spec,
                font_size=self._font_size,
            )

    def new_problem(self) -> None:
        if self.session is not None:
            self.prepare(
                self.session.profile
                if isinstance(self.session, ContinuousCommandSession)
                else self.session.lesson,
                CommandSpec(
                    self.session.spec.lesson_id, seed=self.session.spec.seed + 1
                ),
                font_size=self._font_size,
            )
