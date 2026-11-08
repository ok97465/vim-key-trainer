"""개인 기록 대결은 같은 조건의 전체 클리어 요약만 읽고 세션을 바꾸지 않는다."""

# Standard library imports
from dataclasses import replace
from uuid import uuid4

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditLesson, EditPracticeSpec
from vim_key_trainer.domain.sessions import EditingSessionResult, SessionState
from vim_key_trainer.services.challenge_rival import rival_for_session
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession


def session(clock: list[int], *, seed: int = 7) -> EditingSession:
    return EditingSession(
        create_edit_problem(EditPracticeSpec("editing_numbers", seed, 12)),
        challenge=ChallengeOptions(kind="bomb"),
        clock_ns=lambda: clock[0],
    )


def finish(practice: EditingSession, clock: list[int]) -> EditingSessionResult:
    while practice.state in {SessionState.READY, SessionState.RUNNING}:
        assert practice.expected_token is not None
        clock[0] += 100_000_000
        practice.submit(practice.expected_token)
    assert practice.result is not None
    assert practice.result.challenge is not None
    assert practice.result.challenge.full_clear
    return practice.result


def test_rival_uses_cumulative_summary_at_completed_segments_without_replay() -> None:
    reference = finish(session(reference_clock := [0]), reference_clock)
    clock = [0]
    practice = session(clock)
    snapshot = practice.engine.snapshot()
    rival = rival_for_session(practice, (reference,))
    assert rival is not None and rival.reference == reference
    assert rival.cumulative_seconds[-1] == pytest.approx(reference.elapsed_seconds)
    initial = rival.progress(practice)
    assert initial is not None
    assert initial.completed_segments == 0 and initial.delta_seconds is None
    assert practice.state == SessionState.READY
    assert practice.key_count == 0 and practice.engine.snapshot() == snapshot
    while practice.active_segment_index == 0:
        assert practice.expected_token is not None
        clock[0] += 10_000_000
        practice.submit(practice.expected_token)
    progress = rival.progress(practice)
    assert progress is not None and progress.completed_segments == 1
    assert progress.delta_seconds is not None and progress.delta_seconds < 0
    assert progress.reference_checkpoint_seconds == rival.cumulative_seconds[0]
    keys = practice.key_count
    clock[0] += 100_000_000
    later = rival.progress(practice)
    assert later is not None
    assert later.delta_seconds == progress.delta_seconds
    assert later.reference_progress >= progress.reference_progress
    assert practice.key_count == keys


@pytest.mark.parametrize("condition", ["pause", "return", "hint", "seed", "difficulty"])
def test_rival_requires_every_live_comparison_condition_to_match(
    condition: str,
) -> None:
    reference = finish(session(reference_clock := [0]), reference_clock)
    clock = [0]
    practice = session(clock, seed=8 if condition == "seed" else 7)
    if condition == "pause":
        practice.pause()
    elif condition == "return":
        practice.return_to_step(0)
    elif condition == "hint":
        practice.extra_hints = 1
    elif condition == "difficulty":
        practice = EditingSession(
            practice.lesson,
            challenge=ChallengeOptions(kind="bomb", difficulty="challenge"),
            clock_ns=lambda: clock[0],
        )
    assert rival_for_session(practice, (reference,)) is None


def test_changed_assistance_invalidates_an_already_selected_rival() -> None:
    reference = finish(session(reference_clock := [0]), reference_clock)
    practice = session([0])
    rival = rival_for_session(practice, (reference,))
    assert rival is not None
    practice.pause()
    assert rival.progress(practice) is None


def test_progress_and_completion_reuse_the_prepared_lesson_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = finish(session(reference_clock := [0]), reference_clock)
    clock = [0]
    practice = session(clock)
    rival = rival_for_session(practice, (reference,))
    assert rival is not None

    def unexpected_rehash(_lesson: EditLesson) -> str:
        raise AssertionError("준비한 긴 문제를 화면 갱신마다 다시 해싱했습니다.")

    monkeypatch.setattr(EditLesson, "signature", property(unexpected_rehash))
    for _ in range(3):
        assert rival.progress(practice) is not None
    finish(practice, clock)


def test_rival_excludes_partial_revenge_unmeasured_and_current_attempt() -> None:
    reference = finish(session(reference_clock := [0]), reference_clock)
    assert reference.challenge is not None
    clock = [0]
    practice = session(clock)
    invalid_sources = (
        replace(reference, state=SessionState.ABORTED, stars=0),
        replace(reference, elapsed_seconds=0),
        replace(reference, attempt_id=practice.attempt_id),
        replace(
            reference,
            challenge=replace(reference.challenge, full_clear=False),
            stars=0,
        ),
        replace(
            reference,
            challenge=replace(
                reference.challenge, revenge_of=reference.lesson_signature
            ),
            stars=0,
        ),
    )
    assert rival_for_session(practice, invalid_sources) is None
    assert rival_for_session(practice, (reference,)) is not None


def test_rival_selects_best_score_then_time_and_has_no_cross_mode_record() -> None:
    reference = finish(session(reference_clock := [0]), reference_clock)
    assert reference.challenge is not None
    slower = replace(
        reference,
        attempt_id=str(uuid4()),
        elapsed_seconds=reference.elapsed_seconds + 1,
    )
    free = replace(reference, mode="free", guide_level="none")
    practice = session([0])
    rival = rival_for_session(practice, (slower, reference, free))
    assert rival is not None and rival.reference == reference
    assert rival_for_session(practice, (free,)) is None


def test_failed_live_attempt_stops_record_eligibility_but_keeps_reference_summary() -> (
    None
):
    reference = finish(session(reference_clock := [0]), reference_clock)
    clock = [0]
    practice = session(clock)
    rival = rival_for_session(practice, (reference,))
    assert rival is not None and practice.expected_token is not None
    practice.submit(practice.expected_token)
    assert practice.remaining_seconds is not None
    clock[0] += round(practice.remaining_seconds * 1_000_000_000)
    practice.check_deadline(practice.timer_guard)
    progress = rival.progress(practice)
    assert progress is not None and not progress.eligible
    assert progress.completed_segments == 1
