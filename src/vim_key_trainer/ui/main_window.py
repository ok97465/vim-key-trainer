"""메뉴 → 준비 → 연속 입력 → 결과의 첫 학습 흐름."""

# Standard library imports
from secrets import randbelow

# Third party imports
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.content.document_missions import list_document_missions
from vim_key_trainer.domain.command_generator import (
    get_command_profile,
    list_command_profiles,
)
from vim_key_trainer.domain.commands import CommandSpec
from vim_key_trainer.domain.document_missions import DocumentPracticeSpec
from vim_key_trainer.domain.edit_weights import (
    EDIT_TECHNIQUES,
    EditTechniqueWeights,
)
from vim_key_trainer.domain.editing import EditLesson, EditPracticeSpec
from vim_key_trainer.domain.exercises import EXERCISES, PracticeSpec
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    InputResult,
    SessionResult,
    SessionState,
)
from vim_key_trainer.services.document_problem_factory import (
    create_random_document_problem,
)
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.result_repository import (
    MemoryResultRepository,
    ResultRepository,
)
from vim_key_trainer.services.session_service import PracticeSession
from vim_key_trainer.ui.command_practice import CommandPracticePage
from vim_key_trainer.ui.components import button, label, scroll_page
from vim_key_trainer.ui.edit_catalog import EditCatalogPage
from vim_key_trainer.ui.edit_practice import EditPracticePage
from vim_key_trainer.ui.qt_input import IGNORED_INPUT_MESSAGES, NormalizedKey
from vim_key_trainer.ui.widgets.practice_input import PracticeInput

