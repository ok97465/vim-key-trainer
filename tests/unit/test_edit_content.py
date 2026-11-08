"""편집 콘텐츠의 읽기 경계와 실제 가이드·기준 풀이 재생 회귀 검증."""

# Standard library imports
import copy
import json
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from typing import Any

# Third party imports
import pytest

# Local imports
from vim_key_trainer.content.edit_loader import (
    get_edit_lesson,
    load_edit_lesson_json,
    load_edit_lessons,
    validate_edit_replay,
)
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import ESC, characters
from vim_key_trainer.domain.editing import EditSegment, goal_matches
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState


def raw_lesson(filename: str = "01_numbers.json") -> dict[str, Any]:
    resource = files("vim_key_trainer").joinpath(
        "resources", "lessons", "editing", filename
    )
    result: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    return result


def test_packaged_tasks_replay_guides_and_baselines_with_no_issues() -> None:
    report = load_edit_lessons()
    assert not report.issues
    assert len(report.lessons) == 6
    assert {lesson.id for lesson in report.lessons} == {
        "editing_numbers",
        "editing_delete_line",
        "editing_delete_word",
        "editing_append",
        "editing_compound",
        "editing_undo",
    }
    for lesson in report.lessons:
        validate_edit_replay(lesson)
        assert lesson.baseline_keys == len(lesson.baseline)
        assert len(lesson.signature) == 64
    assert get_edit_lesson("editing_numbers").id == "editing_numbers"
    with pytest.raises(ValueError, match="알 수 없거나"):
        get_edit_lesson("missing")


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("content_version", "1"),
        ("stage", "commands"),
        ("id", ""),
        ("title", "  "),
        ("description", ""),
        ("guide", []),
        ("allowed_commands", []),
        ("allowed_commands", ["c"]),
        ("allowed_commands", ["x", "x"]),
        ("free_enabled", "yes"),
        ("unexpected_field", True),
    ],
)
def test_invalid_task_fields_are_rejected(field: str, invalid: object) -> None:
    data = raw_lesson()
    data[field] = invalid
    with pytest.raises(ValueError):
        load_edit_lesson_json(json.dumps(data))


@pytest.mark.parametrize(
    "state",
    [
        {"lines": [], "row": 0, "column": 0},
        {"lines": ["hello"], "row": 1, "column": 0},
        {"lines": ["hello"], "row": 0, "column": 5},
        {"lines": [""], "row": 0, "column": 1},
        {"lines": ["한글"], "row": 0, "column": 0},
        {"lines": ["hello\n"], "row": 0, "column": 0},
        {"lines": ["hello"], "row": 0, "column": 0, "mode": "visual"},
        {"lines": ["hello"], "row": 0, "column": 0, "pending": "d"},
    ],
)
def test_invalid_initial_states_are_rejected(state: dict[str, object]) -> None:
    data = raw_lesson()
    data["initial"] = state
    with pytest.raises(ValueError):
        load_edit_lesson_json(json.dumps(data))


@pytest.mark.parametrize(
    "token",
    [
        {"kind": "char", "value": "한"},
        {"kind": "char", "value": "ab"},
        {"kind": "special", "value": "Esc"},
        {"kind": "chord", "value": "<C-r>"},
        {"kind": "special", "value": "tab"},
        {"kind": "char", "value": "c"},
    ],
)
def test_invalid_or_unsupported_guide_keys_are_rejected(
    token: dict[str, object],
) -> None:
    data = raw_lesson()
    data["guide"][0]["keys"] = [token]
    with pytest.raises(ValueError):
        load_edit_lesson_json(json.dumps(data))


def test_valid_key_not_allowed_by_task_is_rejected_during_replay() -> None:
    data = raw_lesson()
    data["allowed_commands"].remove("w")
    with pytest.raises(ValueError, match=r"guide.0.keys.0"):
        load_edit_lesson_json(json.dumps(data))


def test_guide_state_baseline_count_and_goal_are_replayed() -> None:
    data = raw_lesson()
    data["guide"][0]["expected"]["column"] = 0
    with pytest.raises(ValueError, match=r"guide.0.expected"):
        load_edit_lesson_json(json.dumps(data))

    data = raw_lesson()
    data["baseline"]["key_count"] += 1
    with pytest.raises(ValueError, match="기준 입력 수"):
        load_edit_lesson_json(json.dumps(data))

    data = raw_lesson()
    data["baseline"]["keys"] = [{"kind": "char", "value": "w"}]
    data["baseline"]["key_count"] = 1
    with pytest.raises(ValueError, match="baseline"):
        load_edit_lesson_json(json.dumps(data))

    data = raw_lesson()
    data["goal"]["lines"] = ["wrong goal"]
    with pytest.raises(ValueError, match="목표"):
        load_edit_lesson_json(json.dumps(data))


