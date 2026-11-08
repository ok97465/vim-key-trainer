"""수집 성취에 따라 밝아지는 작업실과 게임에 영향을 주지 않는 꾸미기."""

# Third party imports
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPixmap, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.domain.achievements import LearningSummary
from vim_key_trainer.domain.decorations import DecorationProgress
from vim_key_trainer.domain.preferences import AppearanceSettings
from vim_key_trainer.ui.components import label
from vim_key_trainer.ui.game_resources import game_resource_path


class _WorkshopArt(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(180, 128)
        self.setMaximumWidth(270)
        self.progress = 0
        try:
            self.pixmap = QPixmap(game_resource_path("library-workshop.png"))
        except (OSError, ValueError):
            self.pixmap = QPixmap()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        image = self.pixmap.size().scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        x, y = (
            (self.width() - image.width()) // 2,
            (self.height() - image.height()) // 2,
        )
        # 성취로 불이 켜지는 정적인 상태 그림. 판정과 애니메이션은 독립적이다.
        painter.setOpacity(min(1.0, 0.34 + self.progress * 0.055))
        painter.drawPixmap(x, y, image.width(), image.height(), self.pixmap)
        painter.setOpacity(1.0)
        painter.setPen(QColor("#e9d49e"))
        if self.progress >= 6:
            for point in ((15, 16), (self.width() - 20, 28), (self.width() - 35, 10)):
                x, y = point
                painter.drawLine(x - 3, y, x + 3, y)
                painter.drawLine(x, y - 3, x, y + 3)


class CollectionWorkshop(QFrame):
    appearance_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self._appearance = AppearanceSettings()
        self._progress = DecorationProgress(0, 0)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        row = QHBoxLayout()
        self.art = _WorkshopArt()
        row.addWidget(self.art, 1)
        text = QVBoxLayout()
        self.title = label("나의 작은 작업실", "sectionTitle")
        text.addWidget(self.title)
        self.progress_label = label(
            "첫 문서를 복구하면 책상에 불이 켜집니다.", "muted", wrap=True
        )
        text.addWidget(self.progress_label)
        self.unlock_label = label(
            "꾸미기 해금 · 서로 다른 연습 완료 0개", "eyebrow", wrap=True
        )
        text.addWidget(self.unlock_label)
        self.decorations_check = QCheckBox("그림과 꾸미기 표시")
        self.decorations_check.setChecked(True)
        self.decorations_check.setAccessibleName("그림과 꾸미기 표시")
        self.decorations_check.toggled.connect(self._changed)
        text.addWidget(self.decorations_check)
        row.addLayout(text, 2)
        root.addLayout(row)
        controls = QHBoxLayout()
        self.choices: dict[str, QComboBox] = {}
        for key, title, entries in (
            (
                "mascot",
                "폭탄 모양",
                (("별심지 폭탄 · 기본", "classic"), ("민트 고양이 · 3종 완료", "cat")),
            ),
            (
                "fuse",
                "심지 색",
                (
                    ("민트 · 기본", "mint"),
                    ("복숭아 · 1종 완료", "peach"),
                    ("라일락 · 3종 완료", "lilac"),
                ),
            ),
            (
                "stamp",
                "성공 도장",
                (
                    ("체크 · 기본", "check"),
                    ("별 · 3종 완료", "star"),
                    ("꽃 · 6종 완료", "flower"),
                ),
            ),
        ):
            column = QVBoxLayout()
            column.addWidget(label(title, "muted"))
            combo = QComboBox()
            combo.setMinimumContentsLength(8)
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setAccessibleName(title)
            for caption, value in entries:
                combo.addItem(caption, value)
            combo.currentIndexChanged.connect(self._changed)
            self.choices[key] = combo
            column.addWidget(combo)
            controls.addLayout(column, 1)
        root.addLayout(controls)
        self.setToolTip(
            "서로 다른 연습 유형·원문을 완료할 때 해금합니다. 반복·재저장·"
            "시간 초과·복수전은 추가 해금 수를 늘리지 않습니다. "
            "외형은 시간과 점수에 영향을 주지 않습니다."
        )
        self.configure_appearance(self._appearance)

    @property
    def appearance_settings(self) -> AppearanceSettings:
        return self._appearance

    def configure_appearance(self, settings: AppearanceSettings) -> None:
        self._appearance = settings
        for key, combo in self.choices.items():
            with QSignalBlocker(combo):
                combo.setCurrentIndex(combo.findData(getattr(settings, key)))
        with QSignalBlocker(self.decorations_check):
            self.decorations_check.setChecked(settings.decorations)
        self.art.setVisible(settings.decorations)
        for combo in self.choices.values():
            combo.setEnabled(settings.decorations)

    def set_progress(
        self, learning: LearningSummary, progress: DecorationProgress
    ) -> None:
        self._progress = progress
        count = learning.completed_missions
        self.art.progress = count
        self.art.update()
        stage = (
            "별빛 도서관"
            if count >= 12
            else "포근한 도서관"
            if count >= 6
            else "책장이 채워지는 중"
            if count >= 3
            else "책상에 첫 불빛"
            if count
            else "첫 복구를 기다리는 작업실"
        )
        self.progress_label.setText(
            f"{stage}\n문서 수집 {count}/{learning.total_missions} · "
            f"모은 별 {learning.total_stars}"
        )
        self.unlock_label.setText(
            f"서로 다른 연습 완료 {progress.completed_lessons}종 · "
            f"직접 해체 {progress.direct_repairs}곳"
        )
        previous = self._appearance
        self.configure_appearance(progress.effective(previous))
        for key, combo in self.choices.items():
            model = combo.model()
            if isinstance(model, QStandardItemModel):
                for index in range(combo.count()):
                    item = model.item(index)
                    if item is not None:
                        item.setEnabled(
                            progress.allows(key, str(combo.itemData(index)))
                        )
        if self._appearance != previous:
            self.appearance_changed.emit(self._appearance)

    def _changed(self) -> None:
        settings = AppearanceSettings(
            mascot=self.choices["mascot"].currentData(),
            fuse=self.choices["fuse"].currentData(),
            stamp=self.choices["stamp"].currentData(),
            decorations=self.decorations_check.isChecked(),
        )
        self.configure_appearance(self._progress.effective(settings))
        self.appearance_changed.emit(self._appearance)
