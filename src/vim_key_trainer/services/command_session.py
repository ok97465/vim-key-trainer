"""Qt·실제 Vim 실행과 독립적인 명령 타이핑 세션."""

# Standard library imports
import hashlib
import json
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import asdict, replace
from random import Random
from time import perf_counter_ns
from types import MappingProxyType
from uuid import uuid4

# Local imports
from vim_key_trainer.domain.command_generator import (
    GENERATOR_VERSION,
    CommandGenerator,
    CommandProfile,
)
from vim_key_trainer.domain.commands import CommandItem, CommandLesson, CommandSpec
from vim_key_trainer.domain.game_rules import typing_stars
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    CommandTiming,
    InputResult,
    SessionState,
)


class CommandSession:
    continuous = False
    MAX_COMMAND_SAMPLES: int | None = None
    MAX_REACTION_SAMPLES: int | None = None
    lesson: CommandLesson | CommandProfile

    def __init__(
        self,
        lesson: CommandLesson,
        spec: CommandSpec | None = None,
        *,
        clock_ns: Callable[[], int] = perf_counter_ns,
    ) -> None:
        self.lesson = lesson
        actual_spec = spec or CommandSpec(lesson.id)
        items = list(lesson.items)
        if actual_spec.seed:
            Random(actual_spec.seed).shuffle(items)
        self._initialize(tuple(items), actual_spec, clock_ns)
        self._lesson_signature = hashlib.sha256(
            json.dumps(asdict(self.lesson), ensure_ascii=True, sort_keys=True).encode()
        ).hexdigest()

    def _initialize(
        self,
        items: tuple[CommandItem, ...],
        spec: CommandSpec,
        clock_ns: Callable[[], int],
    ) -> None:
        if spec.lesson_id != self.lesson.id:
            raise ValueError("연습 조건과 콘텐츠 ID가 다릅니다.")
        self.spec = spec
        self.items = items
        self.target = tuple(token for item in items for token in item.tokens)
        self.attempt_id = str(uuid4())
        self.position = 0
        self.command_index = 0
        self.token_index = 0
        self.explanation_index: int | None = None
        self._explanation_item: CommandItem | None = None
        self._completed_commands = 0
        self.state = SessionState.READY
        self.combo = 0
        self.max_combo = 0
        self.incorrect = 0
        self.keypad_errors = 0
        self.pause_count = 0
        self.result: CommandSessionResult | None = None
        self._errors: Counter[str] = Counter()
        self._command_samples: deque[CommandTiming] = deque(
            maxlen=self.MAX_COMMAND_SAMPLES
        )
        self._clock_ns = clock_ns
        self._accumulated_ns = 0
        self._running_since_ns: int | None = None
        self._target_started_ns: int | None = None
        self._command_started_ns: int | None = None
        self._reaction_times: deque[tuple[str, float]] = deque(
            maxlen=self.MAX_REACTION_SAMPLES
        )
        self._paused_from_ready = False

    @property
    def expected_token(self) -> KeyToken | None:
        return self.target[self.position] if self.position < len(self.target) else None

    @property
    def completed_commands(self) -> int:
        return self._completed_commands

    @property
    def explanation_item(self) -> CommandItem | None:
        return self._explanation_item

    @property
    def command_times(self) -> tuple[tuple[str, float], ...]:
        return tuple(
            (sample.item_id, sample.seconds) for sample in self._command_samples
        )

    @property
    def command_samples(self) -> tuple[CommandTiming, ...]:
        return tuple(self._command_samples)

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

    @property
    def commands_per_minute(self) -> float | None:
        elapsed = self.elapsed_seconds
        return 60 * self.completed_commands / elapsed if elapsed > 0 else None

    def submit(self, token: KeyToken | None, *, keypad: bool = False) -> InputResult:
        if self.state not in {SessionState.READY, SessionState.RUNNING}:
            return InputResult.IGNORED
        expected = self.expected_token
        if token is None or (
            token == KeyToken("special", "backspace") and token != expected
        ):
            return InputResult.IGNORED

        now_ns = self._clock_ns()
        if self.state == SessionState.READY:
            self.state = SessionState.RUNNING
            self._running_since_ns = now_ns
        active_ns = self._elapsed_ns(now_ns)
        item = self.items[self.command_index]
        self.explanation_index = self.command_index
        self._explanation_item = item
        if self._command_started_ns is None:
            self._command_started_ns = active_ns
        if token != expected:
            self.incorrect += 1
            self.combo = 0
            assert expected is not None
            self._errors[expected.display] += 1
            return InputResult.REJECTED

        assert expected is not None
        if self._target_started_ns is not None:
            self._reaction_times.append(
                (
                    expected.display,
                    (active_ns - self._target_started_ns) / 1_000_000_000,
                )
            )
        self.position += 1
        self.token_index += 1
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self._target_started_ns = active_ns
        if self.token_index == len(item.tokens):
            seconds = (active_ns - self._command_started_ns) / 1_000_000_000
            self._command_samples.append(CommandTiming(item.id, item.display, seconds))
            self.command_index += 1
            self._completed_commands += 1
            self.token_index = 0
            self._command_started_ns = None
            self._on_command_completed(item, now_ns)
        return InputResult.ACCEPTED

    def _on_command_completed(self, item: CommandItem, now_ns: int) -> None:
        if self.command_index == len(self.items):
            self._complete(now_ns)

    def _complete(self, now_ns: int) -> None:
        self._stop_clock(now_ns)
        self.state = SessionState.COMPLETED
        self.result = self._make_result()

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

    def _make_result(self) -> CommandSessionResult:
        return CommandSessionResult(
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
            lesson_version=self.lesson.content_version,
            lesson_signature=self._lesson_signature,
            item_ids=tuple(item.id for item in self.items),
            display_count=self.lesson.display_count,
            completed_commands=self.completed_commands,
            command_times=self.command_times,
            commands_per_minute=self.commands_per_minute,
        )


