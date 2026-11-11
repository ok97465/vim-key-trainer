"""문서 종류와 문자열 편집 기술을 고르는 카드 메뉴."""

# Third party imports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.content.document_missions import (
    document_catalog_issues,
    list_document_collections,
    list_document_missions,
)
from vim_key_trainer.domain.achievements import summarize_activities, summarize_learning
from vim_key_trainer.domain.decorations import summarize_decorations
from vim_key_trainer.domain.edit_generator import (
    EditProfile,
    list_code_edit_profiles,
    list_edit_profiles,
)
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.preferences import AppearanceSettings, PresentationSettings
from vim_key_trainer.domain.sessions import EditingSessionResult
from vim_key_trainer.services.result_repository import ResultRepository
from vim_key_trainer.ui.components import button, label, scroll_page
from vim_key_trainer.ui.widgets.collection_workshop import CollectionWorkshop

_MODE_TITLES: tuple[tuple[EditMode, str], ...] = (
    ("guided", "가이드"),
    ("free", "자유"),
)


def _refresh_profile_stars(
    repository: ResultRepository,
    profiles: tuple[EditProfile, ...],
    labels: dict[tuple[str, EditMode], QLabel],
) -> None:
    for profile in profiles:
        for mode, title in _MODE_TITLES:
            value = labels.get((profile.id, mode))
            if value is None:
                continue
            stars = repository.best_edit_stars(profile.id, mode)
            value.setText(f"{title} " + "★" * stars + "☆" * (3 - stars))


def _practice_card(
    title: str,
    detail: str | QLabel,
    profile: EditProfile | None = None,
    stars: dict[tuple[str, EditMode], QLabel] | None = None,
) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    box = QVBoxLayout(frame)
    box.setContentsMargins(18, 14, 18, 14)
    box.setSpacing(6)
    top = QHBoxLayout()
    top.addWidget(label(title, "sectionTitle", wrap=True))
    top.addStretch()
    if profile is not None and stars is not None:
        for mode, mode_title in _MODE_TITLES:
            if mode == "free" and not profile.free_enabled:
                continue
            value = label(f"{mode_title} ☆☆☆", "eyebrow")
            stars[(profile.id, mode)] = value
            top.addWidget(value)
    box.addLayout(top)
    box.addWidget(
        label(detail, "eyebrow", wrap=True) if isinstance(detail, str) else detail
    )
    return frame, box


