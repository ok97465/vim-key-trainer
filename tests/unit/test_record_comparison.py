"""메모리 기록의 중복 반영, 보상과 입력·시간·정확도 우선순위를 검증한다."""

# Standard library imports
from dataclasses import replace
from uuid import uuid4

# Third party imports
import pytest
from record_factories import typing_result

# Local imports
from vim_key_trainer.domain.editing import EditPracticeSpec
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    SessionResult,
    SessionState,
)
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.session_service import PracticeSession


def test_duplicate_save_cannot_increment_completion_count_or_award_again() -> None:
    repository = MemoryResultRepository()
    result = typing_result()
    assert repository.save(result)
    assert not repository.save(result)
    assert repository.completed_count == 1
    assert repository.best_stars("numbers") == 3
    assert repository.best_for(result) == result


def test_aborted_attempt_does_not_award_stars_or_personal_best() -> None:
    repository = MemoryResultRepository()
    session = PracticeSession(PracticeSpec())
    session.abort()
    assert session.result is not None
    assert not repository.save(session.result)
    assert repository.completed_count == 0
    assert repository.best_for(session.result) is None
    assert repository.best_stars("numbers") == 0


def test_personal_best_prefers_accuracy_then_active_time() -> None:
    repository = MemoryResultRepository()
    initial = typing_result(seconds=2, mistakes=1)
    accurate = typing_result(seconds=5)
    faster = typing_result(seconds=3)
    slower = typing_result(seconds=4)
    assert repository.save(initial)
    assert repository.save(accurate)
    assert repository.save(faster)
    assert not repository.save(slower)
    assert repository.best_for(initial) == faster
    assert repository.completed_count == 4
    assert repository.best_stars("numbers") == 3


def test_new_seed_and_pause_usage_compare_separately() -> None:
    repository = MemoryResultRepository()
    first = typing_result(seed=0)
    different_seed = typing_result(seed=1, seconds=10)
    paused = replace(first, attempt_id=str(uuid4()), pause_count=1, elapsed_seconds=20)
    assert repository.save(first)
    assert repository.save(different_seed)
    assert repository.save(paused)
    assert repository.best_for(first) == first
    assert repository.best_for(different_seed) == different_seed
    assert repository.best_for(paused) == paused


def test_lower_result_does_not_reduce_lesson_stars() -> None:
    repository = MemoryResultRepository()
    repository.save(typing_result())
    assert not repository.save(typing_result(mistakes=5))
    assert repository.best_stars("numbers") == 3


def test_measured_time_replaces_an_unmeasured_best_at_equal_accuracy() -> None:
    repository = MemoryResultRepository()
    unmeasured = typing_result(seconds=0)
    assert repository.save(unmeasured)
    measured = typing_result(seconds=5)
    assert repository.save(measured)
    assert repository.best_for(unmeasured) == measured
    assert not repository.save(typing_result(seconds=0))
    assert repository.best_for(unmeasured) == measured


def edit_result(
    *, mode: str = "free", keys: int = 5, seconds: float = 3
) -> EditingSessionResult:
    guided = mode == "guided"
    return EditingSessionResult(
        attempt_id=str(uuid4()),
        lesson_id="editing_numbers",
        lesson_signature="same-start-goal-allowed-commands",
        mode="guided" if guided else "free",
        state=SessionState.COMPLETED,
        key_count=keys,
        baseline_keys=5,
        elapsed_seconds=seconds,
        correct=5 if guided else None,
        incorrect=0 if guided else None,
        accuracy=100 if guided else None,
        max_combo=5 if guided else None,
        stars=3,
        extra_hints=0,
        step_returns=0,
        pause_count=0,
        guide_level="step" if guided else "none",
    )


def test_editing_modes_have_independent_stars_and_records() -> None:
    repository = MemoryResultRepository()
    free = edit_result()
    guided = replace(edit_result(mode="guided"), stars=1)
    assert repository.save(free)
    assert repository.save(guided)
    assert repository.best_edit_stars(free.lesson_id, "free") == 3
    assert repository.best_edit_stars(free.lesson_id, "guided") == 1
    assert repository.best_for(free) == free
    assert repository.best_for(guided) == guided


