"""서로 다른 완료 문서의 별·훈장·꾸미기를 집계하고 중복 보상을 막는다."""

# Standard library imports
from dataclasses import replace
from uuid import uuid4

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.achievements import LearningSummary, summarize_learning
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.decorations import summarize_decorations
from vim_key_trainer.domain.preferences import AppearanceSettings
from vim_key_trainer.domain.sessions import EditingSessionResult, SessionState
from vim_key_trainer.services.edit_session import EditingSession


def result(mission_id: str, *, stars: int = 3) -> EditingSessionResult:
    return EditingSessionResult(
        attempt_id=str(uuid4()),
        lesson_id=mission_id,
        lesson_signature="fixed-mission-goal",
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


def badge_ids(summary: LearningSummary) -> set[str]:
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


def test_current_catalog_excludes_unknown_and_aborted_results() -> None:
    matching = result("mission_current")
    unknown = result("removed_mission")
    aborted = replace(result("mission_aborted"), state=SessionState.ABORTED, stars=0)
    summary = summarize_learning(
        (matching, unknown, aborted), ("mission_current", "mission_aborted")
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


def _complete(lesson_id: str) -> EditingSessionResult:
    lesson = get_edit_lesson(lesson_id)
    session = EditingSession(lesson, clock_ns=lambda: 0)
    for token in lesson.baseline:
        session.submit(token)
    assert session.result is not None
    return session.result


def test_unlocks_require_different_completed_lessons() -> None:
    first = _complete("editing_numbers")
    second = _complete("editing_delete_line")
    third = _complete("editing_delete_word")
    repeated = replace(first, attempt_id="different-attempt")
    progress = summarize_decorations((first, first, repeated, second))
    assert progress.completed_lessons == 2
    assert not progress.allows("mascot", "cat")
    progress = summarize_decorations((first, repeated, second, third))
    assert progress.completed_lessons == 3
    assert progress.allows("mascot", "cat")
    assert progress.allows("stamp", "star")
    assert not progress.allows("stamp", "flower")
    locked = AppearanceSettings("cat", "peach", "flower", False)
    assert progress.effective(locked) == replace(locked, stamp="check")


def test_repaired_document_and_revenge_do_not_unlock() -> None:
    now = 0
    lesson = get_edit_lesson("editing_numbers")
    session = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: now
    )
    session.submit(lesson.baseline[0])
    now = 10**15
    assert session.check_deadline()
    assert session.result is not None
    assert summarize_decorations((session.result,)).completed_lessons == 0
    revenge = session.create_revenge()
    while revenge.expected_token is not None:
        revenge.submit(revenge.expected_token)
    assert revenge.result is not None
    assert (
        summarize_decorations((session.result, revenge.result)).completed_lessons == 0
    )
