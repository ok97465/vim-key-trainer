"""도전 결과의 점수·저장·복수전 재구성과 같은 조건의 기록 대결을 검증한다."""

# Standard library imports
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.achievements import summarize_learning
from vim_key_trainer.domain.challenge import (
    TIME_RULE_VERSION,
    ChallengeOptions,
    ChallengeSummary,
    SegmentResult,
)
from vim_key_trainer.domain.editing import EditLesson, EditPracticeSpec
from vim_key_trainer.domain.game_rules import bomb_score, bomb_segment_score
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.services.activity_problem_factory import create_boss_problem
from vim_key_trainer.services.challenge_rival import rival_for_session
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.recorded_practice import create_recorded_revenge
from vim_key_trainer.services.result_codec import decode_result, encode_result
from vim_key_trainer.services.result_comparison import comparison_key, is_better_result
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.services.sqlite_repository import SqliteResultRepository


def challenge_result(
    *,
    failed: bool = False,
    auto_repair: bool = True,
    revenge: bool = False,
    elapsed: float = 2,
) -> EditingSessionResult:
    segments = (
        SegmentResult("repair-1", "direct", elapsed, 10),
        SegmentResult(
            "repair-2",
            "timeout" if failed else "direct",
            10 if failed else elapsed,
            10,
            auto_repaired=failed and auto_repair,
        ),
    )
    summary = ChallengeSummary(
        options=ChallengeOptions(kind="bomb", auto_repair=auto_repair),
        time_rule_version=TIME_RULE_VERSION,
        segments=segments,
        full_clear=not failed,
        score=bomb_score(segments=segments),
        max_chain=1 if failed else 2,
        revenge_of="same-problem" if revenge else None,
    )
    return EditingSessionResult(
        attempt_id=str(uuid4()),
        lesson_id="mission_test",
        lesson_signature="same-problem",
        mode="guided",
        state=SessionState.COMPLETED,
        key_count=5,
        baseline_keys=5,
        elapsed_seconds=sum(segment.elapsed_seconds for segment in segments),
        correct=5,
        incorrect=0,
        accuracy=100,
        max_combo=5,
        stars=0 if failed or revenge else 3,
        extra_hints=0,
        step_returns=0,
        pause_count=0,
        guide_level="step",
        challenge=summary,
    )


def test_bomb_score_has_bounded_time_bonus_and_no_failure_credit() -> None:
    assert (
        bomb_segment_score(verdict="direct", elapsed_seconds=0, limit_seconds=10)
        == 1500
    )
    assert (
        bomb_segment_score(verdict="direct", elapsed_seconds=9, limit_seconds=10)
        == 1050
    )
    assert (
        bomb_segment_score(verdict="timeout", elapsed_seconds=10, limit_seconds=10) == 0
    )
    for assistance in ({"extra_hints": 1}, {"step_returns": 1}):
        assert (
            bomb_segment_score(
                verdict="direct", elapsed_seconds=1, limit_seconds=10, **assistance
            )
            == 1000
        )


@pytest.mark.parametrize("auto_repair", [False, True])
@pytest.mark.parametrize("revenge", [False, True])
def test_partial_and_revenge_result_roundtrip_without_completion_reward(
    tmp_path: Path, auto_repair: bool, revenge: bool
) -> None:
    result = challenge_result(failed=True, auto_repair=auto_repair, revenge=revenge)
    assert decode_result(encode_result(result)) == result
    path = tmp_path / "bomb.sqlite3"
    repository = SqliteResultRepository(path)
    assert not repository.save(result)
    assert not repository.save(result)
    assert repository.completed_count == 0
    assert repository.best_for(result) is None
    assert repository.best_edit_stars("mission_test", "guided") == 0
    assert summarize_learning(repository.results, ("mission_test",)).completed_ids == (
        frozenset()
    )
    repository.close()
    reopened = SqliteResultRepository(path)
    assert reopened.results == (result,)
    assert reopened.completed_count == 0
    assert reopened.best_for(result) is None
    reopened.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM lesson_progress"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM comparison_bests"
        ).fetchone() == (0,)


def test_full_clear_awards_once_but_clean_revenge_does_not_award() -> None:
    repository = MemoryResultRepository()
    clear = challenge_result()
    revenge = challenge_result(revenge=True)
    assert repository.save(clear)
    assert not repository.save(clear)
    assert not repository.save(revenge)
    assert repository.completed_count == 1
    assert repository.best_for(clear) == clear
    assert repository.best_for(revenge) is None
    summary = summarize_learning(repository.results, ("mission_test",))
    assert summary.completed_ids == frozenset({"mission_test"})
    assert summary.total_stars == 3


