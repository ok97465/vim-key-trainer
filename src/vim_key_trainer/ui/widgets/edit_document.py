"""엔진 상태만 그리는 문서 위젯. Qt의 기본 텍스트 편집을 사용하지 않는다."""

# Standard library imports
from collections import defaultdict
from math import ceil

# Third party imports
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)

# Local imports
from vim_key_trainer.domain.document_display import (
    DocumentLanguage,
    TextSpan,
    lexical_spans,
)
from vim_key_trainer.engine import EditorState, YankSpan
from vim_key_trainer.ui.qt_input import NormalizedKey, normalize_key_event
from vim_key_trainer.ui.widgets.practice_input import PracticeInput

_SYNTAX_COLORS = {
    "keyword": "#cda9ef",
    "string": "#b9de91",
    "property": "#86c9e8",
    "number": "#f3bc82",
    "comment": "#8fa0ad",
    "operator": "#86c9e8",
    "preprocessor": "#cda9ef",
    "heading": "#86c9e8",
    "link": "#b5b7f2",
}
_CHANGE_COLORS = {"replace": "#f0c76d", "insert": "#76cafa", "delete": "#ef9b9b"}
_CURRENT_BACKGROUNDS = {"replace": "#4b3528", "insert": "#17394a", "delete": "#502c37"}
_GOAL_BACKGROUNDS = {"replace": "#494127", "insert": "#1c4252", "delete": "#502c37"}
_YANK_BACKGROUND = "#1c363c"
_YANK_BORDER = "#78c9cf"
_YANK_DURATION_MS = 400


def _spans_by_row(spans: tuple[TextSpan, ...]) -> dict[int, list[TextSpan]]:
    rows: dict[int, list[TextSpan]] = defaultdict(list)
    for span in spans:
        rows[span.row].append(span)
    return rows


