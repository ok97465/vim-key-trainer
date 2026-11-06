# Standard library imports
from dataclasses import replace
from uuid import uuid4

# Local imports
from vim_key_trainer.domain.exercises import PracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import SessionResult
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.session_service import PracticeSession


def completed_result(
    seed: int = 0, *, seconds: float = 4, mistakes: int = 0
) -> SessionResult:
    now_ns = 0
    session = PracticeSession(
        PracticeSpec(seed=seed, target_length=2), clock_ns=lambda: now_ns
    )
    for _ in range(mistakes):
        session.submit(KeyToken("char", "a"))
    session.submit(KeyToken("char", session.target[0]))
    now_ns = round(seconds * 1_000_000_000)
    session.submit(KeyToken("char", session.target[1]))
    assert session.result is not None
    return session.result


def test_duplicate_save_cannot_increment_completion_count_or_award_again() -> None:
    repository = MemoryResultRepository()
    result = completed_result()
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
    initial = completed_result(seconds=2, mistakes=1)
    accurate = completed_result(seconds=5)
    faster = completed_result(seconds=3)
    slower = completed_result(seconds=4)
    assert repository.save(initial)
    assert repository.save(accurate)
    assert repository.save(faster)
    assert not repository.save(slower)
    assert repository.best_for(initial) == faster
    assert repository.completed_count == 4
    assert repository.best_stars("numbers") == 3


def test_new_seed_and_pause_usage_compare_separately() -> None:
    repository = MemoryResultRepository()
    first = completed_result(seed=0)
    different_seed = completed_result(seed=1, seconds=10)
    paused = replace(first, attempt_id=str(uuid4()), pause_count=1, elapsed_seconds=20)
    assert repository.save(first)
    assert repository.save(different_seed)
    assert repository.save(paused)
    assert repository.best_for(first) == first
    assert repository.best_for(different_seed) == different_seed
    assert repository.best_for(paused) == paused


def test_lower_result_does_not_reduce_lesson_stars() -> None:
    repository = MemoryResultRepository()
    repository.save(completed_result())
    assert not repository.save(completed_result(mistakes=5))
    assert repository.best_stars("numbers") == 3


def test_zero_time_does_not_win_speed_comparison() -> None:
    repository = MemoryResultRepository()
    first = completed_result(seconds=5)
    repository.save(first)
    assert not repository.save(completed_result(seconds=0))
    assert repository.best_for(first) == first


def test_measured_time_replaces_an_unmeasured_best_at_equal_accuracy() -> None:
    repository = MemoryResultRepository()
    unmeasured = completed_result(seconds=0)
    assert repository.save(unmeasured)
    measured = completed_result(seconds=5)
    assert repository.save(measured)
    assert repository.best_for(unmeasured) == measured
    assert not repository.save(completed_result(seconds=0))
    assert repository.best_for(unmeasured) == measured


def test_symbol_stars_separate_game_rules_versions() -> None:
    repository = MemoryResultRepository()
    original = completed_result()
    assert repository.save(original)
    updated = replace(
        completed_result(mistakes=1), game_rules_version=original.game_rules_version + 1
    )
    assert repository.save(updated)
    assert repository.best_stars("numbers", original.game_rules_version) == 3
    assert repository.best_stars("numbers", updated.game_rules_version) == 1
