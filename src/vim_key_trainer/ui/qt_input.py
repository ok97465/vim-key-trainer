"""Normalize local Qt key presses without guessing physical keyboard positions."""

from __future__ import annotations

# Standard library imports
import sys
from dataclasses import dataclass

# Third party imports
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

# Local imports
from vim_key_trainer.domain.keys import KeyToken


@dataclass(frozen=True)
class NormalizedKey:
    token: KeyToken | None
    keypad: bool
    reason: str | None
    text: str
    modifiers: tuple[str, ...]
    auto_repeat: bool
    native_scan_code: int


_MODIFIER_KEYS = {
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Meta,
    Qt.Key.Key_Alt,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_NumLock,
    Qt.Key.Key_ScrollLock,
}

_SPECIAL_KEYS: dict[int, str] = {
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backtab: "tab",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
}


def normalize_key_event(
    event: QKeyEvent, *, platform: str = sys.platform
) -> NormalizedKey:
    """Return one logical key, or a reason why the event is not scored.

    Qt's default macOS mapping uses ControlModifier for Command and
    MetaModifier for physical Control. Native scan codes are diagnostic only;
    KeypadModifier identifies numeric keypad *digits*, never arrow keys.
    """
    flags = event.modifiers()
    control_flag = (
        Qt.KeyboardModifier.MetaModifier
        if platform == "darwin"
        else Qt.KeyboardModifier.ControlModifier
    )
    meta_flag = (
        Qt.KeyboardModifier.ControlModifier
        if platform == "darwin"
        else Qt.KeyboardModifier.MetaModifier
    )
    modifiers = tuple(
        name
        for name, flag in (
            ("ctrl", control_flag),
            ("cmd" if platform == "darwin" else "meta", meta_flag),
            ("alt", Qt.KeyboardModifier.AltModifier),
            ("shift", Qt.KeyboardModifier.ShiftModifier),
        )
        if flags & flag
    )
    text = event.text()
    key = event.key()
    keypad = bool(flags & Qt.KeyboardModifier.KeypadModifier) and (
        len(text) == 1 and text in "0123456789"
    )

    def normalized(
        token: KeyToken | None = None, reason: str | None = None
    ) -> NormalizedKey:
        return NormalizedKey(
            token=token,
            keypad=keypad,
            reason=reason,
            text=text,
            modifiers=modifiers,
            auto_repeat=event.isAutoRepeat(),
            native_scan_code=event.nativeScanCode(),
        )

    if event.type() != QEvent.Type.KeyPress:
        return normalized(reason="not_key_press")
    if event.isAutoRepeat():
        return normalized(reason="auto_repeat")
    if key in _MODIFIER_KEYS:
        return normalized(reason="modifier")
    if (
        key == Qt.Key.Key_V
        and flags
        & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
    ) or (key == Qt.Key.Key_Insert and flags & Qt.KeyboardModifier.ShiftModifier):
        return normalized(reason="paste")
    if len(text) > 1:
        return normalized(reason="multiple_characters")
    if text and not text.isascii():
        return normalized(reason="non_ascii")

    name = _SPECIAL_KEYS.get(key)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        name = f"f{key - Qt.Key.Key_F1 + 1}"

    chord_modifiers = tuple(mod for mod in modifiers if mod != "shift")
    if chord_modifiers:
        if name is None and 32 <= key < 127:
            name = chr(key).lower()
        if name is None:
            return normalized(reason="unsupported_key")
        parts = modifiers + (name,)
        return normalized(KeyToken(kind="chord", value="+".join(parts)))
    if name is not None:
        return normalized(KeyToken(kind="special", value=name))
    if len(text) == 1 and text.isprintable():
        return normalized(KeyToken(kind="char", value=text))
    return normalized(reason="unsupported_key")