class EditCategoryPage(QWidget):
    general_requested = Signal()
    techniques_requested = Signal()
    practice_requested = Signal(str)
    activity_requested = Signal(str)
    appearance_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.missions = list_document_missions()
        self.profiles = list_code_edit_profiles()
        self._stars: dict[tuple[str, EditMode], QLabel] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        page, layout = scroll_page(margins=(32, 28, 32, 26), spacing=16)
        outer.addWidget(page)
        layout.addWidget(label("03 / DOCUMENT EDITING", "eyebrow"))
        layout.addWidget(label("문서 수정 연습", "title"))
        layout.addWidget(
            label(
                "연습 종류를 고르고 가이드 또는 자유 풀이로 바로 시작하세요.",
                "muted",
                wrap=True,
            )
        )
        self.summary = label(
            f"학습 완료 0회 · 문서 복구 0/{len(self.missions)} · 모은 별 0",
            "muted",
            wrap=True,
        )
        self.summary.setToolTip(
            "모은 별은 문서별 최고 별을 한 번씩 합산합니다. "
            "가이드·자유 풀이의 개인 기록은 각각 유지합니다."
        )
        header = QHBoxLayout()
        header.addWidget(label(f"{len(self.profiles) + 2}가지 연습", "sectionTitle"))
        header.addStretch()
        header.addWidget(self.summary)
        layout.addLayout(header)
        grid = QGridLayout()
        grid.setSpacing(12)

        self.source_summary = label(
            f"{len(self.missions)}개 공개 문서 · 원문·라이선스 포함 · 오프라인 연습",
            "eyebrow",
            wrap=True,
        )
        general, box = _practice_card("일반 문서 연습", self.source_summary)
        box.addWidget(
            label(
                "공개 문서의 손상을 원문대로 복구합니다. "
                "연습 화면에서 다른 문서를 선택할 수 있습니다.",
                "muted",
                wrap=True,
            )
        )
        self.general_button = button(
            "연습 준비 →", "editingGeneral", enter_activates=True
        )
        self.general_button.clicked.connect(self.general_requested.emit)
        self.general_button.setEnabled(bool(self.missions))
        box.addWidget(self.general_button)
        grid.addWidget(general, 0, 0)

        techniques, box = _practice_card(
            "기술별 문자열 연습", "12 / 24 / 40줄 · 가이드 / 자유 풀이"
        )
        box.addWidget(
            label(
                "숫자·줄 삭제·단어·메모·복합·undo의 6개 유형을 연습합니다. "
                "undo는 가이드로 연습합니다.",
                "muted",
                wrap=True,
            )
        )
        self.techniques_button = button(
            "기술 선택 →", "editingTechniques", enter_activates=True
        )
        self.techniques_button.clicked.connect(self.techniques_requested.emit)
        box.addWidget(self.techniques_button)
        grid.addWidget(techniques, 0, 1)

        corpus_error = ""
        try:
            code_sources = load_code_sources()
        except (ValueError, OSError) as error:
            code_sources = ()
            corpus_error = str(error)
        for index, profile in enumerate(self.profiles, start=2):
            uses_corpus = profile.language in {"python", "cpp"}
            projects = {
                item.source.project
                for item in code_sources
                if item.source.language == profile.language
            }
            detail = (
                f"{len(projects)}개 공개 프로젝트 · 300~500줄 무작위 발췌"
                if uses_corpus
                else "중첩 설정 60줄"
            )
            frame, box = _practice_card(profile.title, detail, profile, self._stars)
            box.addWidget(label(profile.description, "muted", wrap=True))
            if uses_corpus and corpus_error:
                box.addWidget(label(corpus_error, "muted", wrap=True))
            start = button("연습 준비 →", f"lesson_{profile.id}", enter_activates=True)
            start.clicked.connect(
                lambda checked=False, key=profile.id: self.practice_requested.emit(key)
            )
            start.setEnabled(not uses_corpus or bool(projects))
            box.addWidget(start)
            grid.addWidget(frame, index // 2, index % 2)
        for column in range(2):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)

        activities = QHBoxLayout()
        self.daily_button = button(
            "오늘의 미션 →", "editingDaily", enter_activates=True
        )
        self.daily_button.clicked.connect(lambda: self.activity_requested.emit("daily"))
        self.boss_button = button("보스 문서 →", "editingBoss", enter_activates=True)
        self.boss_button.clicked.connect(lambda: self.activity_requested.emit("boss"))
        activities.addWidget(self.daily_button)
        activities.addWidget(self.boss_button)
        activities.addStretch()
        layout.addLayout(activities)
        self.activity_progress = label("", "muted", wrap=True)
        layout.addWidget(self.activity_progress)

        self.achievements = label(
            "첫 문서 복구로 첫 훈장을 모아 보세요.", "eyebrow", wrap=True
        )
        layout.addWidget(self.achievements)
        self.collection_progress = label("", "eyebrow", wrap=True)
        layout.addWidget(self.collection_progress)
        self.workshop = CollectionWorkshop()
        self.workshop.appearance_changed.connect(self.appearance_changed.emit)
        layout.addWidget(self.workshop)
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

    @property
    def appearance_settings(self) -> AppearanceSettings:
        return self.workshop.appearance_settings

    def configure_appearance(self, settings: AppearanceSettings) -> None:
        self.workshop.configure_appearance(settings)

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.workshop.configure_effects(settings)

    def stop_effects(self) -> None:
        self.workshop.art.stop_effects()

    def refresh(self, repository: ResultRepository) -> None:
        completed = sum(
            isinstance(result, EditingSessionResult) and result.completion_eligible
            for result in repository.results
        )
        learning = summarize_learning(
            repository.results, (mission.id for mission in self.missions)
        )
        self.workshop.set_progress(learning, summarize_decorations(repository.results))
        activity = summarize_activities(repository.results)
        self.activity_progress.setText(
            f"오늘의 미션 {activity.daily_completions}개 · "
            f"보스 문서 {activity.boss_completions}개 · "
            f"모은 목표 보너스 {activity.bonus_points:,}점"
        )
        self.summary.setText(
            f"학습 완료 {completed}회 · "
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
        self.collection_progress.setText("  ·  ".join(collection_lines))
        _refresh_profile_stars(repository, self.profiles, self._stars)


class EditTechniquePage(QWidget):
    """문자열 편집 기술 여섯 가지를 고르는 독립 화면."""

    practice_requested = Signal(str)
    categories_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.profiles = list_edit_profiles()
        self._stars: dict[tuple[str, EditMode], QLabel] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        page, layout = scroll_page(margins=(32, 28, 32, 26), spacing=16)
        outer.addWidget(page)
        layout.addWidget(label("03 / STRING EDITING", "eyebrow"))
        layout.addWidget(label("기술별 문자열 연습", "title"))
        layout.addWidget(
            label(
                "12 / 24 / 40줄에서 7 / 7 / 10곳을 고칩니다. undo는 가이드 전용입니다.",
                "muted",
                wrap=True,
            )
        )
        header = QHBoxLayout()
        header.addWidget(label(f"{len(self.profiles)}가지 연습", "sectionTitle"))
        header.addStretch()
        self.summary = label("학습 완료 0회", "muted")
        header.addWidget(self.summary)
        layout.addLayout(header)
        grid = QGridLayout()
        grid.setSpacing(12)
        for index, profile in enumerate(self.profiles):
            frame, box = _practice_card(
                profile.title,
                "가이드 / 자유 풀이" if profile.free_enabled else "가이드 전용",
                profile,
                self._stars,
            )
            box.addWidget(label(profile.description, "muted", wrap=True))
            start = button("연습 준비 →", f"lesson_{profile.id}", enter_activates=True)
            start.clicked.connect(
                lambda checked=False, key=profile.id: self.practice_requested.emit(key)
            )
            box.addWidget(start)
            grid.addWidget(frame, index // 2, index % 2)
        for column in range(2):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        categories = button(
            "← 문서 수정 연습", "editingToCategories", enter_activates=True
        )
        categories.clicked.connect(self.categories_requested.emit)
        actions = QHBoxLayout()
        actions.addWidget(categories)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()

    def refresh(self, repository: ResultRepository) -> None:
        profile_ids = {profile.id for profile in self.profiles}
        completed = sum(
            isinstance(result, EditingSessionResult)
            and result.completion_eligible
            and result.lesson_id in profile_ids
            for result in repository.results
        )
        self.summary.setText(f"학습 완료 {completed}회")
        _refresh_profile_stars(repository, self.profiles, self._stars)
