"""명령 경계·실제 특수키·일시정지 시간의 회귀 검증."""

# Standard library imports
from dataclasses import dataclass, replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.command_generator import get_command_profile
from vim_key_trainer.domain.commands import CommandItem, CommandLesson, CommandSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import (
    CommandSessionResult,
    InputResult,
    SessionState,
)
from vim_key_trainer.services import command_session as command_session_module
from vim_key_trainer.services.command_session import (
    CommandSession,
    ContinuousCommandSession,
)
from vim_key_trainer.services.result_repository import MemoryResultRepository


@dataclass
class Clock:
    seconds: float = 0

    def __call__(self) -> int:
        return round(self.seconds * 1_000_000_000)


def characters(value: str) -> tuple[KeyToken, ...]:
    return tuple(KeyToken("char", character) for character in value)


def lesson(*targets: tuple[KeyToken, ...]) -> CommandLesson:
    return CommandLesson(
        schema_version=1,
        content_version=1,
        id="command_test",
        title="명령 회귀 연습",
        description="명령 토큰을 독립적으로 입력합니다.",
        difficulty="beginner",
        tags=("test",),
        display_count=10,
        items=tuple(
            CommandItem(
                id=f"item_{index}",
                tokens=tokens,
                meaning=f"명령 {index}의 의미",
                start_mode="Normal",
                follow_up="",
            )
            for index, tokens in enumerate(targets)
        ),
    )


def complete(session: CommandSession) -> None:
    for token in session.target:
        assert session.submit(token) == InputResult.ACCEPTED


def test_item_boundaries_have_no_separator_and_explanation_changes_on_first_input() -> (
    None
):
    session = CommandSession(lesson(characters("dd"), characters("0")))
    assert session.explanation_index is None
    assert session.submit(None) == InputResult.IGNORED
    assert session.explanation_index is None
    assert session.submit(KeyToken("char", "x")) == InputResult.REJECTED
    assert session.explanation_index == session.command_index == 0
    assert session.position == session.token_index == 0
    assert session.submit(KeyToken("char", "d")) == InputResult.ACCEPTED
    assert session.token_index == 1
    assert session.submit(KeyToken("char", "d")) == InputResult.ACCEPTED
    assert session.command_index == 1
    assert session.token_index == 0
    assert session.explanation_index == 0
    assert session.submit(KeyToken("char", " ")) == InputResult.REJECTED
    assert session.explanation_index == 1
    assert session.position == 2
    assert session.submit(KeyToken("char", "0")) == InputResult.ACCEPTED
    assert session.state == SessionState.COMPLETED
    assert session.result is not None
    assert session.result.completed_commands == 2
    assert session.result.correct == 3
    assert session.result.incorrect == 2
    assert session.result.accuracy == 60


def test_escape_display_cannot_replace_real_escape() -> None:
    session = CommandSession(lesson(characters("ix") + (KeyToken("special", "esc"),)))
    session.submit(KeyToken("char", "i"))
    session.submit(KeyToken("char", "x"))
    for character in "<Esc>":
        assert session.submit(KeyToken("char", character)) == InputResult.REJECTED
    assert session.position == 2
    assert session.submit(KeyToken("special", "esc")) == InputResult.ACCEPTED
    assert session.result is not None
    assert session.result.correct == 3
    assert session.result.incorrect == 5


def test_zero_counts_uppercase_and_control_chords_remain_distinct() -> None:
    session = CommandSession(
        lesson(
            characters("0"),
            characters("10l"),
            characters("G"),
            (KeyToken("chord", "ctrl+r"),),
        )
    )
    assert session.submit(KeyToken("char", "1")) == InputResult.REJECTED
    assert session.submit(KeyToken("char", "0")) == InputResult.ACCEPTED
    for token in characters("10l"):
        assert session.submit(token) == InputResult.ACCEPTED
    assert session.submit(KeyToken("char", "g")) == InputResult.REJECTED
    assert session.submit(KeyToken("char", "G")) == InputResult.ACCEPTED
    assert session.submit(KeyToken("char", "r")) == InputResult.REJECTED
    assert session.submit(KeyToken("chord", "cmd+r")) == InputResult.REJECTED
    assert session.submit(KeyToken("chord", "ctrl+r")) == InputResult.ACCEPTED
    assert session.result is not None
    assert session.result.correct == 6
    assert session.result.incorrect == 4
    assert session.result.completed_commands == 4