def test_final_goal_rejects_insert_pending_and_explicit_cursor_mismatch() -> None:
    lesson = get_edit_lesson("editing_numbers")
    assert goal_matches(lesson, EditorState(lesson.goal_lines, 0, 0))
    assert not goal_matches(lesson, EditorState(lesson.goal_lines, 0, 0, mode="insert"))
    assert not goal_matches(lesson, EditorState(lesson.goal_lines, 0, 0, pending="d"))
    assert not goal_matches(lesson, EditorState(lesson.goal_lines, command_line="/"))
    data = raw_lesson()
    data["goal"]["cursor"] = [0, 14]
    explicit = load_edit_lesson_json(json.dumps(data))
    assert not goal_matches(explicit, EditorState(explicit.goal_lines, 0, 0))
    assert goal_matches(explicit, EditorState(explicit.goal_lines, 0, 14))


def test_segment_cannot_start_with_unfinished_insert() -> None:
    initial = EditorState(("old",), mode="insert")
    builder = GuideBuilder(initial, frozenset({"i"}))
    builder.record(characters("new") + (ESC,), "새 단어를 입력합니다.")
    builder.finish_segment(0, 0)
    lesson = replace(
        get_edit_lesson("editing_numbers"),
        initial=initial,
        goal_lines=("newold",),
        guide=tuple(builder.steps),
        baseline=builder.steps[0].keys,
        baseline_keys=len(builder.steps[0].keys),
        segments=tuple(builder.segments),
    )
    with pytest.raises(ValueError, match="구간 경계"):
        validate_edit_replay(lesson)


def test_segment_target_must_fit_document_before_or_after_edit() -> None:
    lesson = get_edit_lesson("editing_numbers")
    segment = EditSegment("repair", 0, len(lesson.guide), 0, 2)
    with pytest.raises(ValueError, match="문서 범위"):
        validate_edit_replay(replace(lesson, segments=(segment,)))


@pytest.mark.parametrize(
    "changes",
    [
        {"start_step": False},
        {"end_step": 1.5},
        {"target_end_row": True},
        {"prerequisite_ids": ("earlier", "earlier")},
    ],
)
def test_invalid_segment_metadata_is_rejected(changes: dict[str, object]) -> None:
    segment = EditSegment("repair", 0, 1, 0, 1)
    with pytest.raises(ValueError):
        replace(segment, **changes)


def test_free_task_accepts_shorter_and_longer_solutions_than_baseline() -> None:
    lesson = get_edit_lesson("editing_numbers")
    for solution, length in [("$hxi8\x1b", 6), ("wwwhlxi8\x1b", 9)]:
        engine = EditEngine(lesson.initial, allowed_commands=lesson.allowed_commands)
        for character in solution:
            token = (
                KeyToken("special", "esc")
                if character == "\x1b"
                else KeyToken("char", character)
            )
            assert engine.submit(token).accepted
        assert goal_matches(lesson, engine.state)
        assert len(solution) == length
    assert lesson.baseline_keys == 7


def test_initial_equal_goal_is_only_valid_for_full_guide_task() -> None:
    lesson = get_edit_lesson("editing_undo")
    assert lesson.initial.lines == lesson.goal_lines
    assert not lesson.free_enabled
    resource = files("vim_key_trainer").joinpath(
        "resources", "lessons", "editing", "06_undo.json"
    )
    data = json.loads(resource.read_text(encoding="utf-8"))
    data["free_enabled"] = True
    with pytest.raises(ValueError, match="가이드 전용"):
        load_edit_lesson_json(json.dumps(data))