class ContinuousCommandSession(CommandSession):
    """한 페이지씩 생성하며 명시적으로 마칠 때까지 이어지는 명령 연습.

    시도 전체는 seed와 생성기 버전으로 재생할 수 있다. 완료한 입력은 해시로
    누적하고 최근 시간 표본만 보관해 긴 연습도 메모리 사용량을 제한한다.
    """

    continuous = True
    MAX_COMMAND_SAMPLES = 100
    MAX_REACTION_SAMPLES = 500

    def __init__(
        self,
        profile: CommandProfile,
        spec: CommandSpec | None = None,
        *,
        clock_ns: Callable[[], int] = perf_counter_ns,
    ) -> None:
        self.profile = profile
        self.lesson = profile
        actual_spec = spec or CommandSpec(profile.id)
        if actual_spec.lesson_id != profile.id:
            raise ValueError("연습 조건과 생성 프로필 ID가 다릅니다.")
        self._generator = CommandGenerator(profile, actual_spec.seed)
        preview = tuple(
            self._generator.next_item() for _ in range(profile.display_count)
        )
        self._initialize(preview, actual_spec, clock_ns)
        self.page_start_count = 0
        self.finish_requested = False
        self._transcript = hashlib.sha256()
        self._lesson_signature = hashlib.sha256(
            json.dumps(
                {"profile": asdict(profile), "generator_version": GENERATOR_VERSION},
                ensure_ascii=True,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    @property
    def expected_token(self) -> KeyToken | None:
        if self.state in {SessionState.COMPLETED, SessionState.ABORTED}:
            return None
        return self.items[self.command_index].tokens[self.token_index]

    def _on_command_completed(self, item: CommandItem, now_ns: int) -> None:
        # JSON으로 구분해 문자·특수키와 명령 경계가 서로 충돌하지 않게 한다.
        self._transcript.update(
            json.dumps(
                [(key.kind, key.value) for key in item.tokens],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode()
        )
        self._transcript.update(b"\n")
        if self.finish_requested:
            self._complete(now_ns)
        elif self.command_index == len(self.items):
            self.page_start_count = self.completed_commands
            self.items = tuple(
                self._generator.next_item() for _ in range(self.profile.display_count)
            )
            self.target = tuple(key for entry in self.items for key in entry.tokens)
            self.command_index = 0
            # 설명 자체는 유지하고 이전 페이지의 인덱스만 해제한다.
            self.explanation_index = None

    def finish(self) -> bool:
        """완료한 명령을 보존하고, 입력 중인 명령이 있으면 마친 뒤 종료한다."""
        if self.state not in {
            SessionState.READY,
            SessionState.RUNNING,
            SessionState.PAUSED,
        }:
            return False
        if self._command_started_ns is not None:
            self.finish_requested = True
            return False
        if self.completed_commands == 0:
            return False
        self.finish_requested = True
        self._complete(self._clock_ns())
        return True

    def _make_result(self) -> CommandSessionResult:
        return replace(
            super()._make_result(),
            # 전체 스트림 대신 재생 조건과 누적 해시를 기록한다.
            target=(),
            item_ids=tuple(sample.item_id for sample in self._command_samples),
            generator_version=GENERATOR_VERSION,
            transcript_digest=self._transcript.hexdigest(),
            command_samples=self.command_samples,
        )
