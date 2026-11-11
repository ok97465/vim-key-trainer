"""자유풀이의 부분 복구가 실제 키·undo·시간·공식 결과와 독립적인지 검증한다."""

# Standard library imports
from dataclasses import dataclass, replace

# Third party imports
import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from pytestqt.qtbot import QtBot

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditLesson, GuideStep
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.domain.sessions import SessionState
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_session import EditingSession
from vim_key_trainer.services.result_repository import MemoryResultRepository
from vim_key_trainer.ui.edit_practice import EditPracticePage
from vim_key_trainer.ui.main_window import MainWindow

from ._support import press_key


@dataclass
class Clock:
    now: int = 0

    def __call__(self) -> int:
        return self.now


def _lesson(*, repeated: bool = False) -> EditLesson:
    initial = ("alpha", "alpha", "bravo") if repeated else ("alpha", "bravo", "charlie")
    goal = ("Alpha", "Alpha", "Bravo") if repeated else ("Alpha", "Bravo", "Charlie")
    steps: list[GuideStep] = []
    lines = list(initial)
    baseline: tuple[KeyToken, ...] = ()
    for row in range(3):
        keys = tuple(
            KeyToken("char", char)
            for char in ("" if row == 0 else "j") + "r" + goal[row][0]
        )
        lines[row] = goal[row]
        steps.append(GuideStep(keys, EditorState(tuple(lines), row, 0), "첫 글자 수정"))
        baseline += keys
    return replace(
        get_edit_lesson("editing_numbers"),
        initial=EditorState(initial),
        goal_lines=goal,
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=tuple(steps),
        baseline=baseline,
        baseline_keys=len(baseline),
        segments=(),
    )


def _page(
    qtbot: QtBot,
    *,
    bomb: bool = False,
    repeated: bool = False,
    settings: PresentationSettings | None = None,
    lesson: EditLesson | None = None,
) -> tuple[EditPracticePage, EditingSession, Clock]:
    clock = Clock()
    lesson = lesson or _lesson(repeated=repeated)
    session = EditingSession(
        lesson,
        "free",
        challenge=ChallengeOptions("bomb" if bomb else "normal", auto_repair=False),
        clock_ns=clock,
    )
    page = EditPracticePage(MemoryResultRepository(), presentation=settings)
    qtbot.addWidget(page)
    page.resize(1100, 850)
    page.show()
    page.activateWindow()
    page.prepare(lesson, "free", prepared_session=session)
    page.start_practice()
    qtbot.waitUntil(page.practice_input.hasFocus)
    return page, session, clock


@pytest.mark.parametrize("bomb", [False, True])
def test_out_of_order_alternate_solution_undo_redo_and_sound_once(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, bomb: bool
) -> None:
    page, session, _ = _page(qtbot, bomb=bomb)
    cues: list[str] = []
    audio = page.challenge_status.audio if bomb else page.result_audio
    monkeypatch.setattr(audio, "play", lambda cue, **kwargs: cues.append(cue))
    # 가이드의 rA 대신 두 번째 위치를 ~로 먼저 해결한다.
    qtbot.keyClicks(page.practice_input, "j~")
    snapshot = page._free_snapshot
    assert snapshot is not None and snapshot.solved == snapshot.first_solved == 1
    assert len(snapshot.events) == 1 and snapshot.events[0].row == 1
    assert page.practice_input.success_marks
    assert page.repair_effects.isVisible()
    assert page.free_repair_status.isVisible()
    assert session.direct_count == 0 and session.chain == 0
    assert session.accuracy is None and session.combo is None
    assert session.elapsed_seconds == 0 and session.key_count == 2
    assert cues == ["success"]
    page._refresh()
    assert page._free_snapshot is not None and not page._free_snapshot.events
    assert cues == ["success"]
    qtbot.keyClicks(page.practice_input, "u")
    assert page._free_snapshot is not None and page._free_snapshot.solved == 0
    assert not page.practice_input.success_marks
    press_key(page.practice_input, qtbot, KeyToken("chord", "ctrl+r"))
    snapshot = page._free_snapshot
    assert snapshot is not None and snapshot.solved == snapshot.first_solved == 1
    assert not snapshot.events
    assert cues == ["success"]
    assert page.practice_input.hasFocus()
    assert not page.repository.results
    page.abort()


