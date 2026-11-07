"""미션 수집 보상은 서로 다른 완료 과제에만 한 번 반영한다."""

# Standard library imports
from dataclasses import replace
from uuid import uuid4

# Local imports
from vim_key_trainer.domain.achievements import summarize_learning
from vim_key_trainer.domain.sessions import EditingSessionResult, SessionState


def result(mission_id: str, *, stars: int = 3) -> EditingSessionResult:
    return EditingSessionResult(
        attempt_id=str(uuid4()),
        lesson_id=mission_id,
        content_version=1,
        lesson_signature="fixed-mission-goal",
        baseline_version=1,
        mode="guided",
        state=SessionState.COMPLETED,
        key_count=12,
        baseline_keys=12,
        elapsed_seconds=10,
        correct=12,
        incorrect=0,
        accuracy=100,
        max_combo=12,
        stars=stars,
        extra_hints=0,
        step_returns=0,
        pause_count=0,
        guide_level="step",
    )


def badge_ids(summary: object) -> set[str]:
    # Local imports
    from vim_key_trainer.domain.achievements import LearningSummary

    assert isinstance(summary, LearningSummary)
    return {badge.id for badge in summary.badges}


def test_empty_catalog_has_no_awards() -> None:
    summary = summarize_learning((), ())
    assert summary.total_missions == summary.completed_missions == 0
    assert summary.total_stars == summary.mastery_missions == 0
    assert not summary.badges


def test_repeated_attempts_cannot_farm_mission_stars_or_completion() -> None:
    first = result("mission_one", stars=1)
    repeated = replace(first, attempt_id=str(uuid4()), stars=2)
    mastered = result("mission_one")
    summary = summarize_learning((first, first, repeated, mastered), ("mission_one",))
    assert summary.completed_missions == summary.mastery_missions == 1
    assert summary.total_stars == 3
    assert summary.completed_ids == frozenset({"mission_one"})
    assert "first_repair" in badge_ids(summary)
    assert "three_documents" not in badge_ids(summary)


def test_different_modes_share_one_collection_slot_but_keep_best_stars() -> None:
    guided = result("mission_one", stars=2)
    free = replace(
        result("mission_one"),
        mode="free",
        correct=None,
        incorrect=None,
        accuracy=None,
        max_combo=None,
        key_count=10,
        guide_level="none",
    )
    summary = summarize_learning((guided, free), ("mission_one",))
    assert summary.completed_missions == 1 and summary.total_stars == 3
    assert {"own_shortcut", "independent_repair"} <= badge_ids(summary)


def test_current_catalog_versions_exclude_stale_unknown_and_aborted_results() -> None:
    matching = result("mission_current")
    stale = result("mission_stale")
    unknown = result("removed_mission")
    aborted = replace(result("mission_aborted"), state=SessionState.ABORTED, stars=0)
    ids = ("mission_current", "mission_stale", "mission_aborted")
    summary = summarize_learning(
        (matching, stale, unknown, aborted),
        ids,
        {"mission_current": 1, "mission_stale": 2, "mission_aborted": 1},
    )
    assert summary.completed_ids == frozenset({"mission_current"})
    assert summary.total_stars == 3
    assert "collection_complete" not in badge_ids(summary)


def test_three_unique_missions_unlock_milestones_without_speed_requirement() -> None:
    results = tuple(
        replace(result(f"mission_{index}"), elapsed_seconds=3600) for index in range(3)
    )
    summary = summarize_learning(results, (item.lesson_id for item in results))
    assert summary.completed_missions == summary.mastery_missions == 3
    assert summary.total_stars == 9
    assert {
        "three_documents",
        "collection_complete",
        "three_masterpieces",
    } <= badge_ids(summary)


def test_assistance_does_not_award_unassisted_or_shortcut_badges() -> None:
    assisted = replace(
        result("mission_one"),
        mode="free",
        correct=None,
        incorrect=None,
        accuracy=None,
        max_combo=None,
        key_count=5,
        extra_hints=1,
        guide_level="none",
    )
    summary = summarize_learning((assisted,), ("mission_one",))
    assert summary.completed_missions == 1
    assert "independent_repair" not in badge_ids(summary)
    assert "own_shortcut" not in badge_ids(summary)


def test_all_collection_thresholds_use_distinct_missions() -> None:
    results = tuple(result(f"mission_{index}", stars=1) for index in range(12))
    summary = summarize_learning(results, (item.lesson_id for item in results))
    assert {
        "first_repair",
        "three_documents",
        "six_documents",
        "twelve_documents",
    } <= badge_ids(summary)
    assert summary.mastery_missions == 0
    assert "three_masterpieces" not in badge_ids(summary)