def test_bomb_comparison_separates_every_frozen_judgement_condition() -> None:
    result = challenge_result()
    assert result.challenge is not None
    normal = replace(result, challenge=None)
    assert comparison_key(normal) != comparison_key(result)
    for options in (
        replace(result.challenge.options, difficulty="relaxed"),
        replace(result.challenge.options, difficulty="challenge"),
        replace(result.challenge.options, auto_repair=False),
    ):
        changed = replace(result, challenge=replace(result.challenge, options=options))
        assert comparison_key(changed) != comparison_key(result)
    assert comparison_key(result) != comparison_key(challenge_result(revenge=True))
    for condition in ({"extra_hints": 1}, {"step_returns": 1}, {"pause_count": 1}):
        assert comparison_key(replace(result, **condition)) != comparison_key(result)


def test_bomb_best_prefers_score_then_time_then_user_keys() -> None:
    original = challenge_result(elapsed=3)
    faster = challenge_result(elapsed=2)
    assert is_better_result(faster, original)
    assert not is_better_result(original, faster)
    assert not is_better_result(challenge_result(failed=True), original)
    assert faster.challenge is not None
    # 같은 보너스 구간 안에서는 정확한 활성 시간이 우선이다.
    equal_score = replace(
        faster,
        attempt_id=str(uuid4()),
        elapsed_seconds=faster.elapsed_seconds + 0.0001,
    )
    assert is_better_result(faster, equal_score)
    fewer_keys = replace(
        faster, attempt_id=str(uuid4()), key_count=4, correct=4, max_combo=4
    )
    assert is_better_result(fewer_keys, faster)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("full_clear", True),
        ("score", 999999),
        ("max_chain", 9),
        ("time_rule_version", TIME_RULE_VERSION + 1),
        ("revenge_of", "different-problem"),
    ],
)
def test_bomb_codec_rejects_false_summary_before_rewarding(
    field: str, value: object
) -> None:
    payload = json.loads(encode_result(challenge_result(failed=True)))
    payload["data"]["challenge"][field] = value
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("segment_id", "repair-1"),
        ("verdict", "direct"),
        ("elapsed_seconds", 9),
        ("limit_seconds", 0),
        ("limit_seconds", 1e-100),
        ("limit_seconds", 10.001),
        ("auto_repaired", False),
    ],
)
def test_bomb_codec_rejects_inconsistent_segment_verdicts(
    field: str, value: object
) -> None:
    payload = json.loads(encode_result(challenge_result(failed=True)))
    segment = payload["data"]["challenge"]["segments"][1]
    segment[field] = value
    if field == "auto_repaired":
        # 자동 수정 끄기 정책에서는 자동 복구 판정을 받을 수 없다.
        segment[field] = True
        payload["data"]["challenge"]["options"]["auto_repair"] = False
    with pytest.raises(ValueError):
        decode_result(json.dumps(payload))


def test_guided_limit_cannot_use_the_free_document_time_allowance() -> None:
    result = challenge_result()
    assert result.challenge is not None
    segments = tuple(
        replace(segment, limit_seconds=90.1) for segment in result.challenge.segments
    )
    changed = replace(
        result,
        challenge=replace(
            result.challenge, segments=segments, score=bomb_score(segments=segments)
        ),
    )
    with pytest.raises(ValueError, match="시간"):
        decode_result(encode_result(changed))


@pytest.mark.parametrize(
    "unsupported", [None, "segments", "segment_id", "auto_repair", "revenge"]
)
def test_free_challenge_requires_one_document_without_recovery_or_revenge(
    unsupported: str | None,
) -> None:
    result = challenge_result()
    assert result.challenge is not None
    segments = (SegmentResult("document", "direct", 2, 900),)
    if unsupported == "segments":
        segments += (SegmentResult("other", "direct", 2, 900),)
    elif unsupported == "segment_id":
        segments = (replace(segments[0], segment_id="repair-1"),)
    elif unsupported == "auto_repair":
        segments = (
            replace(
                segments[0], verdict="timeout", elapsed_seconds=900, auto_repaired=True
            ),
        )
    summary = replace(
        result.challenge,
        segments=segments,
        score=bomb_score(segments=segments),
        full_clear=unsupported != "auto_repair",
        max_chain=0 if unsupported == "auto_repair" else len(segments),
        revenge_of=result.lesson_signature if unsupported == "revenge" else None,
    )
    changed = replace(
        result,
        mode="free",
        correct=None,
        incorrect=None,
        accuracy=None,
        max_combo=None,
        elapsed_seconds=sum(segment.elapsed_seconds for segment in segments),
        stars=0 if unsupported in ("auto_repair", "revenge") else 3,
        challenge=summary,
    )
    if unsupported is None:
        assert decode_result(encode_result(changed)) == changed
    else:
        with pytest.raises(ValueError, match="문서 전체"):
            decode_result(encode_result(changed))