def test_bad_files_and_duplicate_ids_do_not_hide_valid_lessons(tmp_path: Path) -> None:
    valid = raw_lesson()
    (tmp_path / "01_valid.json").write_text(json.dumps(valid), encoding="utf-8")
    duplicate = copy.deepcopy(valid)
    (tmp_path / "02_duplicate.json").write_text(json.dumps(duplicate), encoding="utf-8")
    invalid = copy.deepcopy(valid)
    invalid["id"] = "bad_fields"
    invalid["guide"][0]["keys"][0]["value"] = "ab"
    (tmp_path / "03_bad_field.json").write_text(json.dumps(invalid), encoding="utf-8")
    (tmp_path / "04_bad_json.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "05_not_json.txt").write_text("ignored", encoding="utf-8")
    report = load_edit_lessons(tmp_path)
    assert [lesson.id for lesson in report.lessons] == [valid["id"]]
    assert {issue.file for issue in report.issues} == {
        "02_duplicate.json",
        "03_bad_field.json",
        "04_bad_json.json",
    }
    assert any(issue.field == "id" for issue in report.issues)
    assert any("guide.0.keys.0" in issue.field for issue in report.issues)
    assert all(issue.message for issue in report.issues)


def test_missing_and_empty_directory_report_errors(tmp_path: Path) -> None:
    empty = load_edit_lessons(tmp_path)
    assert not empty.lessons and empty.issues
    missing = load_edit_lessons(tmp_path / "missing")
    assert not missing.lessons and missing.issues


def test_signature_tracks_task_conditions_and_baseline_versions() -> None:
    data = raw_lesson()
    lesson = load_edit_lesson_json(json.dumps(data))
    data["baseline"]["version"] = 2
    updated = load_edit_lesson_json(json.dumps(data))
    assert lesson.signature != updated.signature
    data = raw_lesson()
    data["goal"]["cursor"] = [0, 14]
    assert lesson.signature != load_edit_lesson_json(json.dumps(data)).signature


@pytest.mark.parametrize("pending", ["dd", "999d2", "1000", "d0", "abc"])
def test_invalid_expected_pending_preserves_file_and_field_diagnostic(
    tmp_path: Path, pending: str
) -> None:
    data = raw_lesson()
    data["guide"][0]["expected"]["pending"] = pending
    resource = tmp_path / "bad_pending.json"
    resource.write_text(json.dumps(data), encoding="utf-8")
    report = load_edit_lessons(tmp_path)
    assert not report.lessons
    assert len(report.issues) == 1
    assert report.issues[0].file == resource.name
    assert report.issues[0].field == "guide.0.expected.pending"
    assert "대기 명령" in report.issues[0].message


@pytest.mark.parametrize("preference", [None, 0])
def test_guide_accepts_unspecified_or_matching_preferred_column(
    preference: int | None,
) -> None:
    data = raw_lesson("02_lines.json")
    data["guide"][0]["expected"]["preferred_column"] = preference
    lesson = load_edit_lesson_json(json.dumps(data))
    assert lesson.guide[0].expected.preferred_column == preference


def test_wrong_explicit_preferred_column_is_rejected() -> None:
    data = raw_lesson("02_lines.json")
    data["guide"][0]["expected"]["preferred_column"] = 2
    with pytest.raises(ValueError, match=r"guide.0.expected"):
        load_edit_lesson_json(json.dumps(data))


@pytest.mark.parametrize(
    "suffix",
    [
        {"kind": "char", "value": "h"},
        {"kind": "special", "value": "esc"},
    ],
)
def test_free_baseline_cannot_inflate_b_with_keys_after_terminal_goal(
    suffix: dict[str, str],
) -> None:
    data = raw_lesson()
    data["baseline"]["keys"].append(suffix)
    data["baseline"]["key_count"] += 1
    with pytest.raises(ValueError, match=r"baseline.keys.6"):
        load_edit_lesson_json(json.dumps(data))


def test_guide_only_baseline_can_revisit_goal_before_guide_exhaustion() -> None:
    data = raw_lesson("06_undo.json")
    data["baseline"]["keys"].append({"kind": "special", "value": "esc"})
    data["baseline"]["key_count"] += 1
    lesson = load_edit_lesson_json(json.dumps(data))
    assert not lesson.free_enabled
    assert lesson.baseline_keys == 3


def test_unavailable_intro_keeps_file_and_field_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = raw_lesson()
    data["initial"]["row"] = 999
    (tmp_path / "invalid.json").write_text(json.dumps(data), encoding="utf-8")
    report = load_edit_lessons(tmp_path)
    monkeypatch.setattr(
        "vim_key_trainer.content.edit_loader.load_edit_lessons",
        lambda: report,
    )
    with pytest.raises(ValueError) as error:
        get_edit_lesson("editing_numbers")
    assert "invalid.json" in str(error.value)
    assert "initial" in str(error.value)
