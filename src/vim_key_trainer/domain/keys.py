"""학습 대상 키의 논리적인 표현."""

# Standard library imports
from dataclasses import dataclass
from typing import Literal

KeyKind = Literal["char", "special", "chord"]


@dataclass(frozen=True, slots=True)
class KeyToken:
    kind: KeyKind
    value: str

    def __post_init__(self) -> None:
        if self.kind not in {"char", "special", "chord"}:
            raise ValueError("지원하지 않는 논리 키 종류입니다.")
        if not self.value:
            raise ValueError("키 값은 비어 있을 수 없습니다.")
        if self.kind == "char" and (
            len(self.value) != 1
            or not self.value.isascii()
            or not self.value.isprintable()
        ):
            raise ValueError("문자 키는 표시 가능한 ASCII 문자 하나여야 합니다.")

    @property
    def display(self) -> str:
        if self.kind == "char":
            return "<Space>" if self.value == " " else self.value
        special = {
            "esc": "Esc",
            "enter": "Enter",
            "backspace": "Backspace",
            "tab": "Tab",
        }
        if self.kind == "special":
            return f"<{special.get(self.value, self.value)}>"
        return f"<{self.value.replace('ctrl+', 'C-').replace('cmd+', 'Cmd-')}>"
