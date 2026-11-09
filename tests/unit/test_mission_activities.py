"""오늘의 미션·보스의 재현, 선택 목표와 한 번만 지급하는 보상을 검증한다."""

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
from vim_key_trainer.domain.activities import (
    ACTIVITY_RULE_VERSION,
    ActivitySpec,
    BonusObjective,
    daily_seed,
)
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.services.activity_problem_factory import (
    create_activity_problem,
    create_boss_problem,
    create_daily_problem,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import decode_result, encode_result
from vim_key_trainer.services.result_comparison import comparison_key
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository


def test_daily_local_date_is_injected_frozen_and_reconstructible() -> None:
    day = date(2026, 11, 8)
    lesson = create_daily_problem(today=lambda: day, timezone_name="Asia/Seoul")
    same = create_daily_problem(today=lambda: day, timezone_name="Asia/Seoul")
    assert lesson == same
    assert lesson.activity is not None
    assert lesson.activity.local_date == "2026-11-08"
    assert lesson.activity.timezone == "Asia/Seoul"
    assert create_activity_problem(lesson.activity) == lesson
    next_day = create_daily_problem(
        today=lambda: date(2026, 11, 9), timezone_name="Asia/Seoul"
    )
    other_zone = create_daily_problem(today=lambda: day, timezone_name="UTC")
    assert next_day.signature != lesson.signature != other_zone.signature
    session = EditingSession(lesson)
    assert session.lesson.activity.local_date == "2026-11-08"


@pytest.mark.parametrize("seed", [0, 23, 999])
@pytest.mark.parametrize("mode", ["guided", "free"])
def test_independent_boss_has_three_techniques_and_both_modes_replay(
    seed: int, mode: str
) -> None:
    objectives = ("no_hints", "baseline_keys")
    lesson = create_boss_problem(seed, objectives=objectives)
    assert lesson.activity is not None and lesson.activity.kind == "boss"
    assert create_activity_problem(lesson.activity) == lesson
    assert lesson.practice_spec is None and lesson.id == "boss_observatory"
    assert len(lesson.segments) == 3
    assert len(lesson.initial.lines) == len(lesson.goal_lines) == 18
    assert any(key == KeyToken("chord", "ctrl+a") for key in lesson.baseline)
    session = EditingSession(lesson, mode)
    for key in lesson.baseline:
        assert session.submit(key) == InputResult.ACCEPTED
    assert session.state == SessionState.COMPLETED
    result = session.result
    assert result is not None and result.activity == lesson.activity
    assert all(objective.achieved for objective in result.bonus_objectives)
    assert result.bonus_points == 500
    assert decode_result(encode_result(result)) == result


def test_objective_failure_does_not_change_correct_completion_or_stars() -> None:
    lesson = create_boss_problem(23, objectives=("no_hints", "baseline_keys"))
    session = EditingSession(lesson, "free")
    session.reveal_hint()
    session.submit(KeyToken("char", "Q"))
    for key in lesson.baseline:
        assert session.submit(key) == InputResult.ACCEPTED
    result = session.result
    assert result is not None and result.state == SessionState.COMPLETED
    assert result.stars == 1
    assert not any(objective.achieved for objective in result.bonus_objectives)
    assert result.bonus_points == 0
    assert decode_result(encode_result(result)) == result


def test_partial_bomb_and_revenge_do_not_award_objective_bonus() -> None:
    clock = [0]
    lesson = create_boss_problem(23, objectives=("no_hints", "all_direct"))
    session = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: clock[0]
    )
    session.submit(KeyToken("char", "Q"))
    for _ in lesson.segments:
        clock[0] += 100_000_000_000
        session.check_deadline()
    result = session.result
    assert result is not None
    assert not any(objective.achieved for objective in result.bonus_objectives)
    assert result.bonus_points == 0
    revenge = session.create_revenge()
    while revenge.state != SessionState.COMPLETED:
        assert revenge.submit(revenge.expected_token) == InputResult.ACCEPTED
    assert revenge.result is not None and revenge.result.bonus_points == 0
    assert decode_result(encode_result(revenge.result)) == revenge.result


def test_invalid_daily_seed_date_rules_and_objectives_are_rejected() -> None:
    lesson = create_daily_problem(
        today=lambda: date(2026, 11, 8), timezone_name="Asia/Seoul"
    )
    assert lesson.activity is not None
    for changes in (
        {"seed": lesson.activity.seed + 1},
        {"local_date": "2026-02-30"},
        {"version": ACTIVITY_RULE_VERSION + 1},
        {"objectives": ("no_hints", "no_hints")},
    ):
        with pytest.raises(ValueError):
            replace(lesson.activity, **changes)
    with pytest.raises(ValueError):
        ActivitySpec("boss", 1, "editing_compound", 0, 24)


def test_reconstructed_daily_problem_cannot_bypass_undo_exclusion() -> None:
    spec = ActivitySpec(
        "daily",
        ACTIVITY_RULE_VERSION,
        "editing_undo",
        daily_seed("editing_undo", "2026-11-08", "Asia/Seoul"),
        local_date="2026-11-08",
        timezone="Asia/Seoul",
    )
    with pytest.raises(ValueError, match="실제로 수정"):
        create_activity_problem(spec)


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
