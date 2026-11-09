"""가짜 시간원으로 마감·복구·복습·복수전의 독립성과 중복 정산을 검증한다."""

# Standard library imports
from dataclasses import dataclass, replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.challenge import (
    TIME_RULES,
    ChallengeOptions,
    TimeRules,
)
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.editing import EditLesson, EditPracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.sessions import InputResult, SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_problem_factory import create_edit_problem
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_codec import decode_result, encode_result

ESC = KeyToken("special", "esc")


def chars(text: str) -> tuple[KeyToken, ...]:
    return tuple(KeyToken("char", character) for character in text)


@dataclass
class Clock:
    ns: int = 0

    def __call__(self) -> int:
        return self.ns

    def add(self, seconds: float) -> None:
        self.ns += round(seconds * 1_000_000_000)


def two_segments() -> EditLesson:
    initial = EditorState(("n=1", "m=2"))
    guide = GuideBuilder(initial, SUPPORTED_COMMANDS)
    guide.record(chars("$r3"), "첫 숫자 교체")
    guide.finish_segment(0, 0)
    guide.navigate(1, 2)
    guide.record(chars("r4"), "둘째 숫자 교체")
    guide.finish_segment(1, 1)
    baseline = tuple(key for step in guide.steps for key in step.keys)
    return EditLesson(
        1,
        1,
        "bomb_test",
        "두 숫자",
        "두 곳을 수정합니다.",
        initial,
        ("n=3", "m=4"),
        None,
        SUPPORTED_COMMANDS,
        tuple(guide.steps),
        1,
        baseline,
        len(baseline),
        segments=tuple(guide.segments),
    )


def session_for(
    clock: Clock, *, auto: bool = True, mode: str = "guided"
) -> EditingSession:
    assert mode in {"guided", "free"}
    return EditingSession(
        two_segments(),
        mode,
        clock_ns=clock,
        challenge=ChallengeOptions("bomb", auto_repair=auto),
    )


def play(session: EditingSession, keys: tuple[KeyToken, ...]) -> None:
    for key in keys:
        assert session.submit(key) == InputResult.ACCEPTED


def finish(session: EditingSession) -> None:
    while session.state in {SessionState.RUNNING, SessionState.READY}:
        key = session.expected_token
        assert key is not None
        assert session.submit(key) == InputResult.ACCEPTED


def test_first_input_starts_timer_and_exact_deadline_key_is_not_forwarded() -> None:
    clock = Clock()
    session = session_for(clock)
    limit = session.segment_limit_seconds
    assert limit is not None
    clock.add(1000)
    assert not session.check_deadline()
    assert session.remaining_seconds == limit
    assert session.submit(session.expected_token) == InputResult.ACCEPTED
    guard = session.timer_guard
    clock.add(limit)
    expected = session.expected_token
    assert session.submit(expected) == InputResult.REJECTED
    assert session.timeout_count == session.auto_repair_count == 1
    assert session.direct_count == 0
    assert session.key_count == 2 and session.incorrect == 1
    assert session.token_index == 0 and session.step_index == 1
    assert session.engine.state.lines == ("n=3", "m=2")
    assert session.remaining_seconds == session.segment_limit_seconds
    assert not session.check_deadline(guard)
    assert session.key_count == 2
    finish(session)
    assert session.result is not None
    assert session.result.stars == 0
    assert (
        session.result.challenge is not None and not session.result.challenge.full_clear
    )
    assert decode_result(encode_result(session.result)) == session.result


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_last_answer_deadline_nanosecond_boundary(offset: int) -> None:
    clock = Clock()
    session = session_for(clock)
    play(session, chars("$r"))
    limit = session.segment_limit_seconds
    assert limit is not None
    clock.ns = round(limit * 1_000_000_000) + offset
    outcome = session.submit(KeyToken("char", "3"))
    assert outcome == (InputResult.ACCEPTED if offset < 0 else InputResult.REJECTED)
    assert session.direct_count == (1 if offset < 0 else 0)
    assert session.timeout_count == (0 if offset < 0 else 1)