def test_last_auto_repair_cannot_award_completion_stars() -> None:
    failed = challenge_result(failed=True)
    repository = MemoryResultRepository()
    with pytest.raises(ValueError):
        repository.save(replace(failed, stars=1))
    assert repository.results == ()
    assert repository.completed_count == 0
    assert not repository.save(failed)


def test_waiting_future_segment_cannot_claim_active_time() -> None:
    payload = json.loads(encode_result(challenge_result(failed=True)))
    payload["data"]["state"] = "aborted"
    summary = payload["data"]["challenge"]
    summary["score"] = summary["max_chain"] = 0
    for segment in summary["segments"]:
        segment["verdict"] = "pending"
        segment["auto_repaired"] = False
        segment["elapsed_seconds"] = 1
    with pytest.raises(ValueError, match="활성화되지 않은"):
        decode_result(json.dumps(payload))


@pytest.mark.parametrize("nested", ["options", "segments"])
def test_unknown_nested_challenge_fields_are_rejected(nested: str) -> None:
    payload = json.loads(encode_result(challenge_result()))
    record = payload["data"]["challenge"][nested]
    if isinstance(record, list):
        record = record[0]
    record["unknown_rule"] = 1
    with pytest.raises(ValueError, match="알 수 없는 필드"):
        decode_result(json.dumps(payload))


def test_saved_partial_failure_retry_cannot_create_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = SqliteResultRepository(tmp_path / "retry.sqlite3")
    write_result = repository._write_result

    def fail(_result: object) -> None:
        raise sqlite3.OperationalError("temporary disk failure")

    monkeypatch.setattr(repository, "_write_result", fail)
    result = challenge_result(failed=True)
    assert not repository.save(result)
    assert repository.pending_count == 1
    assert repository.completed_count == 0
    monkeypatch.setattr(repository, "_write_result", write_result)
    assert repository.retry_pending() == 1
    assert repository.retry_pending() == 0
    assert repository.completed_count == 0
    assert repository.best_for(result) is None
    repository.close()


def test_recorded_revenge_rebuilds_failed_only_without_original_memory() -> None:
    clock = [0]
    lesson = create_boss_problem(23, objectives=("all_direct",))
    original = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: clock[0]
    )
    first = lesson.segments[0]
    for step in lesson.guide[first.start_step : first.end_step]:
        for key in step.keys:
            assert original.submit(key) == InputResult.ACCEPTED
    clock[0] += 100_000_000_000
    original.check_deadline()
    while original.state != SessionState.COMPLETED:
        assert original.submit(original.expected_token) == InputResult.ACCEPTED
    result = original.result
    assert result is not None and result.challenge is not None
    saved = decode_result(encode_result(result))
    original.release_transient()
    del original
    revenge = create_recorded_revenge(saved, clock_ns=lambda: clock[0])
    assert revenge.attempt_id != result.attempt_id
    assert revenge.lesson.signature == result.lesson_signature
    assert len(revenge.segments) == 1
    assert revenge.revenge_segments == (lesson.segments[1].id,)
    assert revenge.engine.state.lines == lesson.guide[first.end_step - 1].expected.lines
    while revenge.state != SessionState.COMPLETED:
        assert revenge.submit(revenge.expected_token) == InputResult.ACCEPTED
    assert revenge.result is not None and revenge.result.stars == 0
    assert revenge.result.challenge is not None and revenge.result.challenge.full_clear
    assert saved == result


def test_recorded_revenge_rejects_altered_problem_signature() -> None:
    clock = [0]
    session = EditingSession(
        create_boss_problem(23),
        challenge=ChallengeOptions("bomb"),
        clock_ns=lambda: clock[0],
    )
    session.submit(KeyToken("char", "Q"))
    clock[0] += 100_000_000_000
    session.check_deadline()
    session.abort()
    assert session.result is not None
    tampered = replace(session.result, lesson_signature="0" * 64)
    with pytest.raises(ValueError, match="문제 서명"):
        create_recorded_revenge(tampered)


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
