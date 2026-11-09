"""Qt 이벤트의 정규화와 한 번만 전달되는 입력 경로를 검증한다."""

from __future__ import annotations

# Third party imports
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.ui.qt_input import NormalizedKey, normalize_key_event


def key_event(
    key: Qt.Key,
    text: str = "",
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    *,
    repeat: bool = False,
    event_type: QEvent.Type = QEvent.Type.KeyPress,
) -> QKeyEvent:
    return QKeyEvent(event_type, key, modifiers, text, repeat)


def test_shift_symbol_is_one_character() -> None:
    result = normalize_key_event(
        key_event(Qt.Key.Key_Dollar, "$", Qt.KeyboardModifier.ShiftModifier)
    )
    assert result.token == KeyToken(kind="char", value="$")
    assert result.modifiers == ("shift",)
    assert result.reason is None


@pytest.mark.parametrize(
    ("key", "text", "value"),
    [
        (Qt.Key.Key_Escape, "\x1b", "esc"),
        (Qt.Key.Key_Return, "\r", "enter"),
        (Qt.Key.Key_Enter, "\r", "enter"),
        (Qt.Key.Key_Backspace, "\b", "backspace"),
        (Qt.Key.Key_Tab, "\t", "tab"),
        (Qt.Key.Key_Left, "", "left"),
        (Qt.Key.Key_F1, "", "f1"),
    ],
)
def test_special_keys_use_tokens(key: Qt.Key, text: str, value: str) -> None:
    result = normalize_key_event(key_event(key, text))
    assert result.token == KeyToken(kind="special", value=value)


@pytest.mark.parametrize(
    ("platform", "modifier", "value"),
    [
        ("darwin", Qt.KeyboardModifier.MetaModifier, "ctrl+r"),
        ("darwin", Qt.KeyboardModifier.ControlModifier, "cmd+r"),
        ("linux", Qt.KeyboardModifier.ControlModifier, "ctrl+r"),
        ("win32", Qt.KeyboardModifier.ControlModifier, "ctrl+r"),
    ],
)
def test_physical_control_is_distinct_from_command(
    platform: str, modifier: Qt.KeyboardModifier, value: str
) -> None:
    result = normalize_key_event(
        key_event(Qt.Key.Key_R, "\x12", modifier), platform=platform
    )
    assert result.token == KeyToken(kind="chord", value=value)


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (key_event(Qt.Key.Key_Shift), "modifier"),
        (key_event(Qt.Key.Key_Control), "modifier"),
        (key_event(Qt.Key.Key_Meta), "modifier"),
        (key_event(Qt.Key.Key_1, "1", repeat=True), "auto_repeat"),
        (
            key_event(Qt.Key.Key_1, "1", event_type=QEvent.Type.KeyRelease),
            "not_key_press",
        ),
        (key_event(Qt.Key.Key_unknown, "가"), "non_ascii"),
        (key_event(Qt.Key.Key_unknown, "12"), "multiple_characters"),
        (
            key_event(Qt.Key.Key_V, "v", Qt.KeyboardModifier.ControlModifier),
            "paste",
        ),
        (key_event(Qt.Key.Key_V, "v", Qt.KeyboardModifier.MetaModifier), "paste"),
        (key_event(Qt.Key.Key_Insert, "", Qt.KeyboardModifier.ShiftModifier), "paste"),
    ],
)
def test_unscored_events_are_ignored(event: QKeyEvent, reason: str) -> None:
    result = normalize_key_event(event)
    assert result.token is None
    assert result.reason == reason


def test_keypad_detection_never_guesses_physical_positions() -> None:
    modifier = Qt.KeyboardModifier.KeypadModifier
    digit = normalize_key_event(key_event(Qt.Key.Key_1, "1", modifier))
    arrow = normalize_key_event(key_event(Qt.Key.Key_Left, "", modifier))
    ordinary = normalize_key_event(key_event(Qt.Key.Key_1, "1"))
    assert digit.keypad
    assert not arrow.keypad
    assert not ordinary.keypad
    assert digit.token == ordinary.token == KeyToken(kind="char", value="1")


@pytest.mark.parametrize(
    ("platform", "physical_control", "other_modifier"),
    [
        (
            "darwin",
            Qt.KeyboardModifier.MetaModifier,
            Qt.KeyboardModifier.ControlModifier,
        ),
        (
            "linux",
            Qt.KeyboardModifier.ControlModifier,
            Qt.KeyboardModifier.MetaModifier,
        ),
    ],
)
def test_visual_block_control_v_is_opt_in_and_never_accepts_command_paste(
    platform: str,
    physical_control: Qt.KeyboardModifier,
    other_modifier: Qt.KeyboardModifier,
) -> None:
    control_v = key_event(Qt.Key.Key_V, "\x16", physical_control)
    assert normalize_key_event(control_v, platform=platform).reason == "paste"
    assert normalize_key_event(
        control_v, platform=platform, allow_control_v=True
    ).token == KeyToken("chord", "ctrl+v")
    assert (
        normalize_key_event(
            key_event(Qt.Key.Key_V, "v", other_modifier),
            platform=platform,
            allow_control_v=True,
        ).reason
        == "paste"
    )


def test_qt_key_click_emits_exactly_one_logical_key(qtbot: QtBot) -> None:
    class InputWidget(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.inputs: list[NormalizedKey] = []

        def keyPressEvent(self, event: QKeyEvent) -> None:
            self.inputs.append(normalize_key_event(event))

    widget = InputWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.keyClicks(widget, "123")
    assert [item.token for item in widget.inputs] == [
        KeyToken(kind="char", value=char) for char in "123"
    ]
