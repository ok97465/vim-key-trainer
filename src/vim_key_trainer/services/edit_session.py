"""엔진·가이드·제한시간을 연결하는 Qt 독립 편집 연습 세션."""

from __future__ import annotations

# Standard library imports
from collections.abc import Callable
from dataclasses import replace
from time import perf_counter_ns
from uuid import uuid4

# Local imports
from vim_key_trainer.domain.activities import evaluate_objectives
from vim_key_trainer.domain.challenge import (
    TIME_RULES,
    ChallengeOptions,
    ChallengeSummary,
    FailureExample,
    RecoveryMark,
    SegmentResult,
    SuccessMark,
    TimerGuard,
    bomb_unavailable_reason,
    challenge_segments,
)
from vim_key_trainer.domain.editing import (
    EditLesson,
    EditMode,
    EditSegment,
    GuideStep,
    expected_states_match,
    goal_matches,
)
from vim_key_trainer.domain.game_rules import bomb_score, editing_stars, typing_stars
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.engine import EditEngine, EditorSnapshot

_NANOSECONDS = 1_000_000_000
_DEFAULT_CHALLENGE = ChallengeOptions()


class EditingSession:
    def __init__(
        self,
        lesson: EditLesson,
        mode: EditMode = "guided",
        *,
        clock_ns: Callable[[], int] = perf_counter_ns,
        challenge: ChallengeOptions = _DEFAULT_CHALLENGE,
        revenge_segments: tuple[str, ...] = (),
    ) -> None:
        if mode not in {"guided", "free"}:
            raise ValueError("지원하지 않는 풀이 방식입니다.")
        if mode == "free" and not lesson.free_enabled:
            raise ValueError("이 과제는 가이드 풀이만 지원합니다.")
        if not lesson.guide:
            raise ValueError("편집 과제에는 가이드가 필요합니다.")
        if not isinstance(challenge, ChallengeOptions):
            raise ValueError("도전 조건의 형식이 올바르지 않습니다.")
        if challenge.kind == "bomb" and (
            reason := bomb_unavailable_reason(lesson, mode)
        ):
            raise ValueError(reason)
        if revenge_segments and (challenge.kind != "bomb" or mode != "guided"):
            raise ValueError("실패 구간 복수전은 가이드 폭탄 도전에서만 가능합니다.")
        self.lesson = lesson
        self.lesson_signature = lesson.signature
        self.mode = mode
        self.challenge = challenge
        self.revenge_segments = revenge_segments
        self.engine = EditEngine(lesson.initial, lesson.allowed_commands)
        self.attempt_id = str(uuid4())
        self.state = SessionState.READY
        self.key_count = 0
        self.step_index = 0
        self.token_index = 0
        self.extra_hints = 0
        self.step_returns = 0
        self.pause_count = 0
        self.message = "첫 키를 입력하면 시간 측정을 시작합니다."
        self.result: EditingSessionResult | None = None
        self._correct = 0
        self._incorrect = 0
        self._combo = 0
        self._max_combo = 0
        self._clock_ns = clock_ns
        self._accumulated_ns = 0
        self._running_since_ns: int | None = None
        self._paused_from_ready = False
        self._step_snapshots: dict[int, EditorSnapshot] = {0: self.engine.snapshot()}
        self._prepared_steps: dict[int, EditorSnapshot] = {}
        self._generation = 0
        self._active_started_elapsed_ns: int | None = None
        self._segment_results: list[SegmentResult] = []
        self._active_segment_index: int | None = None
        self._recovery_marks: list[RecoveryMark] = []
        self._success_marks: list[SuccessMark] = []
        self._failure_examples: list[FailureExample] = []
        self.recovery_error: str | None = None
        self.chain = 0
        self.max_chain = 0
        self.segments: tuple[EditSegment, ...] = ()
        if self.bomb_enabled:
            self._prepare_challenge()

    @property
    def bomb_enabled(self) -> bool:
        return self.challenge.kind == "bomb"

    def _prepare_challenge(self) -> None:
        """준비 중 한 번 재생해 복구·복수전의 선행 상태를 검증하고 캐시한다."""
        all_segments = challenge_segments(self.lesson, self.mode)
        covered = 0
        seen: set[str] = set()
        for segment in all_segments:
            if (
                segment.id in seen
                or segment.start_step != covered
                or segment.end_step > len(self.lesson.guide)
                or not set(segment.prerequisite_ids).issubset(seen)
            ):
                raise ValueError("수정 구간의 범위·순서·선행 조건이 올바르지 않습니다.")
            seen.add(segment.id)
            covered = segment.end_step
        if covered != len(self.lesson.guide):
            raise ValueError("수정 구간이 전체 가이드를 포함하지 않습니다.")
        if self.revenge_segments and (
            len(set(self.revenge_segments)) != len(self.revenge_segments)
            or not set(self.revenge_segments).issubset(seen)
        ):
            raise ValueError("복수전 구간이 원래 문제에 없습니다.")
        probe = EditEngine(self.lesson.initial, self.lesson.allowed_commands)
        self._prepared_steps[0] = probe.snapshot()
        step_search_counts: list[int] = []
        for index, step in enumerate(self.lesson.guide):
            search_count = 0
            for key in step.keys:
                previous_prompt = probe.state.command_line
                if not probe.submit(key).accepted:
                    raise ValueError("폭탄 도전의 기준 입력을 재생할 수 없습니다.")
                if not previous_prompt and probe.state.command_line in {"/", "?"}:
                    search_count += 1
            if not expected_states_match(step.expected, probe.state):
                raise ValueError("폭탄 도전의 가이드 기대 상태가 다릅니다.")
            self._prepared_steps[index + 1] = probe.snapshot()
            step_search_counts.append(search_count)
        if not goal_matches(self.lesson, probe.state):
            raise ValueError("폭탄 도전의 기준 풀이가 목표 문서와 다릅니다.")
        self.segments = tuple(
            segment
            for segment in all_segments
            if not self.revenge_segments or segment.id in self.revenge_segments
        )
        for segment in self.segments:
            start = self._prepared_steps[segment.start_step].state
            end = self._prepared_steps[segment.end_step].state
            if end.mode != "normal" or end.pending or end.command_line:
                raise ValueError("폭탄 구간은 Normal·대기 없음 상태로 끝나야 합니다.")
            if start.lines == end.lines:
                raise ValueError(
                    "문서를 바꾸지 않는 구간은 폭탄 대상으로 삼을 수 없습니다."
                )
            steps = self.lesson.guide[segment.start_step : segment.end_step]
            limit = TIME_RULES.limit_seconds(
                key_count=sum(len(step.keys) for step in steps),
                row_distance=abs(segment.target_start_row - start.row),
                search_count=sum(
                    step_search_counts[segment.start_step : segment.end_step]
                ),
                difficulty=self.challenge.difficulty,
                whole_document=self.mode == "free",
            )
            self._segment_results.append(SegmentResult(segment.id, "pending", 0, limit))
        self._active_segment_index = 0
        if self.revenge_segments:
            first = self.segments[0]
            initial = self._history_barrier(self._prepared_steps[first.start_step])
            self.engine.restore(initial)
            self.step_index = first.start_step
            self._step_snapshots = {first.start_step: initial}

    @staticmethod
    def _history_barrier(snapshot: EditorSnapshot) -> EditorSnapshot:
        # 시스템 복구는 사용자 undo 항목이 아니다. 대기·레지스터·찾기·반복은 유지한다.
        return replace(snapshot, undo=(), redo=())

    @property
    def current_step(self) -> GuideStep | None:
        return (
            self.lesson.guide[self.step_index]
            if self.step_index < len(self.lesson.guide)
            else None
        )

    @property
    def expected_token(self) -> KeyToken | None:
        step = self.current_step
        return step.keys[self.token_index] if step is not None else None

    @property
    def guide_level(self) -> str:
        return "step" if self.mode == "guided" else "none"

    @property
    def baseline_keys(self) -> int:
        if self.revenge_segments:
            return sum(
                len(step.keys)
                for segment in self.segments
                for step in self.lesson.guide[segment.start_step : segment.end_step]
            )
        return self.lesson.baseline_keys

    @property
    def delta(self) -> int:
        return self.key_count - self.baseline_keys

    @property
    def correct(self) -> int | None:
        return self._correct if self.mode == "guided" else None

    @property
    def incorrect(self) -> int | None:
        return self._incorrect if self.mode == "guided" else None

    @property
    def combo(self) -> int | None:
        return self._combo if self.mode == "guided" else None

    @property
    def max_combo(self) -> int | None:
        return self._max_combo if self.mode == "guided" else None

    @property
    def accuracy(self) -> float | None:
        total = self._correct + self._incorrect
        return 100 * self._correct / total if self.mode == "guided" and total else None

    def _elapsed_ns(self, now_ns: int) -> int:
        running = (
            max(0, now_ns - self._running_since_ns)
            if self._running_since_ns is not None
            else 0
        )
        return self._accumulated_ns + running

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed_ns(self._clock_ns()) / _NANOSECONDS

    @property
    def active_segment_index(self) -> int | None:
        return self._active_segment_index

    @property
    def current_segment(self) -> EditSegment | None:
        index = self._active_segment_index
        return self.segments[index] if index is not None else None

    @property
    def timer_guard(self) -> TimerGuard | None:
        segment = self.current_segment
        return (
            TimerGuard(self.attempt_id, segment.id, self._generation)
            if segment
            else None
        )

    def _segment_elapsed_ns(self, now_ns: int) -> int:
        if self._active_started_elapsed_ns is None:
            return 0
        return max(0, self._elapsed_ns(now_ns) - self._active_started_elapsed_ns)

    @property
    def segment_limit_seconds(self) -> float | None:
        index = self._active_segment_index
        return self._segment_results[index].limit_seconds if index is not None else None

    @property
    def remaining_seconds(self) -> float | None:
        index = self._active_segment_index
        if index is None or self._segment_results[index].verdict != "pending":
            return None
        return max(
            0,
            self._segment_results[index].limit_seconds
            - self._segment_elapsed_ns(self._clock_ns()) / _NANOSECONDS,
        )

    @property
    def segment_results(self) -> tuple[SegmentResult, ...]:
        return tuple(self._segment_results)

    @property
    def direct_count(self) -> int:
        return sum(segment.verdict == "direct" for segment in self._segment_results)

    @property
    def timeout_count(self) -> int:
        return sum(segment.verdict == "timeout" for segment in self._segment_results)

    @property
    def auto_repair_count(self) -> int:
        return sum(segment.auto_repaired for segment in self._segment_results)

    @property
    def recovery_marks(self) -> tuple[RecoveryMark, ...]:
        return tuple(self._recovery_marks)

    @property
    def success_marks(self) -> tuple[SuccessMark, ...]:
        return tuple(self._success_marks)

    @property
    def failure_examples(self) -> tuple[FailureExample, ...]:
        return tuple(self._failure_examples)

    def release_transient(self) -> None:
        """현재 결과 화면을 떠나면 실패 당시 문서의 메모리 참조를 해제한다."""
        self._failure_examples.clear()

    def _remap_recovery_marks(
        self, before: tuple[str, ...], after: tuple[str, ...]
    ) -> None:
        """행 삽입/삭제 때 여백 표식도 해당 문서 위치를 따라가게 한다."""
        if len(before) == len(after) or not (
            self._recovery_marks or self._success_marks
        ):
            return
        prefix = 0
        while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
            prefix += 1
        suffix = 0
        while (
            suffix < min(len(before), len(after)) - prefix
            and before[len(before) - suffix - 1] == after[len(after) - suffix - 1]
        ):
            suffix += 1
        before_end = len(before) - suffix
        after_end = len(after) - suffix
        delta = len(after) - len(before)

        def mapped_row(original: int) -> int:
            if original < prefix:
                row = original
            elif original >= before_end:
                row = original + delta
            else:
                row = prefix + min(original - prefix, max(0, after_end - prefix - 1))
            return min(len(after) - 1, max(0, row))

        self._recovery_marks = [
            replace(mark, row=mapped_row(mark.row)) for mark in self._recovery_marks
        ]
        self._success_marks = [
            replace(mark, row=mapped_row(mark.row)) for mark in self._success_marks
        ]

    def _expired_at(self, now_ns: int) -> bool:
        index = self._active_segment_index
        return bool(
            self.state == SessionState.RUNNING
            and index is not None
            and self._segment_results[index].verdict == "pending"
            and self._active_started_elapsed_ns is not None
            and self._segment_elapsed_ns(now_ns)
            >= round(self._segment_results[index].limit_seconds * _NANOSECONDS)
        )

    def check_deadline(self, guard: TimerGuard | None = None) -> bool:
        """타이머는 이 메서드만 호출한다. 지난 시도·구간·세대의 요청은 무시한다."""
        if guard is not None and guard != self.timer_guard:
            return False
        return self._check_deadline_at(self._clock_ns())

    def _check_deadline_at(self, now_ns: int) -> bool:
        if not self._expired_at(now_ns):
            return False
        index = self._active_segment_index
        assert index is not None
        segment = self.segments[index]
        result = self._segment_results[index]
        self._segment_results[index] = replace(
            result, verdict="timeout", elapsed_seconds=result.limit_seconds
        )
        self.chain = 0
        self._generation += 1
        self._failure_examples.append(
            FailureExample(
                segment.id,
                self.engine.state.lines,
                self._prepared_steps[segment.end_step].state.lines,
                tuple(
                    key
                    for step in self.lesson.guide[segment.start_step : segment.end_step]
                    for key in step.keys
                ),
            )
        )
        self.message = (
            "시간 초과 · 이 구간을 직접 마무리해 보세요. 실패 판정은 유지됩니다."
        )
        if self.challenge.auto_repair and self.mode == "guided":
            self._recover_segment(segment, index, now_ns)
        return True

    def _recover_segment(self, segment: EditSegment, index: int, now_ns: int) -> None:
        before = self.engine.snapshot()
        self._stop_clock(now_ns)
        try:
            snapshot = self._history_barrier(self._prepared_steps[segment.end_step])
            snapshot = replace(
                snapshot,
                state=replace(snapshot.state, viewport_rows=before.state.viewport_rows),
            )
            probe = EditEngine(self.lesson.initial, self.lesson.allowed_commands)
            probe.restore(snapshot)
            if not expected_states_match(
                self.lesson.guide[segment.end_step - 1].expected, probe.state
            ):
                raise ValueError("자동 복구 종료 상태가 검증된 가이드와 다릅니다.")
            self.engine.restore(probe.snapshot())
        except (ValueError, TypeError, AttributeError, KeyError, RuntimeError) as error:
            self.engine.restore(before)
            self.recovery_error = str(error)
            self.state = SessionState.PAUSED
            self.pause_count += 1
            self.message = (
                "자동 복구를 검증하지 못해 일시정지했습니다. "
                f"같은 문제를 다시 시작하세요: {error}"
            )
            return
        self._remap_recovery_marks(before.state.lines, self.engine.state.lines)
        self._segment_results[index] = replace(
            self._segment_results[index], auto_repaired=True
        )
        self.step_index = segment.end_step
        self.token_index = 0
        for step in range(segment.start_step, segment.end_step):
            self._step_snapshots[step] = self._prepared_steps[step]
        self._step_snapshots[segment.end_step] = self.engine.snapshot()
        self._recovery_marks.append(
            RecoveryMark(
                segment.id,
                min(segment.target_start_row, len(self.engine.state.lines) - 1),
            )
        )
        activated_at = self._clock_ns()
        self._running_since_ns = activated_at
        self._advance_segment(activated_at)
        self.message = "시간 초과 · 자동 복구했습니다. 다음 구간에 도전하세요."
        self._maybe_complete(activated_at)

    def _advance_segment(self, now_ns: int) -> None:
        index = self._active_segment_index
        assert index is not None
        self._generation += 1
        if index + 1 == len(self.segments):
            self._active_segment_index = None
            self._active_started_elapsed_ns = None
            return
        self._active_segment_index = index + 1
        next_segment = self.segments[index + 1]
        if self.revenge_segments and self.step_index != next_segment.start_step:
            self._stop_clock(now_ns)
            snapshot = self._history_barrier(
                self._prepared_steps[next_segment.start_step]
            )
            snapshot = replace(
                snapshot,
                state=replace(
                    snapshot.state, viewport_rows=self.engine.state.viewport_rows
                ),
            )
            previous_lines = self.engine.state.lines
            self.engine.restore(snapshot)
            self._remap_recovery_marks(previous_lines, self.engine.state.lines)
            self.step_index = next_segment.start_step
            self.token_index = 0
            self._step_snapshots[self.step_index] = snapshot
            now_ns = self._clock_ns()
            self._running_since_ns = now_ns
        self._active_started_elapsed_ns = self._elapsed_ns(now_ns)

    def _finish_segment(self, now_ns: int) -> None:
        index = self._active_segment_index
        if index is None:
            return
        segment = self.segments[index]
        if self.mode == "guided" and self.step_index < segment.end_step:
            return
        if self.mode == "free" and not goal_matches(self.lesson, self.engine.state):
            return
        result = self._segment_results[index]
        if result.verdict == "pending":
            self._segment_results[index] = replace(
                result,
                verdict="direct",
                elapsed_seconds=self._segment_elapsed_ns(now_ns) / _NANOSECONDS,
            )
            self._success_marks.append(
                SuccessMark(
                    segment.id,
                    min(segment.target_start_row, len(self.engine.state.lines) - 1),
                )
            )
            self.chain += 1
            self.max_chain = max(self.max_chain, self.chain)
        self._advance_segment(self._clock_ns())

    def submit(self, token: KeyToken | None) -> InputResult:
        if token is None or self.state not in {
            SessionState.READY,
            SessionState.RUNNING,
        }:
            return InputResult.IGNORED
        now_ns = self._clock_ns()
        if self.state == SessionState.READY:
            self.state = SessionState.RUNNING
            self._running_since_ns = now_ns
            if self.bomb_enabled:
                self._active_started_elapsed_ns = 0
        self.key_count += 1
        if self._expired_at(now_ns):
            if self.mode == "guided":
                self._incorrect += 1
                self._combo = 0
            self._check_deadline_at(now_ns)
            return InputResult.REJECTED
        if self.mode == "guided":
            outcome = self._submit_guided(token)
        else:
            edit = self.engine.submit(token)
            self.message = edit.message
            outcome = InputResult.ACCEPTED if edit.accepted else InputResult.REJECTED
        if self.bomb_enabled:
            self._finish_segment(now_ns)
        self._maybe_complete(now_ns)
        return outcome

    def _maybe_complete(self, now_ns: int) -> None:
        guide_done = self.mode == "free" or self.step_index == len(self.lesson.guide)
        finished = guide_done and goal_matches(self.lesson, self.engine.state)
        if self.revenge_segments:
            finished = self._active_segment_index is None
        if finished:
            self._stop_clock(now_ns)
            self.state = SessionState.COMPLETED
            self._generation += 1
            self.message = (
                "목표 문서를 완성했습니다."
                if not self.timeout_count
                else "연습을 마쳤습니다. 놓친 구간은 복수전으로 다시 도전하세요."
            )
            self.result = self._make_result(now_ns)

    def _submit_guided(self, token: KeyToken) -> InputResult:
        step = self.current_step
        if step is None or token != self.expected_token:
            self._incorrect += 1
            self._combo = 0
            expected = self.expected_token
            self.message = (
                f"다음 키는 {expected.display}입니다. 오타는 문서에 적용하지 않습니다."
                if expected is not None
                else "가이드 입력을 모두 마쳤습니다."
            )
            return InputResult.REJECTED
        snapshot = self.engine.snapshot()
        edit = self.engine.submit(token)
        last_key = self.token_index + 1 == len(step.keys)
        if not edit.accepted or (
            last_key and not expected_states_match(step.expected, self.engine.state)
        ):
            self.engine.restore(snapshot)
            self._incorrect += 1
            self._combo = 0
            self.message = edit.message or "가이드 기대 상태가 일치하지 않습니다."
            return InputResult.REJECTED
        self._remap_recovery_marks(snapshot.state.lines, self.engine.state.lines)
        self._correct += 1
        self._combo += 1
        self._max_combo = max(self._max_combo, self._combo)
        self.message = edit.message
        self.token_index += 1
        if last_key:
            self.step_index += 1
            self.token_index = 0
            self._step_snapshots[self.step_index] = self.engine.snapshot()
        return InputResult.ACCEPTED

    def return_to_step(self, step_index: int | None = None) -> bool:
        """가이드 위치만 복원한다. 폭탄의 현재 구간·남은 시간·최초 판정은 유지한다."""
        if self.mode != "guided" or self.state not in {
            SessionState.READY,
            SessionState.RUNNING,
            SessionState.PAUSED,
        }:
            return False
        if self._check_deadline_at(self._clock_ns()):
            return False
        if step_index is None:
            step_index = max(
                0, self.step_index if self.token_index else self.step_index - 1
            )
        if step_index < 0 or step_index > self.step_index:
            return False
        snapshot = self._step_snapshots.get(step_index)
        if snapshot is None:
            return False
        previous_lines = self.engine.state.lines
        self.engine.restore(snapshot)
        self._remap_recovery_marks(previous_lines, self.engine.state.lines)
        self.step_index = step_index
        self.token_index = 0
        if not self.bomb_enabled:
            self._step_snapshots = {
                index: state
                for index, state in self._step_snapshots.items()
                if index <= step_index
            }
        self.step_returns += 1
        self._combo = 0
        self._generation += 1
        self.message = (
            "단계 처음으로 돌아왔습니다. 누적 입력 수·시간·폭탄 판정은 유지합니다."
        )
        return True

    def reveal_hint(self) -> None:
        if self.mode == "free" and self.state in {
            SessionState.READY,
            SessionState.RUNNING,
            SessionState.PAUSED,
        }:
            self._check_deadline_at(self._clock_ns())
            self.extra_hints += 1

    def _stop_clock(self, now_ns: int) -> None:
        self._accumulated_ns = self._elapsed_ns(now_ns)
        self._running_since_ns = None

    def pause(self) -> None:
        if self.state not in {SessionState.READY, SessionState.RUNNING}:
            return
        now_ns = self._clock_ns()
        self._check_deadline_at(now_ns)
        if self.state not in {SessionState.READY, SessionState.RUNNING}:
            return
        self._paused_from_ready = self.state == SessionState.READY
        if not self._paused_from_ready:
            self._stop_clock(now_ns)
        self.state = SessionState.PAUSED
        self.pause_count += 1
        self._generation += 1

    def resume(self) -> None:
        if self.state != SessionState.PAUSED or self.recovery_error is not None:
            return
        if self._paused_from_ready:
            self.state = SessionState.READY
        else:
            self._running_since_ns = self._clock_ns()
            self.state = SessionState.RUNNING
        self._generation += 1

    def abort(self) -> None:
        if self.state in {SessionState.COMPLETED, SessionState.ABORTED}:
            return
        now_ns = self._clock_ns()
        self._check_deadline_at(now_ns)
        if self.state == SessionState.COMPLETED:
            return
        self._stop_clock(now_ns)
        self.state = SessionState.ABORTED
        self._generation += 1
        self.result = self._make_result(now_ns)

    def retry(self) -> EditingSession:
        return EditingSession(
            self.lesson,
            self.mode,
            clock_ns=self._clock_ns,
            challenge=self.challenge,
            revenge_segments=self.revenge_segments,
        )

    def create_revenge(self) -> EditingSession:
        if self.mode != "guided" or self.result is None or not self.timeout_count:
            raise ValueError("완료한 가이드 폭탄 도전에 실패 구간이 있어야 합니다.")
        failed = tuple(
            result.segment_id
            for result in self._segment_results
            if result.verdict == "timeout"
        )
        return EditingSession(
            self.lesson,
            self.mode,
            clock_ns=self._clock_ns,
            challenge=self.challenge,
            revenge_segments=failed,
        )

    def _make_result(self, now_ns: int) -> EditingSessionResult:
        completed = self.state == SessionState.COMPLETED
        summary: ChallengeSummary | None = None
        if self.bomb_enabled:
            segments = list(self._segment_results)
            index = self._active_segment_index
            if index is not None and segments[index].verdict == "pending":
                segments[index] = replace(
                    segments[index],
                    elapsed_seconds=self._segment_elapsed_ns(now_ns) / _NANOSECONDS,
                )
            summary = ChallengeSummary(
                options=self.challenge,
                time_rule_version=TIME_RULES.version,
                segments=tuple(segments),
                full_clear=completed
                and all(segment.verdict == "direct" for segment in segments),
                score=bomb_score(
                    segments=segments,
                    extra_hints=self.extra_hints,
                    step_returns=self.step_returns,
                ),
                max_chain=self.max_chain,
                revenge_of=self.lesson_signature if self.revenge_segments else None,
            )
        eligible = completed and (
            summary is None or (summary.full_clear and summary.revenge_of is None)
        )
        if self.mode == "guided":
            stars = typing_stars(
                completed=eligible,
                correct=self._correct,
                incorrect=self._incorrect,
                extra_hints=self.extra_hints,
                step_returns=self.step_returns,
            )
        else:
            stars = editing_stars(
                completed=eligible,
                key_count=self.key_count,
                baseline_keys=self.baseline_keys,
                extra_hints=self.extra_hints,
                step_returns=self.step_returns,
            )
        return EditingSessionResult(
            attempt_id=self.attempt_id,
            lesson_id=self.lesson.id,
            lesson_signature=self.lesson_signature,
            mode=self.mode,
            state=self.state,
            key_count=self.key_count,
            baseline_keys=self.baseline_keys,
            elapsed_seconds=self._elapsed_ns(now_ns) / _NANOSECONDS,
            correct=self.correct,
            incorrect=self.incorrect,
            accuracy=self.accuracy,
            max_combo=self.max_combo,
            stars=stars,
            extra_hints=self.extra_hints,
            step_returns=self.step_returns,
            pause_count=self.pause_count,
            guide_level=self.guide_level,
            practice_spec=self.lesson.practice_spec,
            document_spec=self.lesson.document_spec,
            code_source_id=(
                self.lesson.code_excerpt.source.id
                if self.lesson.code_excerpt is not None
                else None
            ),
            challenge=summary,
            activity=self.lesson.activity,
            bonus_objectives=evaluate_objectives(
                self.lesson.activity.objectives
                if self.lesson.activity is not None
                else (),
                eligible=eligible,
                extra_hints=self.extra_hints,
                key_count=self.key_count,
                baseline_keys=self.baseline_keys,
                efficiency_eligible=summary is None or summary.auto_repair_count == 0,
                all_direct=summary is not None and summary.full_clear,
            ),
        )