def test_delayed_timer_starts_next_segment_at_actual_activation_not_old_deadline() -> (
    None
):
    clock = Clock()
    session = session_for(clock)
    play(session, chars("$"))
    stale = session.timer_guard
    clock.add(500)
    assert session.check_deadline(stale)
    assert session.timeout_count == 1
    assert not session.check_deadline(stale)
    assert not session.check_deadline()
    assert session.remaining_seconds == session.segment_limit_seconds
    assert session.state == SessionState.RUNNING


def test_pause_at_expiry_cannot_escape_failure_but_excludes_paused_time() -> None:
    clock = Clock()
    session = session_for(clock)
    play(session, chars("$"))
    limit = session.segment_limit_seconds
    assert limit is not None
    clock.add(limit)
    session.pause()
    assert session.state == SessionState.PAUSED
    assert session.timeout_count == 1
    remaining = session.remaining_seconds
    stale = session.timer_guard
    clock.add(1000)
    assert session.remaining_seconds == remaining
    assert not session.check_deadline(stale)
    assert session.submit(session.expected_token) == InputResult.IGNORED
    session.resume()
    assert not session.check_deadline(stale)
    finish(session)
    assert session.result is not None and session.result.elapsed_seconds == limit


def test_review_keeps_unsettled_timer_and_never_pays_completed_segment_twice() -> None:
    clock = Clock()
    session = session_for(clock)
    play(session, chars("$r3"))
    assert session.direct_count == session.chain == 1
    limit = session.segment_limit_seconds
    assert limit is not None
    clock.add(2)
    assert session.return_to_step(0)
    assert session.remaining_seconds == pytest.approx(limit - 2)
    play(session, chars("$r3"))
    assert session.direct_count == session.chain == 1
    assert session.remaining_seconds == pytest.approx(limit - 2)
    assert session.return_to_step(0)
    clock.add(limit)
    session.check_deadline()
    assert session.timeout_count == session.auto_repair_count == 1
    assert session.engine.state.lines == session.lesson.goal_lines
    assert session.state == SessionState.COMPLETED
    assert session.result is not None and session.result.stars == 0
    assert decode_result(encode_result(session.result)) == session.result


def test_auto_off_records_timeout_once_and_requires_manual_finish() -> None:
    clock = Clock()
    session = session_for(clock, auto=False)
    play(session, chars("$"))
    before = session.engine.snapshot()
    limit = session.segment_limit_seconds
    assert limit is not None
    clock.add(limit)
    assert session.check_deadline()
    assert session.engine.snapshot() == before
    assert session.remaining_seconds is None
    assert session.timeout_count == 1 and session.auto_repair_count == 0
    clock.add(100)
    assert not session.check_deadline()
    play(session, chars("r3"))
    assert session.timeout_count == 1 and session.direct_count == 0
    assert session.remaining_seconds == session.segment_limit_seconds
    finish(session)
    assert session.result is not None and session.result.stars == 0
    assert decode_result(encode_result(session.result)) == session.result


def test_all_auto_recovered_document_withholds_completion_rewards() -> None:
    clock = Clock()
    session = session_for(clock)
    session.submit(KeyToken("char", "Q"))
    for _ in range(2):
        clock.add(100)
        assert session.check_deadline()
    assert session.engine.state.lines == session.lesson.goal_lines
    assert session.result is not None
    result = session.result
    assert result.state == SessionState.COMPLETED
    assert result.challenge is not None
    assert result.challenge.timeout_count == result.challenge.auto_repair_count == 2
    assert not result.challenge.full_clear and result.stars == 0
    assert not result.completion_eligible and not result.efficiency_eligible
    assert decode_result(encode_result(result)) == result


def test_abort_settles_expired_segment_and_retry_restarts_same_conditions() -> None:
    clock = Clock()
    session = session_for(clock, auto=False)
    play(session, chars("$"))
    clock.add(100)
    session.abort()
    result = session.result
    assert result is not None and result.state == SessionState.ABORTED
    assert result.challenge is not None and result.challenge.timeout_count == 1
    assert decode_result(encode_result(result)) == result
    session.abort()
    assert session.result is result
    retry = session.retry()
    assert retry.attempt_id != session.attempt_id
    assert retry.challenge == session.challenge
    assert retry.lesson.signature == session.lesson.signature
    assert retry.timeout_count == 0