def test_deleting_required_suffix_never_looks_like_a_success(qtbot: QtBot) -> None:
    first = tuple(KeyToken("char", char) for char in "4x")
    second = tuple(KeyToken("char", char) for char in "j~")
    lesson = replace(
        _lesson(),
        initial=EditorState(("abcdclient", "tail")),
        goal_lines=("client", "Tail"),
        guide=(
            GuideStep(first, EditorState(("client", "tail")), "접두부만 삭제"),
            GuideStep(second, EditorState(("client", "Tail"), 1, 1), "대문자 수정"),
        ),
        baseline=first + second,
        baseline_keys=len(first + second),
    )
    page, session, _ = _page(qtbot, lesson=lesson)
    qtbot.keyClicks(page.practice_input, "dw")
    assert session.engine.state.lines == ("", "tail")
    snapshot = page._free_snapshot
    assert snapshot is not None and snapshot.solved == snapshot.first_solved == 0
    assert not snapshot.events and not page.practice_input.success_marks
    assert not page.repair_effects.isVisible()
    qtbot.keyClicks(page.practice_input, "icl")
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Escape)
    assert page._free_snapshot is not None and page._free_snapshot.solved == 0
    assert not page.repair_effects.isVisible()
    qtbot.keyClicks(page.practice_input, "Aient")
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Escape)
    assert session.engine.state.lines[0] == "client"
    assert page._free_snapshot is not None and page._free_snapshot.solved == 1
    assert len(page._free_snapshot.events) == 1
    assert page.repair_effects.isVisible()
    assert session.state == SessionState.RUNNING
    page.abort()


def test_insert_text_only_celebrates_after_returning_to_normal(qtbot: QtBot) -> None:
    page, session, _ = _page(qtbot)
    qtbot.keyClicks(page.practice_input, "sA")
    assert session.engine.state.mode == "insert"
    assert session.engine.state.lines[0] == "Alpha"
    assert page._free_snapshot is not None
    assert page._free_snapshot.first_solved == 0
    assert not page._free_snapshot.events
    assert not page.repair_effects.isVisible()
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Escape)
    assert page._free_snapshot is not None and page._free_snapshot.solved == 1
    assert len(page._free_snapshot.events) == 1
    assert page.repair_effects.isVisible()
    assert session.state == SessionState.RUNNING
    assert not page.repository.results
    page.abort()


