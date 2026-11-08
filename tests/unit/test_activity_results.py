"""선택 목표 결과 검증과 일일·보스 보상의 반복 방지."""

# Standard library imports
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.achievements import summarize_activities
from vim_key_trainer.domain.activities import BonusObjective
from vim_key_trainer.domain.sessions import EditingSessionResult
from vim_key_trainer.services.activity_problem_factory import (
    create_boss_problem,
    create_daily_problem,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import decode_result, encode_result
from vim_key_trainer.services.result_comparison import comparison_key
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository


def completed(
    *, daily: bool = False, objectives: tuple[BonusObjective, ...] = ("no_hints",)
) -> EditingSessionResult:
    lesson = (
        create_daily_problem(
            today=lambda: date(2026, 11, 8),
            timezone_name="Asia/Seoul",
            objectives=objectives,
        )
        if daily
        else create_boss_problem(23, objectives=objectives)
    )
    session = EditingSession(lesson, "free", clock_ns=lambda: 0)
    for key in lesson.baseline:
        session.submit(key)
    assert session.result is not None
    return session.result


@pytest.mark.parametrize("daily", [False, True])
def test_activity_json_database_roundtrip_and_idempotent_bonus(
    tmp_path: Path, daily: bool
) -> None:
    result = completed(daily=daily)
    assert decode_result(encode_result(result)) == result
    repository = SqliteResultRepository(tmp_path / "activity.sqlite3")
    assert repository.save(result)
    assert not repository.save(result)
    repeated = replace(result, attempt_id=str(uuid4()))
    repository.save(repeated)
    summary = summarize_activities(repository.results)
    assert summary.daily_completions == int(daily)
    assert summary.boss_completions == int(not daily)
    assert len(summary.completed_keys) == 1
    assert summary.bonus_points == 200
    repository.close()
    reopened = SqliteResultRepository(tmp_path / "activity.sqlite3")
    assert summarize_activities(reopened.results) == summary
    reopened.close()


@pytest.mark.parametrize("daily", [False, True])
def test_changing_optional_goal_does_not_farm_same_mission_reward(daily: bool) -> None:
    first = completed(daily=daily)
    changed = completed(daily=daily, objectives=("baseline_keys",))
    assert comparison_key(first) != comparison_key(changed)
    summary = summarize_activities((first, first, changed, changed))
    assert len(summary.completed_keys) == 1
    assert summary.bonus_points == 500
    combined = completed(daily=daily, objectives=("no_hints", "baseline_keys"))
    assert summarize_activities((first, changed, combined)) == summary


@pytest.mark.parametrize("daily", [False, True])
@pytest.mark.parametrize("nested", ["activity", "bonus_objectives"])
def test_unknown_nested_activity_fields_cannot_enter_history(
    daily: bool, nested: str
) -> None:
    payload = json.loads(encode_result(completed(daily=daily)))
    value = payload["data"][nested]
    if isinstance(value, list):
        value = value[0]
    value["unknown_condition"] = True
    with pytest.raises(ValueError, match="알 수 없는 필드"):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [("seed", 9), ("local_date", "2026-11-09"), ("document_lines", 40)],
)
def test_daily_result_rejects_changed_generation_conditions(
    field: str, value: object
) -> None:
    payload = json.loads(encode_result(completed(daily=True)))
    payload["data"]["activity"][field] = value
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


def test_boss_result_cannot_claim_a_normal_profile_or_generated_spec() -> None:
    result = completed()
    with pytest.raises(ValueError, match="보스"):
        decode_result(encode_result(replace(result, lesson_id="editing_compound")))


def test_bonus_cannot_be_forged_dropped_reordered_or_attached_after_start() -> None:
    result = completed(objectives=("no_hints", "baseline_keys"))
    for change in ("achieved", "drop", "order", "no_activity"):
        payload = json.loads(encode_result(result))
        if change == "achieved":
            payload["data"]["bonus_objectives"][0]["achieved"] = False
        elif change == "drop":
            payload["data"]["bonus_objectives"].pop()
        elif change == "order":
            payload["data"]["bonus_objectives"].reverse()
        else:
            payload["data"]["activity"] = None
        with pytest.raises(ValueError, match="선택 목표"):
            decode_result(json.dumps(payload))