def test_revenge_uses_prerequisites_and_withholds_completion_rewards() -> None:
    clock = Clock()
    session = session_for(clock)
    play(session, chars("$r3"))
    clock.add(100)
    assert session.check_deadline()
    original = session.result
    assert original is not None
    revenge = session.create_revenge()
    assert revenge.attempt_id != session.attempt_id
    assert len(revenge.segments) == 1
    assert revenge.engine.state.lines == ("n=3", "m=2")
    finish(revenge)
    assert session.result is original
    result = revenge.result
    assert result is not None and result.challenge is not None
    assert result.challenge.full_clear
    assert result.challenge.revenge_of == original.lesson_signature
    assert result.stars == 0 and not result.completion_eligible
    assert result.baseline_keys == sum(
        len(step.keys) for step in session.lesson.guide[1:]
    )
    assert decode_result(encode_result(result)) == result
    assert revenge.retry().revenge_segments == revenge.revenge_segments


def test_revenge_excludes_skipped_segment_preparation_from_active_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = EditorState(("n=1", "m=2", "p=3"))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    for row, replacement in enumerate("456"):
        start = len(builder.steps)
        builder.navigate(row, 2)
        builder.record(chars(f"r{replacement}"), "숫자 교체")
        builder.finish_segment(start, row)
    baseline = tuple(key for step in builder.steps for key in step.keys)
    lesson = replace(
        two_segments(),
        initial=initial,
        goal_lines=("n=4", "m=5", "p=6"),
        guide=tuple(builder.steps),
        baseline=baseline,
        baseline_keys=len(baseline),
        segments=tuple(builder.segments),
    )
    clock = Clock()
    original = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=clock
    )
    original.submit(KeyToken("char", "Q"))
    clock.add(100)
    assert original.check_deadline()
    for step in lesson.guide[
        lesson.segments[1].start_step : lesson.segments[1].end_step
    ]:
        play(original, step.keys)
    clock.add(100)
    assert original.check_deadline()
    revenge = original.create_revenge()
    restore = revenge.engine.restore

    def slow_restore(snapshot: object) -> None:
        clock.add(5)
        restore(snapshot)

    monkeypatch.setattr(revenge.engine, "restore", slow_restore)
    while revenge.active_segment_index == 0:
        clock.add(0.1)
        assert revenge.submit(revenge.expected_token) == InputResult.ACCEPTED
    assert revenge.remaining_seconds == revenge.segment_limit_seconds
    assert revenge.elapsed_seconds == pytest.approx(revenge.key_count * 0.1 - 0.1)
    finish(revenge)
    assert revenge.result is not None
    assert decode_result(encode_result(revenge.result)) == revenge.result


def test_free_timer_accepts_alternative_and_timeout_preserves_document() -> None:
    clock = Clock()
    session = session_for(clock, mode="free")
    assert len(session.segments) == 1
    play(session, chars("$r3"))
    before = session.engine.snapshot()
    clock.add(100)
    assert session.check_deadline()
    assert session.engine.snapshot() == before
    assert session.auto_repair_count == 0
    play(session, chars("jr4"))
    assert session.result is not None and session.result.stars == 0
    assert decode_result(encode_result(session.result)) == session.result


@pytest.mark.parametrize("prefix", ["i", "R", "v", "/abc", ":s/a", "2d"])
def test_recovery_clears_all_partial_modes_without_counting_system_input(
    prefix: str,
) -> None:
    clock = Clock()
    session = session_for(clock)
    session.submit(KeyToken("char", "$"))
    # 가이드 이외의 중간 상태를 엔진에 직접 구성해 원자적 복구 경계를 검사한다.
    for key in chars(prefix):
        session.engine.submit(key)
    count = session.key_count
    correct = session.correct
    clock.add(100)
    session.check_deadline()
    assert session.engine.state.mode == "normal"
    assert not session.engine.state.pending and not session.engine.state.command_line
    assert session.key_count == count and session.correct == correct
    recovered = session.engine.state.lines
    session.engine.submit(KeyToken("char", "u"))
    assert session.engine.state.lines == recovered
    session.engine.submit(KeyToken("chord", "ctrl+r"))
    assert session.engine.state.lines == recovered
    finish(session)
    assert session.result is not None


