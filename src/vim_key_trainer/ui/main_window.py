"""메뉴 → 준비 → 연속 입력 → 결과의 첫 학습 흐름."""

# Standard library imports
from secrets import randbelow

# Third party imports
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.domain.exercises import EXERCISES, PracticeSpec
from vim_key_trainer.domain.sessions import InputResult, SessionResult, SessionState
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.session_service import PracticeSession
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets.practice_input import PracticeInput


def label(text: str, role: str = "", *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, name: str = "", *, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName("primary" if primary else name)
    if name:
        widget.setAccessibleName(name)
    widget.setAutoDefault(False)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(10)
    return frame, layout


def percentage(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("vim-key-trainer · 매일 조금씩, 손에 익는 Vim")
        self.resize(1200, 800)
        self.setMinimumSize(960, 680)
        self.session: PracticeSession | None = None
        self.repository = MemoryResultRepository()
        self.last_result: SessionResult | None = None
        self._switching = False
        self._keyboard_labels: dict[str, QLabel] = {}
        self._result_metrics: dict[str, QLabel] = {}
        self._metric_labels: dict[str, QLabel] = {}
        self._lesson_stars: dict[str, QLabel] = {}

        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._make_sidebar())
        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        shell.addWidget(self.stack, 1)
        self.home_page = self._make_home()
        self.practice_page = self._make_practice()
        self.result_page = self._make_result()
        self.diagnostic_page = self._make_diagnostics()
        self.settings_page = self._make_settings()
        for page in (
            self.home_page,
            self.practice_page,
            self.result_page,
            self.diagnostic_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._refresh_metrics)
        self.stack.setCurrentWidget(self.home_page)

    def _make_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(195)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 30, 20, 24)
        layout.setSpacing(14)
        layout.addWidget(label("vim_", "brand"))
        layout.addWidget(label("KEY TRAINER", "muted"))
        layout.addSpacing(30)
        self.home_button = button("⌂   연습 메뉴", "nav")
        self.home_button.clicked.connect(self.show_home)
        layout.addWidget(self.home_button)
        diagnostic_button = button("⌨   키 입력 진단", "nav")
        diagnostic_button.clicked.connect(self.show_diagnostics)
        layout.addWidget(diagnostic_button)
        settings_button = button("⚙   연습 설정", "nav")
        settings_button.clicked.connect(self.show_settings)
        layout.addWidget(settings_button)
        layout.addStretch()
        layout.addWidget(label("작은 연습, 익숙한 움직임", "muted", wrap=True))
        layout.addWidget(label("LOCAL · OFFLINE\nv0.1  /  기본 연습", "muted"))
        return sidebar

    def _page(
        self, eyebrow: str, title: str, description: str
    ) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 26)
        layout.setSpacing(16)
        layout.addWidget(label(eyebrow, "eyebrow"))
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(description, "muted", wrap=True))
        scroll.setWidget(content)
        return page, layout

    def _make_home(self) -> QWidget:
        page, layout = self._page(
            "YOUR DAILY PRACTICE",
            "Vim, 손끝부터 익혀 보세요.",
            "숫자와 기호부터 차근차근. 속도보다 정확하게, 짧게 반복하세요.",
        )
        stages = QHBoxLayout()
        for number, title, detail in (
            ("01 · 지금 시작", "숫자·기호", "키 위치와 연속 입력 익히기"),
            ("02 · 준비 중", "Vim 명령", "명령을 입력하며 의미 익히기"),
            ("03 · 준비 중", "문서 수정", "목표 문서로 바꾸며 응용하기"),
        ):
            frame, box = card()
            box.addWidget(
                label(number, "eyebrow" if number.startswith("01") else "muted")
            )
            box.addWidget(label(title, "sectionTitle"))
            box.addWidget(label(detail, "muted", wrap=True))
            stages.addWidget(frame)
        layout.addLayout(stages)
        header = QHBoxLayout()
        header.addWidget(label("오늘의 기본 연습", "sectionTitle"))
        header.addStretch()
        self.home_summary = label("이번 실행에서 완료 0회", "muted")
        header.addWidget(self.home_summary)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(12)
        examples = ("1234567890", "!@#$%^&*()", "[]{} <> / ? : ;", "3$7[2!9]0%")
        for index, exercise in enumerate(EXERCISES):
            frame, box = card()
            top = QHBoxLayout()
            top.addWidget(label(exercise.title, "sectionTitle"))
            top.addStretch()
            stars = label("☆☆☆", "eyebrow")
            self._lesson_stars[exercise.id] = stars
            top.addWidget(stars)
            box.addLayout(top)
            box.addWidget(label(examples[index], "brand"))
            box.addWidget(label(exercise.description, "muted", wrap=True))
            start = button("연습 준비  →", f"lesson_{exercise.id}")
            start.clicked.connect(
                lambda checked=False, key=exercise.id: self.prepare_practice(key)
            )
            box.addWidget(start)
            grid.addWidget(frame, index // 2, index % 2)
        layout.addLayout(grid)
        layout.addWidget(
            label(
                "계정 없이 로컬에서 연습합니다. 현재 기록은 앱을 닫을 때 초기화됩니다.",
                "muted",
                wrap=True,
            )
        )
        return page

    def _make_practice(self) -> QWidget:
        page, layout = self._page(
            "01 / NUMBERS & SYMBOLS",
            "숫자 연습",
            "영문 입력 모드 · US QWERTY 기준",
        )
        # 페이지 헤더를 준비한 뒤 레슨별 제목으로 갱신한다.
        titles = page.findChildren(QLabel, "title")
        self.practice_title = titles[0]
        self.practice_instruction = label(
            "강조된 문자부터 차례대로 입력하세요.", "muted", wrap=True
        )
        layout.addWidget(self.practice_instruction)
        metrics = QHBoxLayout()
        for key, title in (
            ("progress", "진행"),
            ("accuracy", "정확도"),
            ("cpm", "CPM"),
            ("combo", "현재 콤보"),
            ("time", "활성 시간"),
        ):
            frame, box = card()
            box.setContentsMargins(14, 12, 14, 12)
            box.addWidget(label(title, "muted"))
            value = label("—", "metric")
            self._metric_labels[key] = value
            box.addWidget(value)
            metrics.addWidget(frame)
        layout.addLayout(metrics)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.practice_input = PracticeInput()
        self.practice_input.key_received.connect(self._receive_key)
        self.practice_input.key_released.connect(self._update_target)
        self.practice_input.focus_lost.connect(self._focus_lost)
        self.practice_input.composition_blocked.connect(self._composition_blocked)
        layout.addWidget(self.practice_input)
        self.feedback = label(
            "준비되면 아래 시작 버튼을 누르세요. 첫 입력부터 시간을 잽니다.",
            "muted",
            wrap=True,
        )
        self.feedback.setMinimumHeight(26)
        layout.addWidget(self.feedback)

        keyboard, key_box = card()
        key_box.setContentsMargins(16, 12, 16, 12)
        key_box.addWidget(
            label("다음 목표 키 · 초록색 강조 / 실제 입력 · 테두리 표시", "muted")
        )
        for row in (
            ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="),
            ("[", "]", "\\", ";", "'", ",", ".", "/", "`", "Shift"),
        ):
            keys = QHBoxLayout()
            keys.setSpacing(5)
            for character in row:
                key_label = label(character)
                key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                key_label.setMinimumHeight(32)
                self._keyboard_labels[character] = key_label
                keys.addWidget(key_label)
            key_box.addLayout(keys)
        layout.addWidget(keyboard)
        actions = QHBoxLayout()
        self.start_button = button("연습 시작", "startPractice", primary=True)
        self.start_button.clicked.connect(self.start_practice)
        actions.addWidget(self.start_button)
        self.pause_button = button("일시정지", "pausePractice")
        self.pause_button.clicked.connect(self.toggle_pause)
        actions.addWidget(self.pause_button)
        self.restart_button = button("같은 문제 다시", "restartPractice")
        self.restart_button.clicked.connect(self.retry)
        actions.addWidget(self.restart_button)
        actions.addStretch()
        leave = button("메뉴로", "leavePractice")
        leave.clicked.connect(self.show_home)
        actions.addWidget(leave)
        # 작은 창에서도 일시정지·나가기 버튼을 입력 영역 바로 아래에 둔다.
        layout.insertLayout(layout.indexOf(keyboard), actions)
        layout.addWidget(
            label(
                "오타는 그 자리에서 다시 입력 · Backspace 무시 · "
                "자동 반복·붙여넣기 제외\n"
                "키패드는 감지 가능한 경우에만 안내하며, "
                "물리 키 위치를 추정하지 않습니다.",
                "muted",
                wrap=True,
            )
        )
        layout.addStretch()
        return page

    def _make_result(self) -> QWidget:
        page, layout = self._page(
            "PRACTICE COMPLETE",
            "잘 마쳤어요!",
            "오늘의 작은 반복이 다음 입력을 더 편하게 만듭니다.",
        )
        self.result_stars = label("★★★", "stars")
        self.result_stars.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.result_stars)
        self.result_note = label("", "muted", wrap=True)
        self.result_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.result_note)
        grid = QGridLayout()
        for index, (key, title) in enumerate(
            (
                ("accuracy", "입력 정확도"),
                ("cpm", "CPM · 정답 문자/분"),
                ("time", "활성 연습 시간"),
                ("combo", "최대 콤보"),
            )
        ):
            frame, box = card()
            box.addWidget(label(title, "muted"))
            value = label("—", "metric")
            self._result_metrics[key] = value
            box.addWidget(value)
            grid.addWidget(frame, index // 2, index % 2)
        layout.addLayout(grid)
        self.error_summary = label("", "muted", wrap=True)
        layout.addWidget(self.error_summary)
        layout.addWidget(
            label(
                "별 기준: 완주 ★ · 정확도 95% 이상 ★★ · 100% ★★★\n"
                "개인 기록은 같은 문제·설정·일시정지 사용 조건에서 "
                "정확도, 활성 시간 순으로 비교합니다.",
                "muted",
                wrap=True,
            )
        )
        actions = QHBoxLayout()
        retry = button("같은 문제 재도전", "retryResult", primary=True)
        retry.clicked.connect(self.retry)
        actions.addWidget(retry)
        fresh = button("새 문제", "newProblem")
        fresh.clicked.connect(self.new_problem)
        actions.addWidget(fresh)
        home = button("연습 메뉴", "resultHome")
        home.clicked.connect(self.show_home)
        actions.addWidget(home)
        layout.addLayout(actions)
        layout.addWidget(
            label(
                "이번 실행 동안의 기록입니다. 영구 저장은 후속 단계에서 추가됩니다.",
                "muted",
            )
        )
        layout.addStretch()
        return page

    def _make_diagnostics(self) -> QWidget:
        page, layout = self._page(
            "INPUT DIAGNOSTICS",
            "키 입력 진단",
            "키 이벤트가 연습용 논리 키로 변환되는 값을 확인합니다. "
            "진단 입력은 채점하지 않습니다.",
        )
        self.diagnostic_input = PracticeInput()
        self.diagnostic_input.diagnostic = True
        self.diagnostic_input.setObjectName("diagnosticInput")
        self.diagnostic_input.key_received.connect(self._diagnose_key)
        layout.addWidget(self.diagnostic_input)
        frame, box = card()
        self.diagnostic_text = label(
            "숫자, Shift+기호, Esc, Enter, Backspace, 실제 Control+R을 눌러 보세요.",
            wrap=True,
        )
        self.diagnostic_text.setMinimumHeight(180)
        box.addWidget(self.diagnostic_text)
        layout.addWidget(frame)
        layout.addWidget(
            label(
                "macOS: Qt Control은 Command, Qt Meta는 실제 Control로 해석합니다.\n"
                "KeypadModifier로 감지한 숫자만 키패드로 표시합니다. "
                "Native scan code는 OS 공통 위치로 해석하지 않습니다.\n"
                "앱 창 밖에서는 키를 수집하지 않으며 "
                "입력 내용은 파일에 저장하지 않습니다.",
                "muted",
                wrap=True,
            )
        )
        home = button("메뉴로", "diagnosticHome")
        home.clicked.connect(self.show_home)
        layout.addWidget(home)
        layout.addStretch()
        return page

    def _make_settings(self) -> QWidget:
        page, layout = self._page(
            "PRACTICE SETTINGS",
            "나에게 맞는 연습",
            "다음 연습부터 적용합니다. 현재 설정은 앱을 닫을 때 초기화됩니다.",
        )
        frame, box = card()
        box.addWidget(label("총 목표 길이", "sectionTitle"))
        self.length_combo = QComboBox()
        self.length_combo.setObjectName("targetLength")
        self.length_combo.setAccessibleName("총 목표 길이")
        for length in (20, 50, 100, 200):
            self.length_combo.addItem(f"{length}자", length)
        self.length_combo.setCurrentIndex(2)
        box.addWidget(self.length_combo)
        box.addWidget(label("한 번에 표시할 문자 수", "sectionTitle"))
        self.width_combo = QComboBox()
        self.width_combo.setObjectName("displayWidth")
        self.width_combo.setAccessibleName("표시 문자 수")
        for width in (10, 20, 40):
            self.width_combo.addItem(f"{width}자", width)
        self.width_combo.setCurrentIndex(1)
        box.addWidget(self.width_combo)
        box.addWidget(label("연습 문자 크기", "sectionTitle"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(16, 30)
        self.font_spin.setValue(23)
        self.font_spin.setSuffix(" pt")
        self.font_spin.setAccessibleName("연습 문자 크기")
        box.addWidget(self.font_spin)
        box.addWidget(
            label(
                "좁은 창에서는 여러 문자가 함께 보이도록 크기를 자동 조절합니다.",
                "muted",
                wrap=True,
            )
        )
        layout.addWidget(frame)
        layout.addWidget(
            label(
                "효과음은 사용하지 않습니다. 현재 화면에는 움직이는 연출이 없습니다.",
                "muted",
                wrap=True,
            )
        )
        home = button("설정 적용 · 메뉴로", "settingsHome", primary=True)
        home.clicked.connect(self.show_home)
        layout.addWidget(home)
        layout.addStretch()
        return page

    def _navigate(self, page: QWidget) -> None:
        self._switching = True
        try:
            if self.session is not None:
                self.session.abort()
            self.timer.stop()
            self.stack.setCurrentWidget(page)
        finally:
            self._switching = False

    def show_home(self) -> None:
        self._navigate(self.home_page)
        self.home_summary.setText(
            f"이번 실행에서 완료 {self.repository.completed_count}회"
        )
        for exercise_id, widget in self._lesson_stars.items():
            stars = self.repository.best_stars(exercise_id)
            widget.setText("★" * stars + "☆" * (3 - stars))

    def show_diagnostics(self) -> None:
        self._navigate(self.diagnostic_page)
        self.diagnostic_input.setFocus()

    def show_settings(self) -> None:
        self._navigate(self.settings_page)

    def prepare_practice(
        self, exercise_id: str, spec: PracticeSpec | None = None
    ) -> None:
        self._navigate(self.practice_page)
        if spec is None:
            spec = PracticeSpec(
                exercise_id=exercise_id,
                target_length=int(self.length_combo.currentData()),
                display_width=int(self.width_combo.currentData()),
                seed=randbelow(2**32),
            )
        self.session = PracticeSession(spec)
        self.practice_title.setText(self.session.exercise.title)
        self.practice_instruction.setText(
            f"총 {len(self.session.target)}자 · {spec.display_width}자씩 표시 · "
            "초록색 문자를 순서대로 입력하세요. 구분선·줄바꿈은 입력하지 않습니다."
        )
        self.practice_input.font_size = self.font_spin.value()
        self.practice_input.paused = False
        self.practice_input.setEnabled(False)
        self.start_button.show()
        self.pause_button.setEnabled(False)
        self.pause_button.setText("일시정지")
        self.feedback.setText(
            "준비되면 연습 시작을 누르세요. 첫 정답 또는 오타부터 시간을 잽니다."
        )
        self.progress.setRange(0, len(self.session.target))
        self._refresh_metrics()
        self._update_target()
        self.start_button.setFocus()

    def start_practice(self) -> None:
        if self.session is None:
            return
        self.start_button.hide()
        self.practice_input.setEnabled(True)
        self.practice_input.setFocus()
        self.pause_button.setEnabled(True)
        self.feedback.setText(
            "강조된 문자부터 입력하세요. 첫 입력을 기다리고 있습니다."
        )
        self.timer.start()

    def _receive_key(self, normalized: NormalizedKey) -> None:
        if self.session is None or self.session.state == SessionState.PAUSED:
            return
        expected = self.session.target[
            self.session.position : self.session.position + 1
        ]
        outcome = self.session.submit(normalized.token, keypad=normalized.keypad)
        if outcome == InputResult.ACCEPTED:
            self.feedback.setText("✓ 정확해요. 다음 문자를 이어서 입력하세요.")
        elif outcome == InputResult.REJECTED:
            self.feedback.setText(
                "! 키패드 대신 키보드 상단 숫자열을 사용하세요."
                if normalized.keypad
                else f"! 현재 목표는 {expected!r}입니다. 같은 위치에서 다시 입력하세요."
            )
        elif normalized.reason:
            reasons = {
                "auto_repeat": "길게 누르기의 자동 반복은 제외합니다.",
                "paste": "붙여넣기 대신 한 글자씩 입력하세요.",
                "multiple_characters": "한 번에 여러 문자를 입력할 수 없습니다.",
                "non_ascii": "영문 입력 모드로 전환해 주세요.",
                "modifier": "Shift·Control 등은 단독으로 세지 않습니다.",
                "unsupported_key": "이 키는 연습에서 사용하지 않습니다.",
            }
            reason = reasons.get(normalized.reason, "채점하지 않는 키입니다.")
            self.feedback.setText(f"입력 제외 · {reason}")
        else:
            self.feedback.setText("입력 제외 · Backspace는 목표를 되돌리지 않습니다.")
        self._refresh_metrics()
        self._update_target(actual=normalized.text)
        if self.session.state == SessionState.COMPLETED:
            self._finish()

    def _composition_blocked(self) -> None:
        self.feedback.setText(
            "입력 제외 · 영문 입력 모드로 전환하고 한 글자씩 눌러 주세요."
        )

    def _refresh_metrics(self) -> None:
        if self.session is None:
            return
        session = self.session
        values = {
            "progress": f"{session.position}/{len(session.target)}",
            "accuracy": percentage(session.accuracy),
            "cpm": "—" if session.cpm is None else f"{session.cpm:.0f}",
            "combo": str(session.combo),
            "time": f"{session.elapsed_seconds:.1f}초",
        }
        for key, value in values.items():
            self._metric_labels[key].setText(value)
        self.progress.setValue(session.position)

    def _update_target(self, actual: str = "") -> None:
        if self.session is None:
            return
        session = self.session
        self.practice_input.show_target(
            session.target, session.position, session.spec.display_width
        )
        expected = session.target[session.position : session.position + 1]
        shift_map = dict(
            zip('!@#$%^&*()_+{}|:"<>?~', "1234567890-=[]\\;',./`", strict=True)
        )
        physical = shift_map.get(expected, expected)
        actual_key = shift_map.get(actual, actual)
        for key, widget in self._keyboard_labels.items():
            target = key == physical or (key == "Shift" and expected in shift_map)
            border = "#f1c27e" if key == actual_key else "#405168"
            widget.setStyleSheet(
                f"background: {'#c3ef85' if target else '#243041'}; "
                f"color: {'#17220e' if target else '#bdc8d6'}; "
                f"border: 2px solid {border}; border-radius: 5px;"
            )

    def _focus_lost(self) -> None:
        # 일시정지 버튼 클릭은 클릭 핸들러가 직접 처리한다.
        if QApplication.focusWidget() is self.pause_button:
            return
        if not self._switching and not self.start_button.isVisible():
            self._pause()

    def _pause(self) -> None:
        if self.session is None or self.session.state not in (
            SessionState.READY,
            SessionState.RUNNING,
        ):
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
            self._pause()

    def changeEvent(self, event: QEvent) -> None:
        # focusOut과 별개로 앱/창 비활성화에도 동일한 멱등 pause 경로를 사용한다.
        if event.type() == QEvent.Type.ActivationChange:
            if (
                not self.isActiveWindow()
                and hasattr(self, "stack")
                and hasattr(self, "practice_page")
            ):
                if (
                    self.stack.currentWidget() == self.practice_page
                    and not self.start_button.isVisible()
                ):
                    self._pause()
        super().changeEvent(event)

    def _finish(self) -> None:
        if self.session is None or self.session.result is None:
            return
        result = self.session.result
        self.last_result = result
        new_best = self.repository.save(result)
        self.timer.stop()
        self.result_stars.setText("★" * result.stars + "☆" * (3 - result.stars))
        self.result_note.setText(
            f"{self.session.exercise.title} · {result.correct}자 완료 · "
            + (
                "같은 조건의 개인 기록을 세웠어요!"
                if new_best
                else "연습을 완료했어요."
            )
        )
        for key, value in {
            "accuracy": percentage(result.accuracy),
            "cpm": "—" if result.cpm is None else f"{result.cpm:.0f}",
            "time": f"{result.elapsed_seconds:.1f}초",
            "combo": f"{result.max_combo}연속",
        }.items():
            self._result_metrics[key].setText(value)
        common = sorted(result.errors.items(), key=lambda item: item[1], reverse=True)[
            :5
        ]
        self.error_summary.setText(
            (
                "다시 살펴볼 목표 키: "
                + " · ".join(f"{key!r} {count}회" for key, count in common)
                if common
                else "오타 없이 완주했어요!"
            )
            + f"\n키패드 위치 오류 {result.keypad_errors}회 · "
            + f"일시정지 {result.pause_count}회"
        )
        self._switching = True
        try:
            self.stack.setCurrentWidget(self.result_page)
        finally:
            self._switching = False

    def retry(self) -> None:
        if self.session is not None:
            self.prepare_practice(self.session.spec.exercise_id, self.session.spec)

    def new_problem(self) -> None:
        if self.session is not None:
            previous = self.session.spec
            self.prepare_practice(
                previous.exercise_id,
                PracticeSpec(
                    exercise_id=previous.exercise_id,
                    target_length=previous.target_length,
                    display_width=previous.display_width,
                    seed=(previous.seed + 1) % 2**32,
                ),
            )

    def _diagnose_key(self, normalized: NormalizedKey) -> None:
        token = normalized.token
        self.diagnostic_text.setText(
            f"결과 문자: {normalized.text!r}\n"
            f"논리 키: {token.kind + ' / ' + token.value if token else '무시'}\n"
            f"Modifier: {', '.join(normalized.modifiers) or '없음'}\n"
            f"키패드 숫자: {'예' if normalized.keypad else '아니요 / 위치 확인 불가'}\n"
            f"자동 반복: {normalized.auto_repeat}\n"
            f"Native scan code: {normalized.native_scan_code}\n"
            f"제외 이유: {normalized.reason or '없음'}"
        )