def test_free_record_prefers_fewer_keys_then_measured_time() -> None:
    repository = MemoryResultRepository()
    initial = edit_result(keys=8, seconds=1)
    shorter = edit_result(keys=4, seconds=10)
    longer = edit_result(keys=5, seconds=0.1)
    faster = edit_result(keys=4, seconds=8)
    unmeasured = edit_result(keys=4, seconds=0)
    assert repository.save(initial)
    assert repository.save(shorter)
    assert not repository.save(longer)
    assert repository.save(faster)
    assert not repository.save(unmeasured)
    assert repository.best_for(initial) == faster


def test_guided_record_prefers_accuracy_before_time() -> None:
    repository = MemoryResultRepository()
    initial = replace(
        edit_result(mode="guided", seconds=1),
        key_count=6,
        incorrect=1,
        accuracy=500 / 6,
    )
    accurate = edit_result(mode="guided", seconds=10)
    faster = edit_result(mode="guided", seconds=8)
    assert repository.save(initial)
    assert repository.save(accurate)
    assert repository.save(faster)
    assert repository.best_for(initial) == faster


def test_editing_assistance_and_problem_conditions_compare_separately() -> None:
    repository = MemoryResultRepository()
    initial = edit_result()
    assert repository.save(initial)
    for changes in (
        {"baseline_keys": 4},
        {"lesson_signature": "different-start-or-goal-or-allowed"},
        {"extra_hints": 1},
        {"step_returns": 1},
        {"pause_count": 1},
        {"guide_level": "other-level"},
    ):
        changed = replace(
            initial,
            attempt_id=str(uuid4()),
            key_count=20,
            elapsed_seconds=100,
            **changes,
        )
        assert repository.save(changed)
        assert repository.best_for(changed) == changed
    assert repository.best_for(initial) == initial


def test_editing_result_is_applied_once_and_abort_cannot_award() -> None:
    repository = MemoryResultRepository()
    result = edit_result()
    assert repository.save(result)
    assert not repository.save(result)
    assert repository.completed_count == 1
    abort = replace(
        result, attempt_id=str(uuid4()), state=SessionState.ABORTED, stars=0
    )
    assert not repository.save(abort)
    assert not repository.save(abort)
    assert repository.completed_count == 1
    assert len(repository.results) == 2
    assert repository.best_for(result) == result
    assert repository.best_edit_stars(result.lesson_id, "free") == 3


def test_editing_stars_never_decrease() -> None:
    repository = MemoryResultRepository()
    initial = edit_result()
    assert repository.save(initial)
    assert not repository.save(replace(edit_result(keys=10), stars=1))
    assert repository.best_edit_stars(initial.lesson_id, "free") == 3


def test_generated_editing_records_keep_seed_and_length_separate() -> None:
    repository = MemoryResultRepository()
    spec = EditPracticeSpec("editing_numbers", seed=101)
    original = replace(edit_result(), practice_spec=spec)
    assert repository.save(original)
    for changes in (
        {"practice_spec": replace(spec, seed=102)},
        {"practice_spec": replace(spec, document_lines=40)},
    ):
        different = replace(
            original, attempt_id=str(uuid4()), elapsed_seconds=100, **changes
        )
        assert repository.save(different)
        assert repository.best_for(different) == different
    faster = replace(original, attempt_id=str(uuid4()), elapsed_seconds=1)
    assert repository.save(faster)
    assert repository.best_for(original) == faster
    assert repository.best_edit_stars("editing_numbers", "free") == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"max_combo": 999},
        {"accuracy": 0},
        {"elapsed_seconds": -1},
        {"state": SessionState.RUNNING},
        {"stars": 4},
    ],
)
def test_memory_storage_rejects_invalid_results_before_awarding_or_reserving_id(
    changes: dict[str, object],
) -> None:
    repository = MemoryResultRepository()
    result = typing_result()
    with pytest.raises(ValueError):
        repository.save(replace(result, **changes))
    assert repository.results == ()
    assert repository.completed_count == 0
    assert repository.best_stars(result.spec.exercise_id) == 0
    assert repository.best_for(result) is None
    assert repository.save(result)


def test_memory_storage_keeps_an_immutable_copy_of_error_statistics() -> None:
    errors = {"1": 1}
    result = replace(typing_result(mistakes=1), errors=errors)
    repository = MemoryResultRepository()
    repository.save(result)
    errors["1"] = 9
    saved = repository.results[0]
    assert isinstance(saved, SessionResult)
    assert saved.errors == {"1": 1}
    with pytest.raises(TypeError):
        saved.errors["1"] = 4  # type: ignore[index]
