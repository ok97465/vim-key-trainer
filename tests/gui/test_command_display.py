"""명령 키와 짧은 설명의 표시 및 입력 간섭을 검증한다."""

from __future__ import annotations

# Standard library imports
import sys
from dataclasses import dataclass, replace

# Third party imports
import pytest
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.commands import CommandItem
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.ui.qt_input import NormalizedKey
from vim_key_trainer.ui.widgets import command_input as command_input_module
from vim_key_trainer.ui.widgets.command_input import CommandInput


@dataclass
class PaintedText:
    rect: QRectF
    text: str
    font: QFont
    color: QColor


def items(*, prefix: str = "뜻") -> tuple[CommandItem, ...]:
    return tuple(
        CommandItem(
            id=f"hint_{index}",
            tokens=tuple(KeyToken("char", character) for character in '"+d0'),
            meaning="커서 앞부터 줄 시작까지 삭제하고 클립보드에 보관합니다.",
            start_mode="Normal",
            follow_up="여기서 완결됩니다.",
            short_meaning=(
                "삭제·클립보드"
                if index == 0 and prefix == "뜻"
                else f"{prefix} {index}"
            ),
        )
        for index in range(8)
    )


def test_control_v_is_scored_only_when_it_is_the_actual_target(qtbot: QtBot) -> None:
    widget = CommandInput()
    qtbot.addWidget(widget)
    received: list[NormalizedKey] = []
    widget.key_received.connect(received.append)
    commands = (replace(items()[0], tokens=(KeyToken("chord", "ctrl+v"),)),)
    widget.show_commands(commands, 0, 0, 8)
    modifier = (
        Qt.KeyboardModifier.MetaModifier
        if sys.platform == "darwin"
        else Qt.KeyboardModifier.ControlModifier
    )
    qtbot.keyClick(widget, Qt.Key.Key_V, modifier)
    assert received[-1].token == KeyToken("chord", "ctrl+v")
    widget.show_commands(items(), 0, 0, 8)
    qtbot.keyClick(widget, Qt.Key.Key_V, modifier)
    assert received[-1].token is None
    assert received[-1].reason == "paste"


@pytest.fixture
def painted(monkeypatch: pytest.MonkeyPatch) -> list[PaintedText]:
    calls: list[PaintedText] = []

    class RecordingPainter(QPainter):
        def drawText(self, *args):
            if (
                len(args) == 3
                and isinstance(args[0], QRectF)
                and isinstance(args[2], str)
            ):
                calls.append(
                    PaintedText(
                        QRectF(args[0]),
                        args[2],
                        QFont(self.font()),
                        QColor(self.pen().color()),
                    )
                )
            return super().drawText(*args)

    monkeypatch.setattr(command_input_module, "QPainter", RecordingPainter)
    return calls


def test_hints_are_small_translucent_and_to_the_right_before_typing(
    qtbot: QtBot, painted: list[PaintedText]
) -> None:
    widget = CommandInput()
    qtbot.addWidget(widget)
    widget.resize(900, 240)
    commands = items()
    widget.show_commands(commands, 0, 0, 8)
    widget.show()
    widget.grab()
    hint = next(call for call in painted if call.text == commands[0].brief_meaning)
    assert 0 < hint.color.alphaF() < 1
    assert all(
        any(call.text == item.brief_meaning for call in painted) for item in commands
    )
    glyphs = [
        call
        for call in painted
        if call.text in {'"', "+", "d", "0"}
        and call.rect.left() < hint.rect.left()
        and call.rect.top() < hint.rect.bottom()
        and call.rect.bottom() > hint.rect.top()
    ]
    assert glyphs
    assert max(glyph.rect.right() for glyph in glyphs) < hint.rect.left()
    assert all(hint.font.pointSizeF() < glyph.font.pointSizeF() for glyph in glyphs)
    assert commands[0].brief_meaning in widget.accessibleDescription()


def test_refill_replaces_inline_hints_and_typing_still_emits_only_target_keys(
    qtbot: QtBot, painted: list[PaintedText]
) -> None:
    widget = CommandInput()
    qtbot.addWidget(widget)
    widget.resize(900, 240)
    before = items()
    widget.show_commands(before, 0, 0, 8)
    received: list[NormalizedKey] = []
    widget.key_received.connect(received.append)
    widget.show()
    widget.setFocus()
    qtbot.keyClicks(widget, '"+d0')
    assert [event.token for event in received] == list(before[0].tokens)
    after = items(prefix="새 뜻")
    widget.show_commands(after, 0, 0, 8, completed_offset=8)
    painted.clear()
    widget.grab()
    assert any(call.text == after[0].brief_meaning for call in painted)
    assert not any(call.text == before[0].brief_meaning for call in painted)
    assert after[0].brief_meaning in widget.accessibleDescription()


def test_long_special_key_labels_wrap_without_overlapping_the_hint(
    qtbot: QtBot, painted: list[PaintedText]
) -> None:
    widget = CommandInput()
    qtbot.addWidget(widget)
    widget.resize(709, 240)
    tokens = (
        KeyToken("char", "i"),
        KeyToken("char", "a"),
        KeyToken("char", "b"),
        KeyToken("special", "backspace"),
        KeyToken("char", "c"),
        KeyToken("special", "enter"),
        KeyToken("char", "d"),
        KeyToken("special", "esc"),
    )
    command = replace(items()[0], tokens=tokens, short_meaning="입력·수정 → Esc 복귀")
    widget.show_commands((command,) + items()[1:], 0, 0, 8)
    widget.show()
    widget.grab()
    hint = next(call for call in painted if call.text == command.brief_meaning)
    glyphs = [
        call
        for call in painted
        if call.text in {token.display for token in tokens}
        and call.rect.left() < hint.rect.left()
        and call.rect.top() < hint.rect.bottom()
        and call.rect.bottom() > hint.rect.top()
    ]
    assert {token.display for token in tokens} <= {glyph.text for glyph in glyphs}
    assert len({round(glyph.rect.top(), 1) for glyph in glyphs}) == 2
    assert max(glyph.rect.right() for glyph in glyphs) < hint.rect.left()
    assert all(hint.font.pointSizeF() < glyph.font.pointSizeF() for glyph in glyphs)


@pytest.mark.parametrize(
    "event_type",
    (
        QEvent.Type.FontChange,
        QEvent.Type.ApplicationFontChange,
        QEvent.Type.DevicePixelRatioChange,
    ),
)
def test_system_font_changes_refresh_command_layout(
    qtbot: QtBot,
    painted: list[PaintedText],
    monkeypatch: pytest.MonkeyPatch,
    event_type: QEvent.Type,
) -> None:
    widget = CommandInput()
    qtbot.addWidget(widget)
    widget.resize(900, 240)
    widget.show_commands(items(), 0, 0, 8)
    widget.show()
    widget.grab()
    previous = next(call.font for call in painted if call.text == '"')
    system_font = QFontDatabase.systemFont

    def changed_font(role: QFontDatabase.SystemFont) -> QFont:
        font = system_font(role)
        if role == QFontDatabase.SystemFont.FixedFont:
            font.setItalic(not previous.italic())
        return font

    monkeypatch.setattr(QFontDatabase, "systemFont", changed_font)
    QApplication.sendEvent(widget, QEvent(event_type))
    painted.clear()
    widget.grab()
    refreshed = next(call.font for call in painted if call.text == '"')
    assert refreshed.italic() != previous.italic()
