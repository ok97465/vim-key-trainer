"""엔진 회귀 검증에서 사용하는 논리 키 입력 도우미."""

# Local imports
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditOutcome

__all__ = [
    "BACKSPACE",
    "ENTER",
    "ESC",
    "REDO",
    "chars",
    "chord",
    "execute",
    "type_keys",
]

BACKSPACE = KeyToken("special", "backspace")
ENTER = KeyToken("special", "enter")
ESC = KeyToken("special", "esc")
REDO = KeyToken("chord", "ctrl+r")


def chars(text: str) -> tuple[KeyToken, ...]:
    return tuple(KeyToken("char", character) for character in text)


def execute(engine: EditEngine, text: str) -> EditOutcome:
    outcome = EditOutcome(True)
    for key in chars(text):
        outcome = engine.submit(key)
        assert outcome.accepted, (text, key, outcome.message)
    return outcome


def type_keys(engine: EditEngine, text: str) -> None:
    execute(engine, text)


def chord(engine: EditEngine, value: str) -> None:
    outcome = engine.submit(KeyToken("chord", "ctrl+" + value))
    assert outcome.accepted, outcome.message