def test_invalid_recovery_snapshot_preserves_current_document_and_pauses() -> None:
    clock = Clock()
    session = session_for(clock)
    session.submit(KeyToken("char", "$"))
    before = session.engine.snapshot()
    endpoint = session.segments[0].end_step
    session._prepared_steps[endpoint] = replace(
        session._prepared_steps[endpoint], state=EditorState(("wrong",))
    )
    clock.add(100)
    assert session.check_deadline()
    assert session.engine.snapshot() == before
    assert session.state == SessionState.PAUSED and session.recovery_error
    assert session.timeout_count == 1 and session.auto_repair_count == 0
    session.resume()
    assert session.state == SessionState.PAUSED


@pytest.mark.parametrize(
    "profile",
    [
        "editing_numbers",
        "editing_delete_line",
        "editing_delete_word",
        "editing_append",
        "editing_compound",
        "code_json",
    ],
)
def test_generated_recipe_segments_validate_and_recover_independently(
    profile: str,
) -> None:
    clock = Clock()
    lesson = create_edit_problem(
        EditPracticeSpec(profile, 313, 60 if profile == "code_json" else 24)
    )
    session = EditingSession(lesson, challenge=ChallengeOptions("bomb"), clock_ns=clock)
    assert len(session.segments) >= 7
    session.submit(KeyToken("char", "Q"))
    for _ in session.segments:
        clock.add(1000)
        assert session.check_deadline()
    assert session.result is not None
    assert session.engine.state.lines == lesson.goal_lines
    assert session.result.stars == 0
    assert decode_result(encode_result(session.result)) == session.result


def test_undo_is_explicitly_excluded_and_rules_are_frozen_integer_grid() -> None:
    lesson = create_edit_problem(EditPracticeSpec("editing_undo", 313))
    with pytest.raises(ValueError, match="실행 취소"):
        EditingSession(lesson, challenge=ChallengeOptions("bomb"))
    assert (
        TIME_RULES.limit_seconds(
            key_count=10, row_distance=0, search_count=0, difficulty="normal"
        )
        == 10.5
    )
    assert (
        TIME_RULES.limit_seconds(
            key_count=10, row_distance=0, search_count=0, difficulty="relaxed"
        )
        == 15.8
    )
    assert (
        TIME_RULES.limit_seconds(
            key_count=1, row_distance=0, search_count=0, difficulty="challenge"
        )
        == 6
    )
    with pytest.raises(ValueError):
        TimeRules(per_key_ms=-1)


@pytest.mark.parametrize(
    ("navigation", "search_count", "goal"),
    [
        (chars("f?"), 0, "a!/b1"),
        (chars("f/"), 0, "a?!b1"),
        (chars("/?") + (KeyToken("special", "enter"),), 1, "a!/b1"),
        (chars("2/?") + (KeyToken("special", "enter"),), 1, "a!/b1"),
    ],
)
@pytest.mark.parametrize("single_step", [False, True])
def test_search_allowance_counts_search_commands_and_excludes_find_arguments(
    navigation: tuple[KeyToken, ...], search_count: int, goal: str, single_step: bool
) -> None:
    initial = EditorState(("a?/b1",))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    if single_step:
        builder.record(navigation + chars("r!"), "기호를 찾아 교체")
    else:
        builder.record(navigation, "기호 찾기")
        builder.record(chars("r!"), "기호 교체")
    builder.finish_segment(0, 0)
    baseline = navigation + chars("r!")
    lesson = replace(
        two_segments(),
        initial=initial,
        goal_lines=(goal,),
        guide=tuple(builder.steps),
        baseline=baseline,
        baseline_keys=len(baseline),
        segments=tuple(builder.segments),
    )
    practice = EditingSession(lesson, challenge=ChallengeOptions("bomb"))
    assert practice.segment_limit_seconds == TIME_RULES.limit_seconds(
        key_count=len(baseline),
        row_distance=0,
        search_count=search_count,
        difficulty="normal",
    )


