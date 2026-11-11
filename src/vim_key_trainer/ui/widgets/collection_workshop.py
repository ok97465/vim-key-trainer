"""수집 성취에 따라 밝아지는 작업실과 게임에 영향을 주지 않는 꾸미기."""

# Standard library imports
import math

# Third party imports
from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSignalBlocker,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QShowEvent,
    QStandardItemModel,
)
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
from vim_key_trainer.domain.preferences import AppearanceSettings, PresentationSettings
from vim_key_trainer.ui.components import label
from vim_key_trainer.ui.game_resources import game_resource_path


class _WorkshopArt(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(180, 128)
        self.setMaximumWidth(270)
        self.progress = 0
        self.previous_progress = 0
        self.arrival = 1.0
        self.settings = PresentationSettings()
        self._pending_arrival = False
        self.pixmap = QPixmap(game_resource_path("library-workshop.png"))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(1400)
        self.animation.valueChanged.connect(self._animate)

    def _animate(self, value: float) -> None:
        self.arrival = value
        self.update()

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.settings = settings
        self.stop_effects()

    def celebrate(self, previous_progress: int) -> None:
        self.previous_progress = previous_progress
        if not self.settings.effects or self.settings.reduced_motion:
            return
        self._pending_arrival = True
        if self.isVisible():
            self._start_arrival()

    def _start_arrival(self) -> None:
        self._pending_arrival = False
        self.animation.stop()
        self.arrival = 0.0
        self.animation.start()

    def stop_effects(self) -> None:
        self.animation.stop()
        self._pending_arrival = False
        self.arrival = 1.0
        self.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._pending_arrival:
            self._start_arrival()

    def hideEvent(self, event: QHideEvent) -> None:
        self.stop_effects()
        super().hideEvent(event)

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
        # 새 성취가 생긴 순간에만 조명이 켜지고 책이 놓인다. 성취 계산은 읽기 전용이다.
        brightness = self.previous_progress + (
            self.progress - self.previous_progress
        ) * min(1.0, self.arrival * 1.7)
        painter.setOpacity(min(1.0, 0.34 + brightness * 0.055))
        painter.drawPixmap(x, y, image.width(), image.height(), self.pixmap)
        painter.setOpacity(1.0)
        if (
            self.arrival < 1
            and self.settings.effects
            and not self.settings.reduced_motion
        ):
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            light = QColor("#ffd580")
            light.setAlphaF(0.16 * math.sin(self.arrival * math.pi))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(light)
            painter.drawEllipse(QRectF(x, y, image.width(), image.height()))
            for index in range(3):
                phase = max(0.0, min(1.0, self.arrival * 2 - index * 0.18))
                book_x = x + image.width() * 0.65 + index * 7
                book_y = y + image.height() * 0.65 - (1 - phase) ** 2 * 40
                color = QColor(("#aee6c0", "#c7b4e9", "#f0cc94")[index])
                color.setAlphaF(min(1.0, phase * 3) * (1 - self.arrival))
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(book_x, book_y, 6, 19), 1, 1)
            for index in range(8):
                angle = index * math.tau / 8
                point = QPointF(self.width() / 2, self.height() / 2) + QPointF(
                    math.cos(angle) * self.width() * 0.4 * self.arrival,
                    math.sin(angle) * self.height() * 0.35 * self.arrival,
                )
                color = QColor("#ffe3a3")
                color.setAlphaF(1 - self.arrival)
                painter.setPen(QPen(color, 1.6))
                painter.drawLine(point - QPointF(2, 0), point + QPointF(2, 0))
        painter.setPen(QColor("#e9d49e"))
        if self.progress >= 6:
            for spark_x, spark_y in (
                (15, 16),
                (self.width() - 20, 28),
                (self.width() - 35, 10),
            ):
                x, y = spark_x, spark_y
                painter.drawLine(x - 3, y, x + 3, y)
                painter.drawLine(x, y - 3, x, y + 3)


class CollectionWorkshop(QFrame):
    appearance_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self._appearance = AppearanceSettings()
        self._progress = DecorationProgress(0, 0)
        self._seen_progress: tuple[int, int] | None = None
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
        self.unlock_notice = label("", "eyebrow", wrap=True)
        self.unlock_notice.setAccessibleName("새로 해금한 꾸미기와 작업실 변화")
        self.unlock_notice.hide()
        text.addWidget(self.unlock_notice)
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
        if not settings.decorations:
            self.art.stop_effects()
        self.art.setVisible(settings.decorations)
        for combo in self.choices.values():
            combo.setEnabled(settings.decorations)

    def configure_effects(self, settings: PresentationSettings) -> None:
        self.art.configure_effects(settings)

    def set_progress(
        self, learning: LearningSummary, progress: DecorationProgress
    ) -> None:
        self._progress = progress
        count = learning.completed_missions
        previous_count = self.art.progress
        self.art.progress = count
        if self._seen_progress is None or count != previous_count:
            self.art.previous_progress = count
        self.art.update()
        if self._seen_progress is not None:
            lessons_before, documents_before = self._seen_progress
            unlocked = [
                title
                for threshold, title in (
                    (1, "복숭아 심지"),
                    (3, "고양이 폭탄 · 라일락 심지 · 별 도장"),
                    (6, "꽃 도장"),
                )
                if lessons_before < threshold <= progress.completed_lessons
            ]
            brightened = any(
                documents_before < threshold <= count for threshold in (1, 3, 6, 12)
            )
            if unlocked or brightened:
                message = "새 꾸미기 · " + " / ".join(unlocked) if unlocked else ""
                if brightened:
                    message += (
                        "\n" if message else ""
                    ) + "작업실에 새 불빛이 켜졌어요!"
                self.unlock_notice.setText(message)
                self.unlock_notice.show()
                if self._appearance.decorations:
                    self.art.celebrate(previous_count)
        self._seen_progress = progress.completed_lessons, count
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
