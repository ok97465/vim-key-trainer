"""같은 조건의 전체 클리어 요약 시간으로만 개인 기록과 나란히 진행한다."""

# Standard library imports
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import accumulate

# Local imports
from vim_key_trainer.domain.challenge import TIME_RULE_VERSION, ChallengeSummary
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    SessionState,
    StoredResult,
)
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_comparison import (
    comparison_key,
    is_better_result,
    record_eligible,
)


@dataclass(frozen=True, slots=True)
class RivalProgress:
    completed_segments: int
    total_segments: int
    reference_completed_segments: int
    reference_progress: float
    checkpoint_seconds: float
    reference_checkpoint_seconds: float
    delta_seconds: float | None
    eligible: bool


def _comparison_probe(session: EditingSession) -> EditingSessionResult:
    """저장하지 않는 비교 조건 투영. 결과 비교 계약을 그대로 재사용한다."""
    return EditingSessionResult(
        attempt_id=session.attempt_id,
        lesson_id=session.lesson.id,
        lesson_signature=session.lesson_signature,
        mode=session.mode,
        state=SessionState.READY,
        key_count=0,
        baseline_keys=session.baseline_keys,
        elapsed_seconds=0,
        correct=0 if session.mode == "guided" else None,
        incorrect=0 if session.mode == "guided" else None,
        accuracy=None,
        max_combo=0 if session.mode == "guided" else None,
        stars=0,
        extra_hints=session.extra_hints,
        step_returns=session.step_returns,
        pause_count=session.pause_count,
        guide_level=session.guide_level,
        practice_spec=session.lesson.practice_spec,
        document_spec=session.lesson.document_spec,
        activity=session.lesson.activity,
        challenge=ChallengeSummary(
            options=session.challenge,
            time_rule_version=TIME_RULE_VERSION,
            segments=session.segment_results,
            full_clear=False,
            score=0,
            revenge_of=session.lesson_signature if session.revenge_segments else None,
        ),
    )


@dataclass(frozen=True, slots=True)
class ChallengeRival:
    reference: EditingSessionResult
    cumulative_seconds: tuple[float, ...]

    def progress(self, session: EditingSession) -> RivalProgress | None:
        """정산한 구간의 시간 차이와 같은 경과 시간의 과거 진도를 반환한다."""
        reference = self.reference
        challenge = reference.challenge
        assert challenge is not None
        # 불변 문제 조건은 준비 때 계산한 서명으로, 진행 중 바뀌는 도움 조건은
        # 직접 비교한다. 화면 타이머마다 전체 결과·도전 요약을 만들지 않는다.
        if (
            session.lesson.id != reference.lesson_id
            or session.lesson_signature != reference.lesson_signature
            or session.mode != reference.mode
            or session.challenge != challenge.options
            or session.revenge_segments
            or session.extra_hints != reference.extra_hints
            or session.step_returns != reference.step_returns
            or (session.pause_count > 0) != (reference.pause_count > 0)
        ):
            return None
        settled = tuple(
            segment
            for segment in session.segment_results
            if segment.verdict != "pending"
        )
        completed = len(settled)
        checkpoint = sum(segment.elapsed_seconds for segment in settled)
        reference_checkpoint = (
            self.cumulative_seconds[completed - 1] if completed else 0.0
        )
        elapsed = session.elapsed_seconds
        reference_completed = bisect_right(self.cumulative_seconds, elapsed)
        count = len(self.cumulative_seconds)
        reference_progress = float(reference_completed)
        if reference_completed < count:
            start = (
                self.cumulative_seconds[reference_completed - 1]
                if reference_completed
                else 0
            )
            duration = self.cumulative_seconds[reference_completed] - start
            if duration > 0:
                reference_progress += max(0.0, min(1.0, (elapsed - start) / duration))
        return RivalProgress(
            completed_segments=completed,
            total_segments=count,
            reference_completed_segments=reference_completed,
            reference_progress=reference_progress / count,
            checkpoint_seconds=checkpoint,
            reference_checkpoint_seconds=reference_checkpoint,
            delta_seconds=checkpoint - reference_checkpoint if completed else None,
            eligible=session.timeout_count == 0,
        )


def rival_for_session(
    session: EditingSession, results: Iterable[StoredResult]
) -> ChallengeRival | None:
    """검증된 기록에서 같은 조건의 최고 전체 클리어를 고른다."""
    if not session.bomb_enabled or session.revenge_segments:
        return None
    conditions = comparison_key(_comparison_probe(session))
    best: EditingSessionResult | None = None
    for result in results:
        if (
            not isinstance(result, EditingSessionResult)
            or result.challenge is None
            or result.attempt_id == session.attempt_id
            or not record_eligible(result)
            or result.elapsed_seconds <= 0
            or not any(
                segment.elapsed_seconds > 0 for segment in result.challenge.segments
            )
            or comparison_key(result) != conditions
        ):
            continue
        if best is None or is_better_result(result, best):
            best = result
    if best is None or best.challenge is None:
        return None
    return ChallengeRival(
        reference=best,
        cumulative_seconds=tuple(
            accumulate(segment.elapsed_seconds for segment in best.challenge.segments)
        ),
    )