@pytest.mark.parametrize("profile", ["code_python", "code_cpp"])
@pytest.mark.parametrize("lines", [300, 500])
def test_large_code_recovery_and_copy_prerequisites(profile: str, lines: int) -> None:
    clock = Clock()
    lesson = create_edit_problem(EditPracticeSpec(profile, 23, lines))
    session = EditingSession(lesson, challenge=ChallengeOptions("bomb"), clock_ns=clock)
    assert session.submit(KeyToken("char", "Q")) == InputResult.REJECTED
    # 복구는 초기 준비 스냅샷만 사용한다. 이후 전체 가이드 재생에 의존하지 않는다.
    for index, segment in enumerate(session.segments):
        if index:
            assert segment.prerequisite_ids == (session.segments[index - 1].id,)
        clock.add(1000)
        assert session.check_deadline()
    assert session.engine.state.lines == lesson.goal_lines
    assert session.result is not None
    assert decode_result(encode_result(session.result)) == session.result
    revenge = session.create_revenge()
    finish(revenge)
    assert revenge.result is not None and revenge.result.challenge is not None
    assert revenge.result.challenge.full_clear
    assert revenge.result.challenge.max_chain == len(session.segments)


@pytest.mark.parametrize("second_auto", [False, True])
def test_recovery_marker_follows_later_row_deletion(second_auto: bool) -> None:
    initial = EditorState(("delete me", "keep me", "n=1"))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    builder.navigate(2, 2)
    builder.record(chars("r2"), "숫자 교체")
    builder.finish_segment(0, 2)
    start = len(builder.steps)
    builder.navigate(0, None)
    builder.record(chars("dd"), "앞의 줄 삭제")
    builder.finish_segment(start, 0)
    baseline = tuple(key for step in builder.steps for key in step.keys)
    lesson = EditLesson(
        1,
        1,
        "marker_test",
        "표식 이동",
        "행 삭제 표식",
        initial,
        ("keep me", "n=2"),
        None,
        SUPPORTED_COMMANDS,
        tuple(builder.steps),
        1,
        baseline,
        len(baseline),
        segments=tuple(builder.segments),
    )
    clock = Clock()
    session = EditingSession(lesson, challenge=ChallengeOptions("bomb"), clock_ns=clock)
    session.submit(KeyToken("char", "Q"))
    clock.add(100)
    session.check_deadline()
    assert session.recovery_marks[0].row == 2
    if second_auto:
        clock.add(100)
        session.check_deadline()
    else:
        finish(session)
    assert session.recovery_marks[0].row == 1
    assert session.failure_examples
    session.release_transient()
    assert not session.failure_examples
    assert session.result is not None and session.result.challenge is not None
    assert session.result.challenge.timeout_count >= 1


def test_recovery_preserves_runtime_viewport_height_and_guide_context() -> None:
    clock = Clock()
    session = session_for(clock)
    session.engine.set_viewport(37, 0)
    session.submit(KeyToken("char", "$"))
    clock.add(100)
    session.check_deadline()
    assert session.engine.state.viewport_rows == 37
    assert session.engine.state.lines == ("n=3", "m=2")
    finish(session)
    assert session.result is not None


def test_pause_request_uses_deadline_time_once_and_excludes_recovery_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    session = session_for(clock)
    session.submit(KeyToken("char", "$"))
    limit = session.segment_limit_seconds
    assert limit is not None
    restore = session.engine.restore

    def slow_restore(snapshot: object) -> None:
        # 복구 중 흘러간 시간은 다음 구간 활성화 이전의 준비 시간이다.
        clock.add(5)
        restore(snapshot)

    monkeypatch.setattr(session.engine, "restore", slow_restore)
    clock.add(limit)
    session.pause()
    assert session.state == SessionState.PAUSED
    assert session.timeout_count == 1
    assert session.elapsed_seconds == limit
    remaining = session.remaining_seconds
    clock.add(100)
    session.resume()
    assert session.remaining_seconds == remaining
    finish(session)
    assert session.result is not None
    assert session.result.elapsed_seconds == limit
    assert decode_result(encode_result(session.result)) == session.result