def test_backspace_only_scores_when_explicit_and_enter_is_one_logical_key() -> None:
    session = CommandSession(
        lesson(
            characters("ia")
            + (
                KeyToken("special", "backspace"),
                KeyToken("special", "enter"),
                KeyToken("special", "esc"),
            )
        )
    )
    backspace = KeyToken("special", "backspace")
    assert session.submit(backspace) == InputResult.IGNORED
    assert session.state == SessionState.READY
    session.submit(KeyToken("char", "i"))
    session.submit(KeyToken("char", "a"))
    assert session.submit(backspace) == InputResult.ACCEPTED
    assert session.submit(backspace) == InputResult.IGNORED
    session.submit(KeyToken("special", "enter"))
    session.submit(KeyToken("special", "esc"))
    assert session.result is not None
    assert session.result.correct == 5
    assert session.result.incorrect == 0
    assert session.result.max_combo == 5


def test_command_time_includes_mistakes_excludes_pause_and_inter_item_wait() -> None:
    clock = Clock(10)
    session = CommandSession(lesson(characters("dd"), characters("gg")), clock_ns=clock)
    session.submit(KeyToken("char", "x"))  # 오타에서 첫 명령 측정을 시작한다.
    clock.seconds = 12
    session.submit(KeyToken("char", "d"))
    clock.seconds = 13
    session.pause()
    session.pause()
    clock.seconds = 100
    assert session.elapsed_seconds == 3
    assert session.submit(KeyToken("char", "d")) == InputResult.IGNORED
    session.resume()
    clock.seconds = 102
    session.submit(KeyToken("char", "d"))
    assert session.command_times == (("item_0", 5),)
    clock.seconds = 110  # 명령 사이의 대기는 전체 시간에만 포함한다.
    session.submit(KeyToken("char", "g"))
    clock.seconds = 112
    session.submit(KeyToken("char", "g"))
    clock.seconds = 1000
    assert session.result is not None
    assert session.result.command_times == (("item_0", 5), ("item_1", 2))
    assert session.elapsed_seconds == session.result.elapsed_seconds == 15
    assert session.commands_per_minute == 8
    assert session.result.pause_count == 1
    assert session.result.reaction_times == (("d", 3), ("g", 8), ("g", 2))
    assert session.result.max_combo == 4


def test_pause_ready_and_abort_do_not_invent_time_or_rewards() -> None:
    clock = Clock(2)
    session = CommandSession(lesson(characters("dd")), clock_ns=clock)
    session.pause()
    clock.seconds = 200
    session.resume()
    assert session.state == SessionState.READY
    assert session.elapsed_seconds == 0
    session.abort()
    assert session.state == SessionState.ABORTED
    assert session.result is not None
    result = session.result
    assert result.elapsed_seconds == 0
    assert result.accuracy is result.commands_per_minute is None
    assert result.stars == 0
    session.resume()
    session.abort()
    assert session.submit(KeyToken("char", "d")) == InputResult.IGNORED
    assert session.result is result


def test_terminal_result_is_frozen_and_keypad_digits_are_valid_in_command_stage() -> (
    None
):
    clock = Clock()
    session = CommandSession(lesson(characters("0")), clock_ns=clock)
    assert session.submit(KeyToken("char", "0"), keypad=True) == InputResult.ACCEPTED
    assert session.result is not None
    assert session.result.stars == 3
    assert session.result.keypad_errors == 0
    assert session.result.cpm is session.result.commands_per_minute is None
    assert session.result.command_times == (("item_0", 0),)
    assert session.submit(KeyToken("char", "0")) == InputResult.IGNORED
    with pytest.raises(TypeError):
        session.result.errors["x"] = 3  # type: ignore[index]


def test_same_seed_reproduces_item_order_and_retry_gets_new_attempt_id() -> None:
    content = lesson(*(characters(str(index)) for index in range(10)))
    first = CommandSession(content, CommandSpec(content.id, seed=42))
    retry = CommandSession(content, first.spec)
    assert first.items == retry.items
    assert first.target == retry.target
    assert first.attempt_id != retry.attempt_id
    assert first.items != CommandSession(content).items
    with pytest.raises(ValueError):
        CommandSession(content, CommandSpec("different"))


def test_records_are_idempotent_and_isolate_versions_and_boundaries() -> None:
    clock = Clock()
    content = lesson(characters("dd"), characters("gg"))
    repository = MemoryResultRepository()
    session = CommandSession(content, clock_ns=clock)
    complete(session)
    assert session.result is not None
    first = session.result
    assert repository.save(first)
    assert not repository.save(first)
    assert repository.completed_count == 1
    assert repository.best_command_stars(content.id, content.content_version) == 3
    for other_content in (
        replace(content, content_version=2),
        replace(content, items=lesson(characters("d"), characters("dgg")).items),
        replace(
            content,
            items=(replace(content.items[0], meaning="갱신된 설명"), content.items[1]),
        ),
    ):
        changed = CommandSession(other_content, clock_ns=clock)
        complete(changed)
        assert changed.result is not None
        assert repository.best_for(changed.result) is None
        assert repository.save(changed.result)
    assert repository.best_for(first) == first
    assert repository.completed_count == 4


