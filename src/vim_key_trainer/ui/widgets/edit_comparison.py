"""긴 현재 문서와 고정 목표를 독립된 스크롤 영역으로 비교한다."""

# Standard library imports
from math import ceil

# Third party imports
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Local imports
from vim_key_trainer.domain.document_display import (
    DocumentLanguage,
    compare_documents,
)
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditorState
from vim_key_trainer.ui.components import label
from vim_key_trainer.ui.widgets.edit_document import EditDocument
from vim_key_trainer.ui.widgets.edit_guide import EditGuideOverlay


class EditComparison(QWidget):
    """커서 이동·보기 조작은 문서 상태를 변경하지 않는다."""

    changes_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.practice_input = EditDocument()
        self.goal_document = EditDocument(read_only=True)
        self.diff = compare_documents(("",), ("",))
        self._goal_position: tuple[int, int] | None = None
        self.current_scroll = self._scroll_area(self.practice_input)
        self.goal_scroll = self._scroll_area(self.goal_document)
        self.guide_overlay = EditGuideOverlay(self.current_scroll.viewport())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for title, area in (
            ("현재 문서", self.current_scroll),
            ("목표 문서 · 수정 위치 강조", self.goal_scroll),
        ):
            column = QVBoxLayout()
            column.setSpacing(4)
            heading = label(title, "muted")
            heading.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            column.addWidget(heading)
            column.addWidget(area, 1)
            layout.addLayout(column, 1)

    @staticmethod
    def _scroll_area(document: EditDocument) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        area.setMinimumSize(100, 120)
        area.setWidget(document)
        return area

    def show_documents(self, current: EditorState, goal: EditorState) -> None:
        self.practice_input.bottom_padding = 0
        self._goal_position = None
        self.goal_document.show_state(goal)
        self.current_scroll.verticalScrollBar().setValue(0)
        self.goal_scroll.verticalScrollBar().setValue(0)
        self.current_scroll.horizontalScrollBar().setValue(0)
        self.goal_scroll.horizontalScrollBar().setValue(0)
        self.show_current(current)

    @property
    def viewport_rows(self) -> int:
        spacing = self.practice_input.document_metrics.lineSpacing()
        return max(1, int((self.current_scroll.viewport().height() - 32) / spacing))

    @property
    def viewport_top(self) -> int:
        spacing = self.practice_input.document_metrics.lineSpacing()
        # Scroll bars store integer pixels; preserve the row after round(row * spacing).
        return max(
            0, int((self.current_scroll.verticalScrollBar().value() + 0.5) / spacing)
        )

    def show_current(
        self, state: EditorState, *, follow_viewport: bool = False
    ) -> None:
        if follow_viewport:
            # zt can place even the final document line at the top of the view.
            self.practice_input.bottom_padding = max(
                0,
                round(
                    self.current_scroll.viewport().height()
                    - 2 * self.practice_input.document_metrics.lineSpacing()
                    - 24
                ),
            )
        self.practice_input.show_state(state)
        previous_count = self.remaining_changes
        self.diff = compare_documents(
            state.lines, self.goal_document.editor_state.lines
        )
        self._apply_highlights()
        if previous_count != self.remaining_changes:
            self.changes_changed.emit(self.remaining_changes)
        cursor = self.practice_input.cursor_rect
        if follow_viewport:
            self.current_scroll.verticalScrollBar().setValue(
                round(
                    state.viewport_top
                    * self.practice_input.document_metrics.lineSpacing()
                )
            )
            self._ensure_cursor_visible()
        else:
            self.current_scroll.ensureVisible(
                int(cursor.center().x()), int(cursor.center().y()), 24, 24
            )
        goal_position = (self.diff.goal_rows[state.row], state.column)
        if goal_position != self._goal_position:
            # 오타·대기 명령의 갱신은 사용자가 따로 스크롤한 목표를 되돌리지 않는다.
            goal_row, _ = goal_position
            metrics = self.goal_document.document_metrics
            self.goal_scroll.ensureVisible(
                int(cursor.center().x()),
                int(16 + (goal_row + 0.5) * metrics.lineSpacing()),
                24,
                24,
            )
            self._goal_position = goal_position

    @property
    def remaining_changes(self) -> int:
        return self.diff.remaining_count

    def _apply_highlights(self) -> None:
        self.practice_input.show_highlights(self.diff.current_spans)
        self.goal_document.show_highlights(self.diff.goal_spans)

    def set_language(self, language: DocumentLanguage) -> None:
        self.practice_input.set_language(language)
        self.goal_document.set_language(language)

    def set_font_size(self, size: int) -> None:
        for document in (self.practice_input, self.goal_document):
            document.font_size = size
            document.show_state(document.editor_state)
        self._apply_highlights()
        self._ensure_cursor_visible()

    def _ensure_cursor_visible(self) -> None:
        cursor = self.practice_input.cursor_rect
        self.current_scroll.ensureVisible(
            int(cursor.center().x()),
            int(cursor.center().y()),
            24,
            ceil(cursor.height() / 2) + 1,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        # The scroll area's layout has its new height after this resize event.
        QTimer.singleShot(0, self._ensure_cursor_visible)

    def set_paused(self, paused: bool) -> None:
        self.practice_input.paused = paused
        self.practice_input.update()
        self.guide_overlay.set_paused(paused)

    def show_guide(
        self,
        keys: tuple[KeyToken, ...],
        completed: int,
        *,
        description: str,
        progress: str,
    ) -> None:
        self.guide_overlay.show_guide(
            keys, completed, description=description, progress=progress
        )

    def clear_guide(self) -> None:
        self.guide_overlay.clear_guide()