def test_return_request_at_deadline_settles_current_before_moving_guide() -> None:
    clock = Clock()
    session = session_for(clock)
    play(session, chars("$r3"))
    guard = session.timer_guard
    limit = session.segment_limit_seconds
    assert limit is not None
    clock.add(limit)
    assert not session.return_to_step(0)
    assert session.state == SessionState.COMPLETED
    assert session.timeout_count == 1 and session.direct_count == 1
    assert session.engine.state.lines == session.lesson.goal_lines
    assert not session.check_deadline(guard)
    result = session.result
    assert result is not None and result.stars == 0
    session.return_to_step(0)
    assert session.result is result


def test_recovery_restore_failure_rolls_back_partial_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    session = session_for(clock)
    session.submit(KeyToken("char", "$"))
    original = session.engine.snapshot()
    restore = session.engine.restore
    failed = False

    def partial_failure(snapshot: object) -> None:
        nonlocal failed
        restore(snapshot)
        if not failed:
            failed = True
            raise RuntimeError("test restore failure")

    monkeypatch.setattr(session.engine, "restore", partial_failure)
    clock.add(100)
    assert session.check_deadline()
    assert session.engine.snapshot() == original
    assert session.state == SessionState.PAUSED
    assert session.recovery_error == "test restore failure"
    assert session.auto_repair_count == 0 and session.timeout_count == 1
    assert session.active_segment_index == 0
    session.abort()
    assert session.result is not None and session.result.stars == 0
    assert decode_result(encode_result(session.result)) == session.result


@pytest.mark.parametrize("operation", ["delete", "insert"])
@pytest.mark.parametrize("second_auto", [False, True])
def test_success_marker_tracks_later_row_edits_and_review_without_duplicates(
    operation: str, second_auto: bool
) -> None:
    initial = EditorState(("remove me", "keep me", "n=1", "tail"))
    builder = GuideBuilder(initial, SUPPORTED_COMMANDS)
    builder.navigate(2, 2)
    builder.record(chars("r2"), "숫자 교체")
    builder.finish_segment(0, 2)
    second_start = len(builder.steps)
    builder.navigate(0, None)
    if operation == "delete":
        builder.record(chars("dd"), "앞의 줄 삭제")
        goal = ("keep me", "n=2", "tail!")
        moved_row = 1
    else:
        builder.record(chars("Onew row") + (ESC,), "앞의 줄 삽입")
        goal = ("new row", "remove me", "keep me", "n=2", "tail!")
        moved_row = 3
    builder.finish_segment(second_start, 0)
    third_start = len(builder.steps)
    builder.navigate(len(goal) - 1, None)
    builder.record(chars("A!") + (ESC,), "마지막 줄에 표식 추가")
    builder.finish_segment(third_start, len(goal) - 1)
    baseline = tuple(key for step in builder.steps for key in step.keys)
    lesson = EditLesson(
        1,
        1,
        "success_marker_test",
        "성공 표식 이동",
        "수정·복습의 표식 유지",
        initial,
        goal,
        None,
        SUPPORTED_COMMANDS,
        tuple(builder.steps),
        1,
        baseline,
        len(baseline),
        segments=tuple(builder.segments),
    )
    clock = Clock()
    session = EditingSession(lesson, challenge=ChallengeOptions("bomb"), clock_ns=clock)
    for step in lesson.guide[:second_start]:
        play(session, step.keys)
    assert len(session.success_marks) == 1
    assert session.success_marks[0].row == 2
    if second_auto:
        clock.add(100)
        session.check_deadline()
    else:
        for step in lesson.guide[second_start:third_start]:
            play(session, step.keys)
    first_mark = session.success_marks[0]
    assert first_mark.row == moved_row
    assert session.engine.state.lines[first_mark.row] == "n=2"
    marks_count = len(session.success_marks)
    settled = session.segment_results
    assert session.return_to_step(second_start)
    assert session.success_marks[0].row == 2
    assert session.engine.state.lines[session.success_marks[0].row] == "n=2"
    for step in lesson.guide[second_start:third_start]:
        play(session, step.keys)
    assert len(session.success_marks) == marks_count
    assert session.segment_results == settled
    assert session.success_marks[0].row == moved_row
    assert session.engine.state.lines[moved_row] == "n=2"
    finish(session)
    assert len({mark.segment_id for mark in session.success_marks}) == len(
        session.success_marks
    )
    assert session.result is not None
    assert decode_result(encode_result(session.result)) == session.result