def test_command_best_prefers_accuracy_then_time_and_separates_pause_usage() -> None:
    repository = MemoryResultRepository()
    content = lesson(characters("dd"))

    def result(
        seconds: float, mistakes: int = 0, pause: bool = False
    ) -> CommandSessionResult:
        clock = Clock()
        session = CommandSession(content, clock_ns=clock)
        for _ in range(mistakes):
            session.submit(KeyToken("char", "x"))
        session.submit(KeyToken("char", "d"))
        if pause:
            session.pause()
            session.resume()
        clock.seconds = seconds
        session.submit(KeyToken("char", "d"))
        assert session.result is not None
        return session.result

    inaccurate = result(1, mistakes=1)
    accurate = result(5)
    faster = result(3)
    paused = result(10, pause=True)
    assert repository.save(inaccurate)
    assert repository.save(accurate)
    assert repository.save(faster)
    assert repository.save(paused)
    assert not repository.save(result(4))
    assert repository.best_for(inaccurate) == faster
    assert repository.best_for(paused) == paused


def test_command_stars_separate_content_and_game_rules_versions() -> None:
    repository = MemoryResultRepository()
    content = lesson(characters("dd"))
    original = CommandSession(content)
    complete(original)
    assert original.result is not None
    assert repository.save(original.result)
    assert repository.best_command_stars(content.id, 1) == 3
    assert repository.best_command_stars(content.id, 2) == 0
    assert repository.best_command_stars(content.id, 1, game_rules_version=2) == 0
    assert repository.best_stars(content.id) == 0

    updated = CommandSession(replace(content, content_version=2))
    updated.submit(KeyToken("char", "x"))
    complete(updated)
    assert updated.result is not None
    assert updated.result.stars == 1
    assert repository.save(updated.result)
    assert repository.best_command_stars(content.id, 1) == 3
    assert repository.best_command_stars(content.id, 2) == 1

    new_rules = replace(updated.result, attempt_id="new-rules", game_rules_version=2)
    assert repository.save(new_rules)
    assert repository.best_command_stars(content.id, 2, game_rules_version=2) == 1
    assert repository.best_command_stars(content.id, 1, game_rules_version=2) == 0
    assert not repository.save(new_rules)


@pytest.fixture
def predictable_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    class Generator:
        index = 0

        def __init__(self, profile: object, seed: int) -> None:
            self.index = 0

        def next_item(self) -> CommandItem:
            self.index += 1
            return CommandItem(
                id=f"sample_{self.index % 3}",
                tokens=characters("dd"),
                meaning=f"연습 {self.index}",
                start_mode="Normal",
                follow_up="완결된 명령입니다.",
            )

    monkeypatch.setattr(command_session_module, "CommandGenerator", Generator)


def complete_current(session: ContinuousCommandSession) -> None:
    current = session.items[session.command_index]
    for token in current.tokens[session.token_index :]:
        assert session.submit(token) == InputResult.ACCEPTED


def test_continuous_pages_keep_totals_and_bound_history(
    predictable_stream: None,
) -> None:
    clock = Clock()
    session = ContinuousCommandSession(
        get_command_profile("commands_random"), clock_ns=clock
    )
    initial_items = session.items
    for index in range(1_000):
        clock.seconds = float(index)
        complete_current(session)
    assert session.state == SessionState.RUNNING
    assert session.result is None
    assert session.completed_commands == session.page_start_count == 1_000
    assert session.position == session.combo == session.max_combo == 2_000
    assert session.command_index == session.token_index == 0
    assert len(session.items) == session.profile.display_count == 10
    assert session.items != initial_items
    assert len(session.command_times) == len(session.command_samples) == 100
    assert session.finish()
    assert session.result is not None
    assert session.result.correct == 2_000
    assert session.result.completed_commands == 1_000
    assert session.result.target == ()
    assert len(session.result.command_samples) == 100
    assert len(session.result.reaction_times) == 500
    assert len(session.result.transcript_digest) == 64


def test_continuous_finish_waits_for_started_command_and_is_terminal(
    predictable_stream: None,
) -> None:
    clock = Clock(5)
    session = ContinuousCommandSession(
        get_command_profile("commands_random"), clock_ns=clock
    )
    assert not session.finish()
    assert session.state == SessionState.READY
    assert session.submit(KeyToken("special", "backspace")) == InputResult.IGNORED
    assert not session.finish_requested
    session.submit(KeyToken("char", "d"))
    clock.seconds = 6
    assert not session.finish()
    assert session.finish_requested
    assert session.state == SessionState.RUNNING
    assert session.completed_commands == 0
    clock.seconds = 8
    session.submit(KeyToken("char", "d"))
    assert session.state == SessionState.COMPLETED
    assert session.result is not None
    result = session.result
    assert result.correct == 2
    assert result.completed_commands == 1
    assert result.command_samples[0].display == "dd"
    assert result.command_samples[0].seconds == 3
    assert result.elapsed_seconds == 3
    assert result.stars == 3
    clock.seconds = 500
    session.abort()
    assert not session.finish()
    assert session.submit(KeyToken("char", "d")) == InputResult.IGNORED
    assert session.result is result
    assert session.elapsed_seconds == 3