_SHIFT_KEYS = dict(zip('!@#$%^&*()_+{}|:"<>?~', "1234567890-=[]\\;',./`", strict=True))


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
    def __init__(self, repository: ResultRepository | None = None) -> None:
        super().__init__()
        self.setWindowTitle("vim-key-trainer · 매일 조금씩, 손에 익는 Vim")
        self.resize(1200, 800)
        self.setMinimumSize(1200, 800)
        self.session: PracticeSession | None = None
        self.repository = (
            repository if repository is not None else MemoryResultRepository()
        )
        self._storage_startup_error: str | None = None
        self.last_result: SessionResult | None = None
        self._switching = False
        self._keyboard_labels: dict[str, QLabel] = {}
        self._result_metrics: dict[str, QLabel] = {}
        self._metric_labels: dict[str, QLabel] = {}
        self._lesson_stars: dict[str, QLabel] = {}
        self._command_lesson_stars: dict[tuple[str, int], QLabel] = {}
        self._category = "numbers"

        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._make_sidebar())
        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        shell.addWidget(self.stack, 1)
        self.numbers_page = self._make_numbers_menu()
        self.commands_menu_page = self._make_commands_menu()
        self.editing_page = EditCatalogPage()
        self.editing_page.practice_requested.connect(self.prepare_editing)
        self.editing_page.random_practice_requested.connect(
            self.prepare_random_document
        )
        self.editing_page.numbers_requested.connect(self.show_numbers)
        self.editing_page.commands_requested.connect(self.show_commands_menu)
        self.editing_summary = self.editing_page.summary
        self.practice_page = self._make_practice()
        self.command_page = CommandPracticePage(self.repository)
        self.command_page.leave_requested.connect(self.show_commands_menu)
        self.edit_practice = EditPracticePage(
            self.repository, technique_weights=self._edit_weights
        )
        self.edit_practice.leave_requested.connect(self.show_editing)
        self.result_page = self._make_result()
        self.diagnostic_page = self._make_diagnostics()
        self.settings_page = self._make_settings()
        for page in (
            self.numbers_page,
            self.commands_menu_page,
            self.editing_page,
            self.practice_page,
            self.command_page,
            self.edit_practice,
            self.result_page,
            self.diagnostic_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._refresh_metrics)
        self.stack.setCurrentWidget(self.numbers_page)
        self.numbers_button.setChecked(True)
        self.storage_timer = QTimer(self)
        self.storage_timer.setInterval(1000)
        self.storage_timer.timeout.connect(self._refresh_storage_status)
        self.storage_timer.start()

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
        self.numbers_button = button("숫자·기호 연습", "nav")
        self.numbers_button.setAccessibleName("navNumbers")
        self.commands_button = button("Vim 명령 연습", "nav")
        self.commands_button.setAccessibleName("navCommands")
        self.editing_button = button("문서 수정 연습", "nav")
        self.editing_button.setAccessibleName("navEditing")
        self.diagnostic_button = button("⌨   키 입력 진단", "nav")
        self.diagnostic_button.setAccessibleName("navDiagnostics")
        self.settings_button = button("⚙   연습 설정", "nav")
        self.settings_button.setAccessibleName("navSettings")
        self.nav_group = QButtonGroup(self)
        for item, handler in (
            (self.numbers_button, self.show_numbers),
            (self.commands_button, self.show_commands_menu),
            (self.editing_button, self.show_editing),
            (self.diagnostic_button, self.show_diagnostics),
            (self.settings_button, self.show_settings),
        ):
            item.setCheckable(True)
            self.nav_group.addButton(item)
            item.clicked.connect(handler)
            layout.addWidget(item)
        layout.addStretch()
        layout.addWidget(label("작은 연습, 익숙한 움직임", "muted", wrap=True))
        self.storage_status = label("학습 기록", "muted", wrap=True)
        layout.addWidget(self.storage_status)
        self.storage_retry_button = button("기록 저장 재시도", "retryRecordStorage")
        self.storage_retry_button.clicked.connect(self._retry_storage)
        self.storage_retry_button.hide()
        layout.addWidget(self.storage_retry_button)
        layout.addWidget(label("LOCAL · OFFLINE\nv0.1  /  기본 연습", "muted"))
        return sidebar

    def _page(
        self, eyebrow: str, title: str, description: str
    ) -> tuple[QWidget, QVBoxLayout]:
        page, layout = scroll_page(margins=(32, 28, 32, 26), spacing=16)
        layout.addWidget(label(eyebrow, "eyebrow"))
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(description, "muted", wrap=True))
        return page, layout

    def _make_numbers_menu(self) -> QWidget:
        page, layout = self._page(
            "01 / NUMBERS & SYMBOLS",
            "숫자·기호 연습",
            "키 위치부터 반복·연속 패턴까지. 익히고 싶은 유형을 골라 연습하세요.",
        )
        header = QHBoxLayout()
        header.addWidget(label(f"{len(EXERCISES)}가지 연습", "sectionTitle"))
        header.addStretch()
        self.home_summary = label("학습 완료 0회", "muted")
        header.addWidget(self.home_summary)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(12)
        for index, exercise in enumerate(EXERCISES):
            frame, box = card()
            box.setContentsMargins(18, 14, 18, 14)
            box.setSpacing(6)
            top = QHBoxLayout()
            top.addWidget(label(exercise.title, "sectionTitle"))
            top.addStretch()
            stars = label("☆☆☆", "eyebrow")
            self._lesson_stars[exercise.id] = stars
            top.addWidget(stars)
            box.addLayout(top)
            box.addWidget(label(exercise.example, "brand"))
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
                "예시의 구분 공백은 입력하지 않습니다. "
                "학습 기록은 로컬 DB에 저장합니다.",
                "muted",
                wrap=True,
            )
        )
        layout.addStretch()
        return page

    def _make_commands_menu(self) -> QWidget:
        page, layout = self._page(
            "02 / VIM COMMANDS",
            "Vim 명령 연습",
            "문법에 맞는 새 조합을 계속 생성합니다. "
            "원하는 명령 계열에 집중하거나 전체를 섞어 연습하세요.",
        )
        header = QHBoxLayout()
        header.addWidget(
            label(f"{len(list_command_profiles())}가지 연습", "sectionTitle")
        )
        header.addStretch()
        self.commands_summary = label("학습 완료 0회", "muted")
        header.addWidget(self.commands_summary)
        layout.addLayout(header)
        commands = QGridLayout()
        commands.setSpacing(12)
        for index, lesson in enumerate(list_command_profiles()):
            frame, box = card()
            box.setContentsMargins(18, 14, 18, 14)
            box.setSpacing(6)
            top = QHBoxLayout()
            top.addWidget(label(lesson.title, "sectionTitle"))
            top.addStretch()
            stars = label("☆☆☆", "eyebrow")
            self._command_lesson_stars[(lesson.id, lesson.content_version)] = stars
            top.addWidget(stars)
            box.addLayout(top)
            box.addWidget(label(lesson.example, "eyebrow", wrap=True))
            box.addWidget(label(lesson.description, "muted", wrap=True))
            box.addWidget(
                label(
                    f"{lesson.display_count}개씩 자동 생성 · 마칠 때까지 계속", "muted"
                )
            )
            start = button("명령 연습 준비  →", f"lesson_{lesson.id}")
            start.clicked.connect(
                lambda checked=False, key=lesson.id: self.prepare_commands(key)
            )
            box.addWidget(start)
            commands.addWidget(frame, index // 2, index % 2)
        layout.addLayout(commands)
        layout.addWidget(
            label(
                "명령 오른쪽의 짧은 뜻을 보며 입력하세요. "
                "연습 마치기까지 10개씩 자동 공급합니다.",
                "muted",
                wrap=True,
            )
        )
        layout.addStretch()
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

        actions = QHBoxLayout()
        self.start_button = button(
            "연습 시작", "startPractice", primary=True, enter_activates=True
        )
        self.start_button.clicked.connect(self.start_practice)
        actions.addWidget(self.start_button)
        self.pause_button = button("일시정지", "pausePractice")
        self.pause_button.clicked.connect(self.toggle_pause)
        actions.addWidget(self.pause_button)
        self.restart_button = button("같은 문제 다시", "restartPractice")
        self.restart_button.clicked.connect(self.retry)
        actions.addWidget(self.restart_button)
        self.new_problem_button = button("다른 문제", "newPracticeProblem")
        self.new_problem_button.clicked.connect(self.new_problem)
        actions.addWidget(self.new_problem_button)
        actions.addStretch()
        leave = button("숫자·기호 선택", "leavePractice")
        leave.clicked.connect(self.show_numbers)
        actions.addWidget(leave)
        layout.addLayout(actions)

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
        self.result_new_button = button(
            "다른 문제", "newProblem", primary=True, enter_activates=True
        )
        self.result_new_button.clicked.connect(self.new_problem)
        actions.addWidget(self.result_new_button)
        self.result_retry_button = button(
            "같은 문제 재도전", "retryResult", enter_activates=True
        )
        self.result_retry_button.clicked.connect(self.retry)
        actions.addWidget(self.result_retry_button)
        home = button("숫자·기호 선택", "resultHome")
        home.clicked.connect(self.show_numbers)
        actions.addWidget(home)
        layout.addLayout(actions)
        layout.addWidget(
            label(
                "학습 기록과 개인 기록은 로컬 DB에 저장합니다.",
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
        box.addWidget(label("숫자·기호의 총 목표 길이", "sectionTitle"))
        self.length_combo = QComboBox()
        self.length_combo.setObjectName("targetLength")
        self.length_combo.setAccessibleName("총 목표 길이")
        for length in (20, 50, 100, 200):
            self.length_combo.addItem(f"{length}자", length)
        self.length_combo.setCurrentIndex(2)
        box.addWidget(self.length_combo)
        box.addWidget(label("숫자·기호의 표시 문자 수", "sectionTitle"))
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
        box.addWidget(
            label(
                "Vim 명령은 10개씩 새 조합을 생성하며 연습 마치기까지 계속됩니다.",
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
        layout.addWidget(self._make_edit_weight_card())
        self.settings_apply_button = button(
            "설정 적용 · 메뉴로", "settingsHome", primary=True
        )
        self.settings_apply_button.clicked.connect(self.show_home)
        layout.addWidget(self.settings_apply_button)
        self._refresh_edit_weight_preview()
        layout.addStretch()
        return page

    def _make_edit_weight_card(self) -> QFrame:
        frame, box = card()
        box.addWidget(label("문서 수정의 기술 비중", "sectionTitle"))
        box.addWidget(
            label(
                "복합 문서 수정에서 중심으로 연습할 기술의 상대 비중입니다. "
                "숫자·단어 등 집중 연습은 해당 기술을 유지하며, "
                "실제 문서는 원문에 적용할 수 있는 기술 안에서 반영합니다. "
                "검색·복사·반복 집중 과제는 복합 연습을 이용하세요.",
                "muted",
                wrap=True,
            )
        )
        box.addWidget(
            label(
                "키 입력 횟수의 비율은 아닙니다. 필수 이동·입력은 다른 과제에도 "
                "함께 쓰입니다. 0인 기술은 중심 과제에서 제외합니다.",
                "muted",
                wrap=True,
            )
        )
        grid = QGridLayout()
        grid.addWidget(label("기술", "muted"), 0, 0)
        grid.addWidget(label("상대 비중", "muted"), 0, 1)
        grid.addWidget(label("환산 비율", "muted"), 0, 2)
        defaults = EditTechniqueWeights()
        self.edit_weight_spins: dict[str, QSpinBox] = {}
        self._edit_weight_percentages: dict[str, QLabel] = {}
        for row, (technique, title) in enumerate(EDIT_TECHNIQUES, start=1):
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setValue(getattr(defaults, technique))
            spin.setObjectName(f"editWeight_{technique}")
            spin.setAccessibleName(f"{title} 연습 비중")
            percentage_label = label("", "muted")
            percentage_label.setAccessibleName(f"{title} 환산 비율")
            self.edit_weight_spins[technique] = spin
            self._edit_weight_percentages[technique] = percentage_label
            grid.addWidget(label(title), row, 0)
            grid.addWidget(spin, row, 1)
            grid.addWidget(percentage_label, row, 2)
            spin.valueChanged.connect(self._refresh_edit_weight_preview)
        grid.setColumnStretch(0, 1)
        box.addLayout(grid)
        self.edit_weight_note = label("", "muted", wrap=True)
        self.edit_weight_note.setAccessibleName("문서 수정 기술 비중 안내")
        box.addWidget(self.edit_weight_note)
        self.reset_edit_weights_button = button(
            "기술 비중 기본값 복원", "resetEditTechniqueWeights"
        )
        self.reset_edit_weights_button.clicked.connect(self._reset_edit_weights)
        box.addWidget(self.reset_edit_weights_button)
        return frame

    def _edit_weights(self) -> EditTechniqueWeights:
        return EditTechniqueWeights(
            **{
                technique: spin.value()
                for technique, spin in self.edit_weight_spins.items()
            }
        )

    def _refresh_edit_weight_preview(self) -> None:
        total = sum(spin.value() for spin in self.edit_weight_spins.values())
        for technique, spin in self.edit_weight_spins.items():
            share = 100 * spin.value() / total if total else 0
            self._edit_weight_percentages[technique].setText(f"{share:.1f}%")
        self.edit_weight_note.setText(
            "합계를 100에 맞출 필요는 없습니다. 다음에 준비하는 새 문제부터 적용합니다."
            if total
            else "연습할 기술을 하나 이상 선택하세요. 모든 비중을 0으로 둘 수 없습니다."
        )
        self.settings_apply_button.setEnabled(total > 0)

    def _reset_edit_weights(self) -> None:
        defaults = EditTechniqueWeights()
        for technique, spin in self.edit_weight_spins.items():
            with QSignalBlocker(spin):
                spin.setValue(getattr(defaults, technique))
        self._refresh_edit_weight_preview()

    def _navigate(self, page: QWidget) -> None:
        self.statusBar().clearMessage()
        self.statusBar().hide()
        self._switching = True
        try:
            if self.session is not None:
                self.session.abort()
                result = self.session.result
                if (
                    result is not None
                    and result.state == SessionState.ABORTED
                    and result.correct + result.incorrect
                ):
                    self.repository.save(result)
            self.command_page.abort()
            self.edit_practice.abort()
            self.timer.stop()
            self.stack.setCurrentWidget(page)
        finally:
            self._switching = False

    def show_home(self) -> None:
        if self._category == "commands":
            self.show_commands_menu()
        elif self._category == "editing":
            self.show_editing()
        else:
            self.show_numbers()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.storage_timer.stop()
        page = self.stack.currentWidget()
        if page is not None:
            self._navigate(page)
        super().closeEvent(event)

    def _refresh_catalogs(self) -> None:
        number_count = sum(
            isinstance(result, SessionResult) and result.state == SessionState.COMPLETED
            for result in self.repository.results
        )
        command_count = sum(
            isinstance(result, CommandSessionResult)
            and result.state == SessionState.COMPLETED
            for result in self.repository.results
        )
        self.home_summary.setText(f"학습 완료 {number_count}회")
        self.commands_summary.setText(f"학습 완료 {command_count}회")
        self.editing_page.refresh(self.repository)
        for exercise_id, widget in self._lesson_stars.items():
            stars = self.repository.best_stars(exercise_id)
            widget.setText("★" * stars + "☆" * (3 - stars))

        for (lesson_id, version), widget in self._command_lesson_stars.items():
            stars = self.repository.best_command_stars(lesson_id, version)
            widget.setText("★" * stars + "☆" * (3 - stars))

    def show_numbers(self) -> None:
        self._category = "numbers"
        self._navigate(self.numbers_page)
        self.numbers_button.setChecked(True)
        self.numbers_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refresh_catalogs()

    def show_commands_menu(self) -> None:
        self._category = "commands"
        self._navigate(self.commands_menu_page)
        self.commands_button.setChecked(True)
        self.commands_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refresh_catalogs()

    def show_editing(self) -> None:
        self._category = "editing"
        self._navigate(self.editing_page)
        self.editing_button.setChecked(True)
        self.editing_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refresh_catalogs()

    def show_diagnostics(self) -> None:
        self._navigate(self.diagnostic_page)
        self.diagnostic_button.setChecked(True)
        self.diagnostic_input.setFocus()

    def show_settings(self) -> None:
        self._navigate(self.settings_page)
        self.settings_button.setChecked(True)

    def prepare_practice(
        self, exercise_id: str, spec: PracticeSpec | None = None
    ) -> None:
        self._category = "numbers"
        self._navigate(self.practice_page)
        self.numbers_button.setChecked(True)
        # 이전 입력 영역의 포커스를 정리한 뒤 새 시도를 만든다.
        self.practice_input.setEnabled(False)
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

    def prepare_commands(self, lesson_id: str, spec: CommandSpec | None = None) -> None:
        lesson = get_command_profile(lesson_id)
        self._category = "commands"
        self._navigate(self.command_page)
        self.commands_button.setChecked(True)
        self.command_page.prepare(lesson, spec, font_size=self.font_spin.value())

    def prepare_editing(
        self, profile_id: str, spec: EditPracticeSpec | None = None
    ) -> None:
        if spec is not None and spec.profile_id != profile_id:
            raise ValueError("선택한 유형과 문제 생성 조건이 다릅니다.")
        try:
            if spec is None:
                spec = EditPracticeSpec(
                    profile_id,
                    seed=randbelow(2**32),
                    technique_weights=self._edit_weights(),
                )
            lesson = create_edit_problem(spec)
        except ValueError as error:
            self.statusBar().showMessage(f"과제 열기 실패 · {error}")
            self.statusBar().show()
            return
        self.prepare_editing_lesson(lesson)

    def prepare_editing_lesson(
        self, lesson: EditLesson, *, random_document: bool = False
    ) -> None:
        self._category = "editing"
        self._navigate(self.edit_practice)
        self.editing_button.setChecked(True)
        self.edit_practice.prepare(lesson, random_document=random_document)

    def prepare_document_mission(
        self,
        mission_id: str,
        *,
        seed: int | None = None,
        random_document: bool = False,
    ) -> None:
        try:
            spec = DocumentPracticeSpec(
                mission_id,
                randbelow(2**32) if seed is None else seed,
                technique_weights=self._edit_weights(),
            )
            lesson = create_random_document_problem(spec)
        except ValueError as error:
            self.statusBar().showMessage(f"과제 열기 실패 · {error}")
            self.statusBar().show()
            return
        self.prepare_editing_lesson(lesson, random_document=random_document)

    def prepare_random_document(self) -> None:
        missions = list_document_missions()
        if missions:
            self.prepare_document_mission(
                missions[randbelow(len(missions))].id,
                random_document=True,
            )

    def show_storage_warning(self, message: str) -> None:
        self._storage_startup_error = message
        self._refresh_storage_status()

    def _refresh_storage_status(self) -> None:
        pending_error = self.repository.persistence_error
        error = pending_error or self._storage_startup_error
        self.storage_status.setText(
            "기록 저장 대기 · 현재 결과는 유지됩니다."
            if error
            else "학습 기록 저장 준비"
        )
        self.storage_status.setToolTip(error or "")
        self.storage_retry_button.setVisible(bool(pending_error))

    def _retry_storage(self) -> None:
        self.repository.retry_pending()
        self._refresh_storage_status()

    def start_practice(self) -> None:
        if self.session is None or self.session.state != SessionState.READY:
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
        if (
            self.session is None
            or not self.practice_input.isEnabled()
            or self.session.state not in {SessionState.READY, SessionState.RUNNING}
        ):
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
            reason = IGNORED_INPUT_MESSAGES.get(
                normalized.reason, "채점하지 않는 키입니다."
            )
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
        physical = _SHIFT_KEYS.get(expected, expected)
        actual_key = _SHIFT_KEYS.get(actual, actual)
        for key, widget in self._keyboard_labels.items():
            target = key == physical or (key == "Shift" and expected in _SHIFT_KEYS)
            border = "#f1c27e" if key == actual_key else "#405168"
            style = (
                f"background: {'#c3ef85' if target else '#243041'}; "
                f"color: {'#17220e' if target else '#bdc8d6'}; "
                f"border: 2px solid {border}; border-radius: 5px;"
            )
            if widget.styleSheet() != style:
                widget.setStyleSheet(style)

    def _focus_lost(self, reason: Qt.FocusReason) -> None:
        # 마우스 클릭은 버튼 핸들러가 처리하고, 다른 포커스 이동은 일시정지한다.
        if (
            reason == Qt.FocusReason.MouseFocusReason
            and QApplication.focusWidget() is self.pause_button
        ):
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
                elif self.stack.currentWidget() == self.command_page:
                    if not self.command_page.start_button.isVisible():
                        self.command_page.pause()
                elif self.stack.currentWidget() == self.edit_practice:
                    self.edit_practice.pause()
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
            self.result_new_button.setFocus()
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
