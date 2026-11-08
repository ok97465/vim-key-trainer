"""폭탄 결과의 부분 실패·복수전·중복 저장은 완료 보상과 분리한다."""

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
from vim_key_trainer.domain.game_rules import bomb_score, bomb_segment_score
from vim_key_trainer.domain.sessions import EditingSessionResult, SessionState
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