class EditDocument(PracticeInput):
    def __init__(self, *, read_only: bool = False) -> None:
        super().__init__()
        self.setObjectName("editDocument")
        self.setAccessibleName("목표 문서" if read_only else "현재 문서 입력 영역")
        self.setAcceptDrops(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.read_only = read_only
        self._viewport_height = 0
        self.editor_state = EditorState(("",))
        self.language: DocumentLanguage = "text"
        self.syntax_spans: tuple[TextSpan, ...] = ()
        self.change_spans: tuple[TextSpan, ...] = ()
        self._syntax_by_row: dict[int, list[TextSpan]] = {}
        self._changes_by_row: dict[int, list[TextSpan]] = {}
        self.yank_spans: tuple[YankSpan, ...] = ()
        self._yanks_by_row: dict[int, list[YankSpan]] = {}
        self._yank_enabled = True
        self._yank_timer = QTimer(self)
        self._yank_timer.setSingleShot(True)
        self._yank_timer.setInterval(_YANK_DURATION_MS)
        self._yank_timer.timeout.connect(self.clear_yank_highlight)
        self.recovery_marks: tuple[tuple[int, str], ...] = ()
        self.success_marks: tuple[tuple[int, str], ...] = ()
        self._layout_key: tuple[tuple[str, ...], int, int] | None = None
        if read_only:
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _document_font(self) -> QFont:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setFamilies(["Menlo", "Consolas", "DejaVu Sans Mono", font.family()])
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(self.font_size)
        return font

    @property
    def document_metrics(self) -> QFontMetricsF:
        return QFontMetricsF(self._document_font())

    @property
    def document_font(self) -> QFont:
        return self._document_font()

    def show_state(self, state: EditorState) -> None:
        if state.lines != self.editor_state.lines or state.mode != "normal":
            self.clear_yank_highlight()
        if state.lines != self.editor_state.lines:
            self.syntax_spans = lexical_spans(state.lines, self.language)
            self._syntax_by_row = _spans_by_row(self.syntax_spans)
            self.change_spans = ()
            self._changes_by_row = {}
        self.editor_state = state
        layout_key = (state.lines, self.font_size, self._viewport_height)
        if layout_key != self._layout_key:
            # 커서·대기 명령만 바뀔 때는 문서 전체의 글자 폭을 다시 재지 않는다.
            metrics = self.document_metrics
            self.setMinimumSize(
                int(max(metrics.horizontalAdvance(line) for line in state.lines) + 100),
                max(
                    240,
                    int((len(state.lines) + 1) * metrics.lineSpacing() + 24),
                    ceil((len(state.lines) - 1) * metrics.lineSpacing())
                    + self._viewport_height,
                ),
            )
            self._layout_key = layout_key
        self.setAccessibleDescription(
            f"{state.mode} · {state.row + 1}행 {state.column + 1}열\n"
            + "\n".join(state.lines)
        )
        self.update()

    def set_viewport_height(self, height: int) -> None:
        """원문을 늘리지 않고 마지막 줄을 뷰포트 상단까지 스크롤하게 한다."""
        height = max(0, height)
        if height != self._viewport_height:
            self._viewport_height = height
            self.show_state(self.editor_state)

    def set_language(self, language: DocumentLanguage) -> None:
        self.syntax_spans = lexical_spans(self.editor_state.lines, language)
        self._syntax_by_row = _spans_by_row(self.syntax_spans)
        self.language = language
        self.update()

    def show_highlights(self, spans: tuple[TextSpan, ...]) -> None:
        if spans == self.change_spans:
            return
        if any(
            span.row >= len(self.editor_state.lines)
            or span.end > len(self.editor_state.lines[span.row])
            for span in spans
        ):
            raise ValueError("강조 범위가 표시 문서를 벗어났습니다.")
        self.change_spans = spans
        self._changes_by_row = _spans_by_row(spans)
        self.update()

    def set_yank_enabled(self, enabled: bool) -> None:
        self._yank_enabled = enabled
        if not enabled:
            self.clear_yank_highlight()

    def show_yank(self, spans: tuple[YankSpan, ...]) -> None:
        """이번 복사만 잠깐 표시한다. 같은 범위를 재복사해도 만료를 다시 센다."""
        if not spans or self.read_only or self.paused or not self._yank_enabled:
            return
        if any(
            span.row >= len(self.editor_state.lines)
            or span.end > len(self.editor_state.lines[span.row])
            for span in spans
        ):
            raise ValueError("복사 강조 범위가 표시 문서를 벗어났습니다.")
        self.yank_spans = spans
        self._yanks_by_row = defaultdict(list)
        for span in spans:
            self._yanks_by_row[span.row].append(span)
        # 하나의 타이머를 재시작하므로 이전 복사의 만료가 새 표시를 지우지 않는다.
        self._yank_timer.start()
        self.update()

    def clear_yank_highlight(self) -> None:
        self._yank_timer.stop()
        if self.yank_spans:
            self.yank_spans = ()
            self._yanks_by_row = {}
            self.update()

    def show_recovery_marks(self, marks: tuple[tuple[int, str], ...]) -> None:
        """복구 표식은 차이 강조를 덮지 않고 줄 번호 옆 여백에 표시한다."""
        if marks == self.recovery_marks:
            return
        self.recovery_marks = marks
        self._update_mark_tooltip()
        self.update()

    def show_success_marks(self, marks: tuple[tuple[int, str], ...]) -> None:
        if marks == self.success_marks:
            return
        self.success_marks = marks
        self._update_mark_tooltip()
        self.update()

    def _update_mark_tooltip(self) -> None:
        self.setToolTip(
            "\n".join(f"◆ {row + 1}행 · {text}" for row, text in self.recovery_marks)
            + ("\n" if self.recovery_marks and self.success_marks else "")
            + "\n".join(f"✓ {row + 1}행 · {text}" for row, text in self.success_marks)
        )

    def _span_rect(self, span: TextSpan | YankSpan, metrics: QFontMetricsF) -> QRectF:
        line = self.editor_state.lines[span.row]
        return QRectF(
            58 + metrics.horizontalAdvance(line[: span.start]),
            16 + span.row * metrics.lineSpacing(),
            max(3.0, metrics.horizontalAdvance(line[span.start : span.end])),
            metrics.lineSpacing(),
        )

    def _paint_change_backgrounds(
        self,
        painter: QPainter,
        row: int,
        metrics: QFontMetricsF,
    ) -> None:
        backgrounds = _GOAL_BACKGROUNDS if self.read_only else _CURRENT_BACKGROUNDS
        for span in self._changes_by_row.get(row, ()):
            box = self._span_rect(span, metrics)
            painter.fillRect(box, QColor(backgrounds.get(span.role, "#494127")))
            color = QColor(_CHANGE_COLORS.get(span.role, "#f0c76d"))
            painter.setPen(QPen(color, 2))
            painter.drawLine(box.bottomLeft(), box.bottomRight())
            if span.start == span.end:
                painter.drawLine(box.topLeft(), box.bottomLeft())
            painter.setPen(color)
            marker = {"delete": "−", "insert": "+"}.get(span.role, "~")
            painter.drawText(
                QRectF(0, box.top(), 16, box.height()),
                Qt.AlignmentFlag.AlignCenter,
                marker,
            )

    def _paint_syntax(
        self, painter: QPainter, row: int, metrics: QFontMetricsF
    ) -> None:
        for span in self._syntax_by_row.get(row, ()):
            painter.setPen(QColor(_SYNTAX_COLORS.get(span.role, "#e8edf3")))
            painter.drawText(
                self._span_rect(span, metrics),
                Qt.AlignmentFlag.AlignLeft,
                self.editor_state.lines[row][span.start : span.end],
            )

    def _paint_yank_highlights(
        self, painter: QPainter, row: int, metrics: QFontMetricsF
    ) -> None:
        for span in self._yanks_by_row.get(row, ()):
            box = self._span_rect(span, metrics)
            if span.start == span.end:
                box.setWidth(metrics.horizontalAdvance(" "))
            # 아래 수정 밑줄을 남기고, 테두리는 블록 커서 밖으로 내어 한 글자·
            # 빈 줄 복사도 보이게 한다. 구문 문자색과 커서는 이 위에 그린다.
            box.adjust(-0.5, -0.5, 0.5, -2.5)
            painter.fillRect(box, QColor(_YANK_BACKGROUND))
            painter.setPen(QPen(QColor(_YANK_BORDER), 1))
            painter.drawRect(box)

    def line_number_text(self, row: int) -> str:
        """입력 문서는 현재 행의 절대 번호와 다른 행의 상대 거리를 표시한다."""
        if self.read_only or row == self.editor_state.row:
            return str(row + 1)
        return str(abs(row - self.editor_state.row))

    def _paint_selection(
        self, painter: QPainter, row: int, metrics: QFontMetricsF
    ) -> None:
        state = self.editor_state
        anchor = state.visual_anchor
        if anchor is None or not state.mode.startswith("visual"):
            return
        start, end = sorted((anchor, (state.row, state.column)))
        if not start[0] <= row <= end[0]:
            return
        if state.mode == "visual_line":
            left, right = 0, len(state.lines[row])
        elif state.mode == "visual_block":
            left, right = sorted((anchor[1], state.column))
            right += 1
        else:
            left = start[1] if row == start[0] else 0
            right = end[1] + 1 if row == end[0] else len(state.lines[row])
        line = state.lines[row]
        left, right = min(left, len(line)), min(right, len(line))
        painter.fillRect(
            QRectF(
                58 + metrics.horizontalAdvance(line[:left]),
                16 + row * metrics.lineSpacing(),
                max(
                    metrics.horizontalAdvance(" "),
                    metrics.horizontalAdvance(line[left:right]),
                ),
                metrics.lineSpacing(),
            ),
            QColor("#3d506a"),
        )

    def normalize_event(self, event: QKeyEvent) -> NormalizedKey:
        return normalize_key_event(
            event,
            allow_control_v=self.editor_state.mode
            in {"normal", "visual", "visual_line", "visual_block"},
        )

    @property
    def cursor_rect(self) -> QRectF:
        metrics = QFontMetricsF(self._document_font())
        state = self.editor_state
        return QRectF(
            58 + metrics.horizontalAdvance(state.lines[state.row][: state.column]),
            16 + state.row * metrics.lineSpacing(),
            metrics.horizontalAdvance(
                state.lines[state.row][state.column : state.column + 1] or " "
            ),
            metrics.lineSpacing(),
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.read_only:
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.read_only:
            event.accept()
        else:
            super().mousePressEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self.clear_yank_highlight()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151d28"))
        if self.paused:
            painter.setPen(QColor("#a2afbf"))
            painter.drawText(
                self.visibleRegion().boundingRect(),
                Qt.AlignmentFlag.AlignCenter,
                "일시정지 · 연습 재개를 눌러 주세요",
            )
            return
        painter.setFont(self._document_font())
        metrics = QFontMetricsF(painter.font())
        state = self.editor_state
        first_row = max(0, int((event.rect().top() - 16) / metrics.lineSpacing()))
        last_row = min(
            len(state.lines),
            int((event.rect().bottom() - 16) / metrics.lineSpacing()) + 2,
        )
        for row in range(first_row, last_row):
            line = state.lines[row]
            y = 16 + row * metrics.lineSpacing()
            self._paint_change_backgrounds(painter, row, metrics)
            self._paint_yank_highlights(painter, row, metrics)
            self._paint_selection(painter, row, metrics)
            painter.setPen(
                QColor(
                    "#c3ef85" if row == state.row and not self.read_only else "#68778a"
                )
            )
            painter.drawText(
                QRectF(4, y, 42, metrics.lineSpacing()),
                Qt.AlignmentFlag.AlignRight,
                self.line_number_text(row),
            )
            painter.setPen(QColor("#e8edf3"))
            painter.drawText(
                QRectF(58, y, self.width() - 64, metrics.lineSpacing()),
                Qt.AlignmentFlag.AlignLeft,
                line,
            )
            self._paint_syntax(painter, row, metrics)
            if any(mark_row == row for mark_row, _ in self.recovery_marks):
                painter.setPen(QPen(QColor("#f3bc82"), 1.5))
                painter.setBrush(QColor("#f3bc82"))
                painter.drawEllipse(
                    QRectF(49, y + metrics.lineSpacing() / 2 - 2.5, 5, 5)
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
            elif any(mark_row == row for mark_row, _ in self.success_marks):
                painter.setPen(QPen(QColor("#a8dfb0"), 1.5))
                middle = y + metrics.lineSpacing() / 2
                painter.drawLine(48, round(middle), 51, round(middle + 3))
                painter.drawLine(51, round(middle + 3), 56, round(middle - 3))
        if self.read_only:
            return
        cursor = self.cursor_rect
        if state.mode in {"insert", "replace"}:
            painter.setPen(QPen(QColor("#c3ef85"), 2))
            painter.drawLine(cursor.topLeft(), cursor.bottomLeft())
        else:
            painter.fillRect(cursor, QColor("#c3ef85"))
            painter.setPen(QColor("#17220e"))
            character = state.lines[state.row][state.column : state.column + 1]
            painter.drawText(cursor, Qt.AlignmentFlag.AlignLeft, character)
        painter.setPen(QPen(QColor("#819e5f" if self.hasFocus() else "#354458")))
        painter.drawRect(QRectF(self.rect()).adjusted(0, 0, -1, -1))
