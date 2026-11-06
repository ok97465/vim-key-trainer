"""Qt와 독립적인 숫자·기호 세션 진행."""

# Standard library imports
from collections import Counter
from collections.abc import Callable
from time import perf_counter_ns
from types import MappingProxyType
from uuid import uuid4

# Local imports
from vim_key_trainer.domain.exercises import PracticeSpec, generate_target, get_exercise
from vim_key_trainer.domain.game_rules import typing_stars
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionResult, SessionState


class PracticeSession:
    def __init__(
        self, spec: PracticeSpec, *, clock_ns: Callable[[], int] = perf_counter_ns
    ) -> None:
        self.spec = spec
        self.exercise = get_exercise(spec.exercise_id)
        self.target = generate_target(spec)
        self.attempt_id = str(uuid4())
        self.position = 0
        self.state = SessionState.READY
        self.combo = 0
        self.max_combo = 0
        self.incorrect = 0
        self._errors: Counter[str] = Counter()
        self.keypad_errors = 0
        self.pause_count = 0
        self.result: SessionResult | None = None
        self._clock_ns = clock_ns
        self._accumulated_ns = 0
        self._running_since_ns: int | None = None
        self._target_started_ns: int | None = None
        self._reaction_times: list[tuple[str, float]] = []
        self._paused_from_ready = False

    def _elapsed_ns(self, now_ns: int) -> int:
        running = (
            now_ns - self._running_since_ns if self._running_since_ns is not None else 0
        )
        return self._accumulated_ns + running

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed_ns(self._clock_ns()) / 1_000_000_000

    @property
    def accuracy(self) -> float | None:
        total = self.position + self.incorrect
        return 100 * self.position / total if total else None

    @property
    def errors(self) -> dict[str, int]:
        return dict(self._errors)

    @property
    def cpm(self) -> float | None:
        elapsed = self.elapsed_seconds
        return 60 * self.position / elapsed if elapsed > 0 else None

    def submit(self, token: KeyToken | None, *, keypad: bool = False) -> InputResult:
        if self.state not in {SessionState.READY, SessionState.RUNNING}:
            return InputResult.IGNORED
        if token is None or (token.kind == "special" and token.value == "backspace"):
            return InputResult.IGNORED

        now_ns = self._clock_ns()
        if self.state == SessionState.READY:
            self.state = SessionState.RUNNING
            self._running_since_ns = now_ns
        expected = self.target[self.position]
        is_keypad_number = keypad and token.kind == "char" and token.value.isdigit()
        if token.kind != "char" or token.value != expected or is_keypad_number:
            self.incorrect += 1
            self.combo = 0
            if is_keypad_number:
                self.keypad_errors += 1
            else:
                self._errors[expected] += 1
            return InputResult.REJECTED

        active_ns = self._elapsed_ns(now_ns)
        if self._target_started_ns is not None:
            self._reaction_times.append(
                (expected, (active_ns - self._target_started_ns) / 1_000_000_000)
            )
        self.position += 1
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self._target_started_ns = active_ns
        if self.position == len(self.target):
            self._stop_clock(now_ns)
            self.state = SessionState.COMPLETED
            self.result = self._make_result()
        return InputResult.ACCEPTED

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

    def _make_result(self) -> SessionResult:
        return SessionResult(
            attempt_id=self.attempt_id,
            spec=self.spec,
            target=self.target,
            state=self.state,
            correct=self.position,
            incorrect=self.incorrect,
            elapsed_seconds=self.elapsed_seconds,
            accuracy=self.accuracy,
            cpm=self.cpm,
            max_combo=self.max_combo,
            stars=typing_stars(
                completed=self.state == SessionState.COMPLETED,
                correct=self.position,
                incorrect=self.incorrect,
            ),
            errors=MappingProxyType(self.errors),
            keypad_errors=self.keypad_errors,
            pause_count=self.pause_count,
            reaction_times=tuple(self._reaction_times),
        )
