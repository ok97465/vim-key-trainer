"""로컬 날짜 고정·독립 보스 재생·선택 목표·기록 왕복 검증."""

# Standard library imports
from dataclasses import replace
from datetime import date

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.activities import (
    ACTIVITY_RULE_VERSION,
    ActivitySpec,
    daily_seed,
)
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.services.activity_problem_factory import (
    create_activity_problem,
    create_boss_problem,
    create_daily_problem,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import decode_result, encode_result


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
    assert mode in {"guided", "free"}
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


def test_daily_and_boss_reward_keys_deduplicate_retry_conditions() -> None:
    lesson = create_daily_problem(
        today=lambda: date(2026, 11, 8), timezone_name="Asia/Seoul"
    )
    assert lesson.activity is not None
    changed_bonus = replace(
        lesson, activity=replace(lesson.activity, objectives=("no_hints",))
    )
    assert lesson.signature != changed_bonus.signature
    assert changed_bonus.activity is not None
    assert lesson.activity.reward_key() == changed_bonus.activity.reward_key()
    boss = create_boss_problem(23)
    assert boss.activity is not None
    repeated_boss = create_boss_problem(23)
    assert repeated_boss.activity is not None
    assert boss.activity.reward_key() == repeated_boss.activity.reward_key()


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