def test_global_substitution_recognizes_every_restored_place_with_one_sound(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, session, _ = _page(qtbot, repeated=True)
    cues: list[str] = []
    monkeypatch.setattr(
        page.result_audio, "play", lambda cue, **kwargs: cues.append(cue)
    )
    qtbot.keyClicks(page.practice_input, ":%s/alpha/Alpha/g")
    assert page._free_snapshot is not None and not page._free_snapshot.events
    qtbot.keyClick(page.practice_input, Qt.Key.Key_Return)
    snapshot = page._free_snapshot
    assert snapshot is not None and snapshot.solved == snapshot.first_solved == 2
    assert {event.row for event in snapshot.events} == {0, 1}
    assert len(page.practice_input.success_marks) == 2
    assert session.engine.state.lines == ("Alpha", "Alpha", "bravo")
    assert session.state == SessionState.RUNNING
    assert cues == ["success"]
    assert page.practice_input.hasFocus()
    page.abort()


@pytest.mark.parametrize("reduced", [False, True])
def test_effect_settings_pause_and_retry_preserve_and_reset_progress(
    qtbot: QtBot, reduced: bool
) -> None:
    page, session, _ = _page(
        qtbot, settings=PresentationSettings(reduced_motion=reduced)
    )
    qtbot.keyClicks(page.practice_input, "~")
    assert page._free_snapshot is not None and page._free_snapshot.solved == 1
    before = session.engine.snapshot()
    page.configure_effects(PresentationSettings(effects=False, reduced_motion=reduced))
    assert page.free_repair_status.isVisible()
    assert page.repair_effects.isHidden()
    assert session.engine.snapshot() == before
    qtbot.keyClicks(page.practice_input, "j0~")
    assert page._free_snapshot is not None and page._free_snapshot.solved == 2
    page.configure_effects(PresentationSettings(reduced_motion=reduced))
    page._refresh()
    assert not page._free_snapshot.events
    assert page.repair_effects.isHidden()
    page.pause()
    assert session.state == SessionState.PAUSED
    assert page.free_repair_status.animation.state() == QAbstractAnimation.State.Stopped
    page.retry()
    assert page.session is not None and page.session.attempt_id != session.attempt_id
    assert page._free_snapshot is not None
    assert page._free_snapshot.solved == page._free_snapshot.first_solved == 0
    assert not page.practice_input.success_marks
    page.abort()


def test_partial_repair_after_free_timeout_keeps_failure_and_global_timer(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, session, clock = _page(qtbot, bomb=True)
    cues: list[str] = []
    monkeypatch.setattr(
        page.challenge_status.audio, "play", lambda cue, **kwargs: cues.append(cue)
    )
    qtbot.keyClicks(page.practice_input, "l")
    limit = session.remaining_seconds
    assert limit is not None
    clock.now += round(limit * 1_000_000_000)
    page._tick()
    assert session.timeout_count == 1 and session.auto_repair_count == 0
    assert session.state == SessionState.RUNNING
    failure = session.segment_results
    assert page.repair_effects.isHidden()
    assert cues == ["expired"]
    page._refresh()
    page._tick()
    assert cues == ["expired"]
    qtbot.keyClicks(page.practice_input, "j0~")
    assert page._free_snapshot is not None and page._free_snapshot.solved == 1
    assert page.repair_effects.isVisible()
    assert session.segment_results == failure
    assert session.direct_count == 0 and session.remaining_seconds is None
    assert not page.repository.results
    page.abort()


def test_general_free_finale_and_partial_feedback_do_not_change_stored_result(
    qtbot: QtBot,
) -> None:
    page, session, clock = _page(qtbot)
    reference = EditingSession(session.lesson, "free", clock_ns=clock)
    # 순서를 바꾸고 기준 풀이보다 적은 입력으로 완료한다.
    tokens = tuple(KeyToken("char", char) for char in "j~gg~G~")
    for token in tokens:
        clock.now += 80_000_000
        reference.submit(token)
        press_key(page.practice_input, qtbot, token)
    assert session.result is not None and reference.result is not None
    assert replace(session.result, attempt_id=reference.attempt_id) == reference.result
    assert page.result_finale.isVisible()
    assert page.result_finale.result == session.result
    assert page.stack.currentWidget() is page.result_page
    assert len(page.repository.results) == 1
    page.abort()


@pytest.mark.parametrize("reduced", [False, True])
def test_expiration_notice_is_silent_once_and_does_not_block_practice(
    qtbot: QtBot, reduced: bool
) -> None:
    page, session, clock = _page(
        qtbot, bomb=True, settings=PresentationSettings(reduced_motion=reduced)
    )
    qtbot.keyClicks(page.practice_input, "0")
    remaining = session.remaining_seconds
    assert remaining is not None
    clock.now += round(remaining * 1_000_000_000)
    page._tick()
    notice = page.expiration_effect
    assert notice.isVisible()
    assert not page.challenge_status.audio._effects
    assert not page.result_audio._effects
    assert session.timeout_count == 1
    snapshot = session.engine.snapshot()
    verdict = session.segment_results
    if not reduced:
        notice.animation.pause()
        notice.animation.setCurrentTime(450)
    position = notice.animation.currentTime()
    page._tick()
    page._refresh()
    assert notice.animation.currentTime() == position
    assert session.engine.snapshot() == snapshot
    assert session.segment_results == verdict
    assert page.practice_input.hasFocus()
    qtbot.keyClicks(page.practice_input, "j~")
    assert session.key_count == 3
    assert session.engine.state.lines[1] == "Bravo"
    assert notice.isVisible()
    assert page.practice_input.hasFocus()
    page.pause()
    assert notice.isHidden()
    assert not notice.static_timer.isActive()
    page.toggle_pause()
    assert notice.isHidden()
    assert session.timeout_count == 1
    page.retry()
    fresh = page.session
    assert fresh is not None and fresh.attempt_id != session.attempt_id
    assert notice.isHidden()
    page.start_practice()
    qtbot.keyClicks(page.practice_input, "0")
    remaining = fresh.remaining_seconds
    assert remaining is not None
    clock.now += round(remaining * 1_000_000_000)
    page._tick()
    assert notice.isVisible()
    assert fresh.timeout_count == 1
    page.abort()


@pytest.mark.parametrize("suppression", ["pause", "disabled"])
def test_expiration_during_pause_or_disabled_effects_does_not_play_later(
    qtbot: QtBot, suppression: str
) -> None:
    page, session, clock = _page(
        qtbot,
        bomb=True,
        settings=PresentationSettings(effects=suppression != "disabled"),
    )
    qtbot.keyClicks(page.practice_input, "0")
    remaining = session.remaining_seconds
    assert remaining is not None
    clock.now += round(remaining * 1_000_000_000)
    if suppression == "pause":
        page.pause()
        assert page.expiration_effect.isHidden()
        page.toggle_pause()
    else:
        page._tick()
        assert page.expiration_effect.isHidden()
        page.configure_effects(PresentationSettings())
    page._refresh_metrics()
    assert page.expiration_effect.isHidden()
    assert session.timeout_count == 1
    page.abort()


def test_notice_covers_main_window_and_clears_on_result_transition(
    qtbot: QtBot,
) -> None:
    window = MainWindow(MemoryResultRepository())
    qtbot.addWidget(window)
    window.resize(1000, 740)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    lesson = _lesson()
    window.prepare_editing_lesson(lesson)
    page = window.edit_practice
    clock = Clock()
    session = EditingSession(
        lesson,
        "free",
        challenge=ChallengeOptions("bomb", auto_repair=False),
        clock_ns=clock,
    )
    page.prepare(lesson, "free", prepared_session=session)
    page.start_practice()
    qtbot.waitUntil(page.practice_input.hasFocus)
    qtbot.keyClicks(page.practice_input, "0")
    remaining = session.remaining_seconds
    assert remaining is not None
    clock.now += round(remaining * 1_000_000_000)
    page._tick()
    notice = page.expiration_effect
    assert notice.parentWidget() is window
    assert notice.geometry() == window.rect()
    assert notice.isVisible()
    qtbot.keyClicks(page.practice_input, "rAjrBjrC")
    assert session.state == SessionState.COMPLETED
    assert page.stack.currentWidget() is page.result_page
    assert page.isVisible()
    assert notice.isHidden()
    assert notice.animation.state() == QAbstractAnimation.State.Stopped
    assert not notice.static_timer.isActive()
