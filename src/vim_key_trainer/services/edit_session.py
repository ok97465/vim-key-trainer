"""엔진과 콘텐츠를 연결하는 Qt 독립 편집 연습 세션."""

# Standard library imports
from collections.abc import Callable
from time import perf_counter_ns
from uuid import uuid4

# Local imports
from vim_key_trainer.domain.editing import (
    EditLesson,
    EditMode,
    GuideStep,
    expected_states_match,
    goal_matches,
)
from vim_key_trainer.domain.game_rules import editing_stars, typing_stars
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    EditingSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.engine import EditEngine, EditorSnapshot


class EditingSession:
    def __init__(
        self,
        lesson: EditLesson,
        mode: EditMode = "guided",
        *,
        clock_ns: Callable[[], int] = perf_counter_ns,
    ) -> None:
        if mode not in {"guided", "free"}:
            raise ValueError("지원하지 않는 풀이 방식입니다.")
        if mode == "free" and not lesson.free_enabled:
            raise ValueError("이 과제는 가이드 풀이만 지원합니다.")
        if not lesson.guide:
            raise ValueError("편집 과제에는 가이드가 필요합니다.")
        self.lesson = lesson
        self.mode = mode
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

    @property
    def current_step(self) -> GuideStep | None:
        if self.step_index >= len(self.lesson.guide):
            return None
        return self.lesson.guide[self.step_index]

    @property
    def expected_token(self) -> KeyToken | None:
        step = self.current_step
        return step.keys[self.token_index] if step is not None else None

    @property
    def guide_level(self) -> str:
        return "step" if self.mode == "guided" else "none"

    @property
    def baseline_keys(self) -> int:
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
        if self.mode == "free" or not total:
            return None
        return 100 * self._correct / total

    def _elapsed_ns(self, now_ns: int) -> int:
        running = (
            now_ns - self._running_since_ns if self._running_since_ns is not None else 0
        )
        return self._accumulated_ns + running

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed_ns(self._clock_ns()) / 1_000_000_000

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
        self.key_count += 1

        if self.mode == "guided":
            outcome = self._submit_guided(token)
        else:
            edit = self.engine.submit(token)
            self.message = edit.message
            outcome = InputResult.ACCEPTED if edit.accepted else InputResult.REJECTED

        guide_done = self.mode == "free" or self.step_index == len(self.lesson.guide)
        if guide_done and goal_matches(self.lesson, self.engine.state):
            self._stop_clock(now_ns)
            self.state = SessionState.COMPLETED
            self.message = "목표 문서를 완성했습니다."
            self.result = self._make_result()
        return outcome

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
            # 로더가 이미 검증하지만, 잘못 구성한 직접 입력도 완료로 처리하지 않는다.
            self.engine.restore(snapshot)
            self._incorrect += 1
            self._combo = 0
            self.message = edit.message or "가이드 기대 상태가 일치하지 않습니다."
            return InputResult.REJECTED

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
        """부분 입력은 현재 단계 처음으로, 단계 시작점에서는 앞 단계로 복귀한다."""
        if self.mode != "guided" or self.state not in {
            SessionState.READY,
            SessionState.RUNNING,
            SessionState.PAUSED,
        }:
            return False
        if step_index is None:
            step_index = self.step_index if self.token_index else self.step_index - 1
            step_index = max(0, step_index)
        if step_index < 0 or step_index > self.step_index:
            return False
        snapshot = self._step_snapshots.get(step_index)
        if snapshot is None:
            return False
        self.engine.restore(snapshot)
        self.step_index = step_index
        self.token_index = 0
        self._step_snapshots = {
            index: state
            for index, state in self._step_snapshots.items()
            if index <= step_index
        }
        self.step_returns += 1
        self._combo = 0
        self.message = "단계 처음으로 돌아왔습니다. 누적 입력 수와 시간은 유지합니다."
        return True

    def reveal_hint(self) -> None:
        if self.mode == "free" and self.state in {
            SessionState.READY,
            SessionState.RUNNING,
            SessionState.PAUSED,
        }:
            self.extra_hints += 1

    def _stop_clock(self, now_ns: int) -> None:
        self._accumulated_ns = self._elapsed_ns(now_ns)
        self._running_since_ns = None

    def pause(self) -> None:
        if self.state not in {SessionState.READY, SessionState.RUNNING}:
            return
        self._paused_from_ready = self.state == SessionState.READY
        if not self._paused_from_ready:
            self._stop_clock(self._clock_ns())
        self.state = SessionState.PAUSED
        self.pause_count += 1

    def resume(self) -> None:
        if self.state != SessionState.PAUSED:
            return
        if self._paused_from_ready:
            self.state = SessionState.READY
        else:
            self._running_since_ns = self._clock_ns()
            self.state = SessionState.RUNNING

    def abort(self) -> None:
        if self.state in {SessionState.COMPLETED, SessionState.ABORTED}:
            return
        self._stop_clock(self._clock_ns())
        self.state = SessionState.ABORTED
        self.result = self._make_result()

    def _make_result(self) -> EditingSessionResult:
        completed = self.state == SessionState.COMPLETED
        if self.mode == "guided":
            stars = typing_stars(
                completed=completed,
                correct=self._correct,
                incorrect=self._incorrect,
                extra_hints=self.extra_hints,
                step_returns=self.step_returns,
            )
        else:
            stars = editing_stars(
                completed=completed,
                key_count=self.key_count,
                baseline_keys=self.baseline_keys,
                extra_hints=self.extra_hints,
                step_returns=self.step_returns,
            )
        return EditingSessionResult(
            attempt_id=self.attempt_id,
            lesson_id=self.lesson.id,
            lesson_signature=self.lesson.signature,
            mode=self.mode,
            state=self.state,
            key_count=self.key_count,
            baseline_keys=self.baseline_keys,
            elapsed_seconds=self.elapsed_seconds,
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
        )
