"""명령 레슨의 토큰 경계와 학습 콘텐츠 회귀 검증."""

# Standard library imports
import json
from importlib.resources import files
from typing import Any

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.command_loader import (
    get_command_lesson,
    list_command_lessons,
    load_command_lesson_json,
)
from vim_key_trainer.domain.keys import KeyToken


def raw_lesson() -> dict[str, Any]:
    resource = files("vim_key_trainer").joinpath(
        "resources", "lessons", "commands", "01_movement.json"
    )
    result: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    return result


def test_packaged_lessons_cover_required_commands_without_executing_them() -> None:
    lessons = list_command_lessons()
    assert len(lessons) == 4
    assert len({lesson.id for lesson in lessons}) == 4
    assert all(8 <= len(lesson.items) <= 12 for lesson in lessons)
    assert all(8 <= lesson.display_count <= 12 for lesson in lessons)
    items = [item for lesson in lessons for item in lesson.items]
    displays = {item.display for item in items}
    assert {
        "h",
        "j",
        "k",
        "l",
        "w",
        "b",
        "0",
        "^",
        "$",
        "gg",
        "G",
        "3j",
        "10l",
        "2w",
        "x",
        "dd",
        "2dd",
        "dw",
        "d2w",
        "2d3w",
        "8ciw",
        "22gg",
        "qa",
        '"+y',
        "u",
        "<C-r>",
    } <= displays
    assert all(item.execution_support == "typing_only" for item in items)
    assert all(item.meaning.strip() and item.start_mode.strip() for item in items)
    assert get_command_lesson(lessons[0].id) is lessons[0]
    with pytest.raises(ValueError, match="알 수 없는"):
        get_command_lesson("unknown")


def test_display_notation_is_never_parsed_as_input() -> None:
    lesson = get_command_lesson("commands_insert")
    assert lesson.items[0].tokens == (
        KeyToken("char", "i"),
        KeyToken("char", "h"),
        KeyToken("char", "i"),
        KeyToken("special", "esc"),
    )
    assert lesson.items[0].display == "ihi<Esc>"
    assert any(KeyToken("special", "enter") in item.tokens for item in lesson.items)
    assert any(KeyToken("special", "backspace") in item.tokens for item in lesson.items)
    assert any(KeyToken("char", " ") in item.tokens for item in lesson.items)
    assert any(KeyToken("char", "<") in item.tokens for item in lesson.items)
    redo = next(item for item in lesson.items if item.id == "redo")
    assert redo.tokens == (KeyToken("chord", "ctrl+r"),)
    assert len(redo.tokens) == 1


def test_context_fragments_explain_unfinished_real_vim_actions() -> None:
    items = {item.id: item for item in get_command_lesson("commands_context").items}
    assert "공백" in items["change_inner_word_eight"].meaning
    assert "Esc" in items["change_inner_word_eight"].follow_up
    assert "q로 종료" in items["record_macro_a"].follow_up
    assert "motion" in items["clipboard_yank"].follow_up
    assert "Normal" in items["clipboard_yank"].start_mode


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("schema_version", "1"),
        ("content_version", 0),
        ("stage", "editing"),
        ("id", ""),
        ("title", "  "),
        ("description", ""),
        ("difficulty", ""),
        ("display_count", 0),
        ("display_count", 13),
        ("items", []),
        ("tags", [""]),
        ("unexpected_field", "ignored?"),
    ],
)
def test_invalid_lesson_boundary_is_rejected(field: str, invalid: object) -> None:
    data = raw_lesson()
    data[field] = invalid
    with pytest.raises(ValueError):
        load_command_lesson_json(json.dumps(data))


def test_duplicate_command_ids_are_rejected() -> None:
    data = raw_lesson()
    data["items"][1]["id"] = data["items"][0]["id"]
    with pytest.raises(ValueError, match="고유"):
        load_command_lesson_json(json.dumps(data))


@pytest.mark.parametrize(
    "token",
    [
        {"kind": "char", "value": "ab"},
        {"kind": "char", "value": "한"},
        {"kind": "char", "value": "\n"},
        {"kind": "special", "value": "Esc"},
        {"kind": "special", "value": "unknown"},
        {"kind": "chord", "value": "<C-r>"},
        {"kind": "char", "value": "h", "extra": True},
    ],
)
def test_invalid_or_unreachable_tokens_are_rejected(token: dict[str, object]) -> None:
    data = raw_lesson()
    data["items"][0]["tokens"] = [token]
    with pytest.raises(ValueError):
        load_command_lesson_json(json.dumps(data))


def test_empty_tokens_and_unknown_execution_support_are_rejected() -> None:
    data = raw_lesson()
    data["items"][0]["tokens"] = []
    with pytest.raises(ValueError):
        load_command_lesson_json(json.dumps(data))
    data = raw_lesson()
    data["items"][0]["execution_support"] = "external_vim"
    with pytest.raises(ValueError):
        load_command_lesson_json(json.dumps(data))
