"""실제 문서 미션과 기술별 생성 연습을 선택하는 책장."""

# Third party imports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.content.document_missions import (
    document_catalog_issues,
    list_document_collections,
    list_document_missions,
)
from vim_key_trainer.domain.achievements import summarize_learning
from vim_key_trainer.domain.edit_generator import list_edit_profiles
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.sessions import EditingSessionResult, SessionState
from vim_key_trainer.services.result_repository import ResultRepository
from vim_key_trainer.ui.components import button, label, scroll_page


class EditCatalogPage(QWidget):
    practice_requested = Signal(str)
    random_practice_requested = Signal()
    numbers_requested = Signal()
    commands_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.profiles = list_edit_profiles()
        self.missions = list_document_missions()
        self._stars: dict[tuple[str, EditMode], QLabel] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.addWidget(label("03 / DOCUMENT REPAIR", "eyebrow"))
        outer.addWidget(label("문서 복구 작업실", "title"))
        self.summary = label("완료 0회", "muted")
        self.summary.setToolTip(
            "모은 별은 문서별 최고 별을 한 번씩 합산합니다. "
            "가이드·자유 풀이의 개인 기록은 각각 유지합니다."
        )
        outer.addWidget(self.summary)
        self.achievements = label(
            "첫 문서 복구로 첫 훈장을 모아 보세요.", "eyebrow", wrap=True
        )
        outer.addWidget(self.achievements)
        self.tabs = QTabWidget()
        self.mission_page = self._make_missions()
        self.technique_page = self._make_techniques()
        self.tabs.addTab(self.mission_page, "실제 문서 미션")
        self.tabs.addTab(self.technique_page, "기술별 생성 연습")
        outer.addWidget(self.tabs, 1)
        actions = QHBoxLayout()
        numbers = button("숫자·기호 연습으로", "editingToNumbers")
        numbers.clicked.connect(self.numbers_requested.emit)
        commands = button("Vim 명령 연습으로", "editingToCommands")
        commands.clicked.connect(self.commands_requested.emit)
        actions.addWidget(numbers)
        actions.addWidget(commands)
        actions.addStretch()
        outer.addLayout(actions)

    def _make_missions(self) -> QWidget:
        page, layout = scroll_page(margins=(12, 16, 12, 16))
        layout.addWidget(
            label(
                "원문을 무작위로 고르고 Vim 명령과 텍스트 입력으로 만든 손상을 "
                "복구합니다. "
                "같은 원문에서도 매번 다른 문제를 만납니다.",
                "muted",
                wrap=True,
            )
        )
        self.launch_button = button(
            "무작위 문서로 연습 준비 →",
            "startRandomDocumentPractice",
            primary=True,
        )
        self.launch_button.clicked.connect(self.random_practice_requested.emit)
        self.launch_button.setEnabled(bool(self.missions))
        layout.addWidget(self.launch_button)
        layout.addWidget(
            label(
                "연습 화면의 문서 선택에서 특정 원문으로 바꿀 수 있습니다. "
                "같은 문제 다시는 문서와 손상을 유지하며, "
                "다른 문제는 새 손상을 만듭니다.",
                "muted",
                wrap=True,
            )
        )
        self.collection_progress = label("", "eyebrow", wrap=True)
        layout.addWidget(self.collection_progress)
        self.source_summary = label(
            f"{len(self.missions)}개 공개 문서 · 원문·라이선스 포함 · 오프라인 연습",
            "muted",
            wrap=True,
        )
        layout.addWidget(self.source_summary)
        issues = document_catalog_issues()
        if issues:
            layout.addWidget(
                label(
                    "제외한 문서 미션:\n" + "\n".join(issues),
                    "muted",
                    wrap=True,
                )
            )
        layout.addStretch()
        return page

    def _make_techniques(self) -> QWidget:
        page, layout = scroll_page(margins=(4, 10, 4, 10))
        layout.addWidget(
            label(
                "12 / 24 / 40줄 문서에서 7 / 7 / 10개 구간을 연습합니다. "
                "같은 문제 재도전과 새 예제 생성을 구분합니다.",
                "muted",
                wrap=True,
            )
        )
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, profile in enumerate(self.profiles):
            frame = QFrame()
            frame.setObjectName("card")
            box = QVBoxLayout(frame)
            box.setContentsMargins(16, 12, 16, 12)
            box.addWidget(label(profile.title, "sectionTitle"))
            box.addWidget(label(profile.description, "muted", wrap=True))
            stars = QHBoxLayout()
            mode_names: tuple[tuple[EditMode, str], ...] = (
                ("guided", "가이드"),
                ("free", "자유"),
            )
            for mode, title in mode_names:
                if mode == "free" and not profile.free_enabled:
                    continue
                value = label(f"{title} ☆☆☆", "eyebrow")
                self._stars[(profile.id, mode)] = value
                stars.addWidget(value)
            box.addLayout(stars)
            start = button("편집 연습 준비 →", f"lesson_{profile.id}")
            start.clicked.connect(
                lambda checked=False, key=profile.id: self.practice_requested.emit(key)
            )
            box.addWidget(start)
            grid.addWidget(frame, index // 2, index % 2)
        layout.addLayout(grid)
        layout.addStretch()
        return page

    def select_techniques(self) -> None:
        self.tabs.setCurrentWidget(self.technique_page)

    def refresh(self, repository: ResultRepository) -> None:
        completed = sum(
            isinstance(result, EditingSessionResult)
            and result.state == SessionState.COMPLETED
            for result in repository.results
        )
        versions = {m.id: m.content_version for m in self.missions}
        learning = summarize_learning(
            repository.results, versions, content_versions=versions
        )
        self.summary.setText(
            f"완료 {completed}회 · "
            f"문서 복구 {learning.completed_missions}/{len(self.missions)} · "
            f"모은 별 {learning.total_stars}"
        )
        self.achievements.setText(
            "  ·  ".join(badge.title for badge in learning.badges)
            or "첫 문서 복구로 첫 훈장을 모아 보세요."
        )
        collection_lines: list[str] = []
        for collection in list_document_collections():
            missions = [m for m in self.missions if m.collection_id == collection.id]
            done = sum(m.id in learning.completed_ids for m in missions)
            collection_lines.append(f"{collection.title}  {done}/{len(missions)}")
        self.collection_progress.setText("\n".join(collection_lines))
        for profile in self.profiles:
            modes: tuple[EditMode, ...] = ("guided", "free")
            for mode in modes:
                if (profile.id, mode) not in self._stars:
                    continue
                stars = repository.best_edit_stars(
                    profile.id, profile.content_version, mode
                )
                title = "가이드" if mode == "guided" else "자유"
                self._stars[(profile.id, mode)].setText(
                    f"{title} " + "★" * stars + "☆" * (3 - stars)
                )
