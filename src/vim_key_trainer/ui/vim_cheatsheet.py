"""확대·검색할 수 있는 읽기 전용 한국어 Vim 명령 참조."""

# Third party imports
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.content.vim_cheatsheet import CHEAT_SECTIONS, CheatSection
from vim_key_trainer.ui.components import button, label
from vim_key_trainer.ui.widgets.cheatsheet_poster import CheatSheetPoster

_STYLESHEET = """
QWidget#vimCheatSheet { background: #10151d; }
QLabel#sheetEyebrow { color: #b7e980; font-size: 11px; font-weight: bold; }
QLabel#sheetTitle { color: #f0f4f8; font-size: 32px; font-weight: bold; }
QLabel#sheetMuted { color: #a8b6c7; }
QLabel#sheetCount { color: #b7c7d8; font-size: 12px; }
QFrame#sheetIntro {
    background: #1b2b27; border: 1px solid #3c5946; border-radius: 10px;
}
QLabel#sheetFormula { color: #d8efc1; font-size: 20px; font-weight: bold; }
QLabel#sheetExample {
    color: #a8dce9; font-family: "Menlo", "Consolas", monospace;
}
QLineEdit#sheetSearch {
    background: #19232f; border: 1px solid #435367; border-radius: 7px;
    padding: 10px 13px; selection-background-color: #436244;
}
QLineEdit#sheetSearch:focus { border-color: #c3ef85; }
QComboBox#sheetCategory { min-width: 145px; padding: 8px 10px; }
QSpinBox#sheetFontSize { min-width: 64px; padding: 8px; }
QFrame#sheetCard {
    background: #19222e; border: 1px solid #303e50; border-radius: 10px;
}
QLabel#sheetNumber { color: #8ca4b9; font-size: 12px; }
QLabel#sheetCardTitle { color: #d5efb8; font-weight: bold; }
QLabel#sheetBadge {
    color: #edc48c; background: #3b3025; border-radius: 4px;
    padding: 3px 6px; font-size: 11px;
}
QLabel#sheetSubtitle { color: #a9b7c9; }
QFrame#sheetRow { border: none; border-radius: 4px; background: transparent; }
QFrame#sheetRow[alternate="true"] { background: #202d3b; }
QLabel#sheetKeys {
    color: #a8dce9; font-family: "Menlo", "Consolas", monospace;
    font-weight: bold; background: transparent;
}
QLabel#sheetDescription { color: #e0e7ef; background: transparent; }
QLabel#sheetEmpty { color: #a8b6c7; padding: 48px; }
"""