def test_continuous_wrong_first_key_cannot_be_discarded_by_finish(
    predictable_stream: None,
) -> None:
    clock = Clock(1)
    session = ContinuousCommandSession(
        get_command_profile("commands_random"), clock_ns=clock
    )
    session.submit(KeyToken("char", "x"))
    assert not session.finish()
    assert session.finish_requested
    assert session.position == 0
    assert session.incorrect == 1
    clock.seconds = 4
    complete_current(session)
    assert session.result is not None
    assert session.result.incorrect == 1
    assert session.result.elapsed_seconds == 3
    assert session.result.command_samples[0].seconds == 3
    assert session.result.stars == 1


def test_continuous_refill_preserves_previous_meaning_until_next_scored_input(
    predictable_stream: None,
) -> None:
    session = ContinuousCommandSession(get_command_profile("commands_random"))
    for _ in range(session.profile.display_count):
        complete_current(session)
    assert session.command_index == 0
    assert session.page_start_count == 10
    assert session.explanation_item is not None
    assert session.explanation_item.meaning == "연습 10"
    session.submit(None)
    assert session.explanation_item.meaning == "연습 10"
    session.submit(KeyToken("char", "x"))
    assert session.explanation_item.meaning == "연습 11"
    assert session.completed_commands == 10


def test_continuous_pause_excludes_time_and_finish_can_complete_while_paused(
    predictable_stream: None,
) -> None:
    clock = Clock(10)
    session = ContinuousCommandSession(
        get_command_profile("commands_random"), clock_ns=clock
    )
    session.submit(KeyToken("char", "x"))
    clock.seconds = 12
    session.submit(KeyToken("char", "d"))
    clock.seconds = 13
    session.pause()
    clock.seconds = 100
    assert session.submit(KeyToken("char", "d")) == InputResult.IGNORED
    session.resume()
    clock.seconds = 102
    session.submit(KeyToken("char", "d"))
    assert session.command_times[0][1] == 5
    assert session.elapsed_seconds == 5
    clock.seconds = 110
    complete_current(session)
    assert session.command_times[1][1] == 0
    session.pause()
    clock.seconds = 200
    assert session.finish()
    assert session.result is not None
    assert session.result.elapsed_seconds == 13
    assert session.result.pause_count == 2
    assert session.result.completed_commands == 2
    assert session.result.commands_per_minute == pytest.approx(120 / 13)


def test_continuous_seed_replays_beyond_first_page() -> None:
    profile = get_command_profile("commands_random")
    first = ContinuousCommandSession(profile, CommandSpec(profile.id, seed=17))
    retry = ContinuousCommandSession(profile, first.spec)
    other = ContinuousCommandSession(profile, CommandSpec(profile.id, seed=18))
    assert first.attempt_id != retry.attempt_id
    assert first.items != other.items
    for _ in range(35):
        assert first.items == retry.items
        complete_current(first)
        complete_current(retry)
    first.finish()
    retry.finish()
    assert first.result is not None
    assert retry.result is not None
    assert first.result.transcript_digest == retry.result.transcript_digest
    assert first.result.item_ids == retry.result.item_ids


def test_continuous_results_compare_same_generated_problem_and_count(
    predictable_stream: None,
) -> None:
    profile = get_command_profile("commands_random")

    def result(count: int, seconds: float) -> CommandSessionResult:
        clock = Clock()
        session = ContinuousCommandSession(profile, clock_ns=clock)
        for _ in range(count):
            complete_current(session)
        clock.seconds = seconds
        assert session.finish()
        assert session.result is not None
        return session.result

    repository = MemoryResultRepository()
    first = result(12, 5)
    assert repository.save(first)
    assert not repository.save(first)
    faster = result(12, 4)
    assert repository.save(faster)
    assert repository.best_for(first) == faster
    longer = result(13, 2)
    assert repository.best_for(longer) is None
    assert repository.save(longer)
    assert repository.best_for(first) == faster
    for change in (
        {"generator_version": first.generator_version + 1},
        {"transcript_digest": "different"},
        {"pause_count": 1},
    ):
        changed = replace(first, attempt_id=str(change), **change)
        assert repository.best_for(changed) is None
        assert repository.save(changed)
    assert repository.completed_count == 6