def _readable(text: str, role: str) -> QLabel:
    widget = label(text, role, wrap=True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return widget


class _SectionCard(QFrame):
    def __init__(self, section: CheatSection, number: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.section = section
        self.setObjectName("sheetCard")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 15, 16, 12)
        box.setSpacing(8)
        heading = QHBoxLayout()
        heading.setSpacing(9)
        heading.addWidget(label(f"{number:02d}", "sheetNumber"))
        self.title_label = label(section.title, "sheetCardTitle", wrap=True)
        heading.addWidget(self.title_label, 1)
        if section.vim_only:
            heading.addWidget(label("Vim 전용", "sheetBadge"))
        box.addLayout(heading)
        self.subtitle_label = _readable(section.subtitle, "sheetSubtitle")
        box.addWidget(self.subtitle_label)
        self.rows: list[QFrame] = []
        self.key_labels: list[QLabel] = []
        self.description_labels: list[QLabel] = []
        for index, entry in enumerate(section.entries):
            row = QFrame()
            row.setObjectName("sheetRow")
            row.setProperty("alternate", index % 2 == 0)
            cells = QHBoxLayout(row)
            cells.setContentsMargins(8, 7, 8, 7)
            cells.setSpacing(12)
            keys = _readable(entry.keys, "sheetKeys")
            description = _readable(entry.description, "sheetDescription")
            cells.addWidget(keys, 5)
            cells.addWidget(description, 7)
            box.addWidget(row)
            self.rows.append(row)
            self.key_labels.append(keys)
            self.description_labels.append(description)
        self.visible_count = len(self.rows)

    def filter_entries(self, query: str) -> int:
        # Vim 명령은 대소문자를 구분하고, 설명문은 구분하지 않는다.
        section_match = (
            query.casefold()
            in (self.section.title + " " + self.section.subtitle).casefold()
        )
        count = 0
        for row, entry in zip(self.rows, self.section.entries, strict=True):
            matches = (
                not query
                or section_match
                or query in entry.keys
                or query.casefold() in entry.description.casefold()
            )
            row.setVisible(matches)
            count += matches
        self.visible_count = count
        return count

    def set_font_size(self, size: int) -> None:
        self.title_label.setStyleSheet(f"font-size: {size + 3}px;")
        self.subtitle_label.setStyleSheet(f"font-size: {size - 1}px;")
        for widget in (*self.key_labels, *self.description_labels):
            widget.setStyleSheet(f"font-size: {size}px;")


class VimCheatSheetPage(QWidget):
    """검색·범주·글자 크기를 유지하는 독립 참조 화면. 명령을 실행하지 않는다."""

    return_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("vimCheatSheet")
        self.setStyleSheet(_STYLESHEET)
        self._visible_cards: list[_SectionCard] = []
        self._column_count = 0
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.setSpacing(12)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        titles.addWidget(label("REFERENCE / 한국어 명령 가이드", "sheetEyebrow"))
        titles.addWidget(label("Vim CheatSheet", "sheetTitle"))
        heading.addLayout(titles, 1)
        self.return_button = button(
            "← 이전 화면으로", "cheatsheetReturn", enter_activates=True
        )
        self.return_button.clicked.connect(self.return_requested.emit)
        heading.addWidget(self.return_button, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(heading)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("cheatsheetScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        self.poster = CheatSheetPoster()
        body.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignHCenter)
        body.addWidget(
            label(
                "그림 클릭: 전체 화면 · 확대  /  그림 우클릭: PNG 이미지 저장",
                "sheetCount",
                wrap=True,
            )
        )
        body.addWidget(
            label(
                "이동부터 편집, 검색과 창 관리까지. 필요한 명령을 찾아 조합하세요.",
                "sheetMuted",
                wrap=True,
            )
        )
        self.intro = self._make_intro()
        body.addWidget(self.intro)
        body.addWidget(
            label(
                "전체 Vim 참고서입니다. ‘Vim 전용’은 실제 Vim에서 사용하며, "
                "일부 지원 범주는 카드 설명을 확인하세요. "
                "이 화면의 명령은 실행되지 않습니다.",
                "sheetMuted",
                wrap=True,
            )
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("sheetSearch")
        self.search.setAccessibleName("CheatSheet 명령 또는 한글 설명 검색")
        self.search.setPlaceholderText(
            "명령 또는 한글 설명 검색  ·  예: ciw, 단어, 치환"
        )
        self.search.setClearButtonEnabled(True)
        toolbar.addWidget(self.search, 1)
        self.category = QComboBox()
        self.category.setObjectName("sheetCategory")
        self.category.setAccessibleName("CheatSheet 범주")
        self.category.addItem("전체 범주", "")
        for section in CHEAT_SECTIONS:
            self.category.addItem(section.title, section.id)
        toolbar.addWidget(self.category)
        self.font_size = QSpinBox()
        self.font_size.setObjectName("sheetFontSize")
        self.font_size.setAccessibleName("CheatSheet 글자 크기")
        self.font_size.setRange(13, 20)
        self.font_size.setValue(14)
        self.font_size.setSuffix(" px")
        self.font_size.setToolTip("명령과 설명의 글자 크기")
        toolbar.addWidget(self.font_size)
        body.addLayout(toolbar)
        self.result_count = label("", "sheetCount")
        self.result_count.setAccessibleName("CheatSheet 검색 결과 수")
        body.addWidget(self.result_count)

        self.cards_content = QWidget()
        content_layout = QVBoxLayout(self.cards_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.empty_label = label(
            "일치하는 명령이 없습니다. 검색어를 줄이거나 다른 범주를 선택하세요.",
            "sheetEmpty",
            wrap=True,
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.empty_label)
        self.columns_box = QHBoxLayout()
        self.columns_box.setSpacing(14)
        self.columns: list[QWidget] = []
        self.column_layouts: list[QVBoxLayout] = []
        for _ in range(3):
            column = QWidget()
            column.setMinimumWidth(0)
            column.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(14)
            column_layout.addStretch()
            self.columns_box.addWidget(column, 1)
            self.columns.append(column)
            self.column_layouts.append(column_layout)
        content_layout.addLayout(self.columns_box)
        self.cards = [
            _SectionCard(section, number, self.cards_content)
            for number, section in enumerate(CHEAT_SECTIONS, start=1)
        ]
        body.addWidget(self.cards_content)
        self.scroll_area.setWidget(self.content)
        outer.addWidget(self.scroll_area, 1)
        footer = label(
            '기준: <a href="https://vimhelp.org/quickref.txt.html" '
            'style="color:#b7e980">Vim 공식 도움말 ↗</a>'
            " &nbsp; · &nbsp; Ctrl은 실제 Control 키입니다. "
            "macOS의 Command 키와 구분하세요.",
            "sheetCount",
            wrap=True,
        )
        footer.setTextFormat(Qt.TextFormat.RichText)
        footer.setOpenExternalLinks(True)
        outer.addWidget(footer)

        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)
        self.font_size.valueChanged.connect(self._change_font_size)
        self._change_font_size(self.font_size.value())
        self._filter()

    def _make_intro(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sheetIntro")
        box = QHBoxLayout(frame)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(18)
        formula = QVBoxLayout()
        formula.setSpacing(5)
        formula.addWidget(label("연산자  +  횟수  +  이동·객체", "sheetFormula"))
        formula.addWidget(
            label(
                "d 삭제 · c 변경 · y 복사   /   횟수 생략은 1회",
                "sheetMuted",
                wrap=True,
            )
        )
        box.addLayout(formula, 1)
        examples = label(
            'd2w  <span style="color:#b7c8b3">두 단어 삭제</span><br>'
            "ci&quot;  "
            '<span style="color:#b7c8b3">따옴표 내부 변경</span>',
            "sheetExample",
        )
        examples.setTextFormat(Qt.TextFormat.RichText)
        box.addWidget(examples)
        return frame

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.OtherFocusReason)
        self.scroll_area.ensureWidgetVisible(self.search, 0, 16)

    def focus_entry(self) -> None:
        self.poster.setFocus(Qt.FocusReason.OtherFocusReason)
        self.scroll_area.verticalScrollBar().setValue(0)

    def _filter(self) -> None:
        query = self.search.text().strip()
        section_id = self.category.currentData()
        self._visible_cards = []
        count = 0
        for card in self.cards:
            matches = card.filter_entries(query)
            visible = bool(matches) and (
                not section_id or card.section.id == section_id
            )
            card.setVisible(visible)
            if visible:
                self._visible_cards.append(card)
                count += matches
        total = sum(len(section.entries) for section in CHEAT_SECTIONS)
        self.result_count.setText(
            f"{len(self._visible_cards)}개 범주  ·  {count} / {total}개 명령 항목"
            "   |   명령의 대소문자를 구분합니다."
        )
        self.empty_label.setVisible(not self._visible_cards)
        self.intro.setVisible(not query and not section_id)
        self._column_count = 0
        self._reflow()
        if self.isVisible():
            self.scroll_area.ensureWidgetVisible(self.result_count, 0, 16)

    def _change_font_size(self, size: int) -> None:
        for card in self.cards:
            card.set_font_size(size)
        self._column_count = 0
        self._reflow_timer.start(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_timer.start(0)

    def _reflow(self) -> None:
        width = self.scroll_area.viewport().width()
        # 큰 글씨일수록 카드 폭도 늘려 명령·설명 두 열을 읽을 수 있게 한다.
        target_width = 410 + (self.font_size.value() - 14) * 20
        count = max(1, min(3, (width + 14) // (target_width + 14)))
        count = min(count, max(1, len(self._visible_cards)))
        if count == self._column_count:
            return
        self._column_count = count
        for card in self.cards:
            for column_layout in self.column_layouts:
                column_layout.removeWidget(card)
        heights = [0] * count
        for card in self._visible_cards:
            index = min(range(count), key=heights.__getitem__)
            column_layout = self.column_layouts[index]
            column_layout.insertWidget(column_layout.count() - 1, card)
            heights[index] += 100 + card.visible_count * 42
        for index, column in enumerate(self.columns):
            column.setVisible(index < count and bool(self._visible_cards))
