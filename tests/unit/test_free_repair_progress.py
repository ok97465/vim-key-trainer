"""자유 복구의 순서 독립성·좌표·중복 억제를 실제 문서 상태로 검증한다."""

# Standard library imports
from dataclasses import replace

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.document_display import compare_documents
from vim_key_trainer.domain.free_repair_progress import (
    FreeRepairProgress,
    FreeRepairSnapshot,
)
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.engine import EditEngine, EditorState


def _observe(tracker: FreeRepairProgress, engine: EditEngine) -> FreeRepairSnapshot:
    before = engine.snapshot()
    snapshot = tracker.update(engine.state)
    assert engine.snapshot() == before
    return snapshot


def _type(
    tracker: FreeRepairProgress, engine: EditEngine, keys: str
) -> FreeRepairSnapshot:
    snapshot = _observe(tracker, engine)
    for key in keys:
        assert engine.submit(KeyToken("char", key)).accepted
        snapshot = _observe(tracker, engine)
    return snapshot


def test_free_repairs_follow_document_changes_in_any_order() -> None:
    initial = ("alpha", "bravo")
    goal = ("Alpha", "Bravo")
    tracker = FreeRepairProgress(initial, goal)
    engine = EditEngine(EditorState(initial))
    second = _type(tracker, engine, "j~")
    assert (second.total, second.solved, second.first_solved) == (2, 1, 1)
    assert len(second.events) == 1 and second.events[0].row == 1
    assert second.events[0].old_text == "bravo"
    first = _type(tracker, engine, "gg~")
    assert (first.solved, first.first_solved, first.remaining_changes) == (2, 2, 0)
    assert len(first.events) == 1 and first.events[0].row == 0
    assert first.events[0].id != second.events[0].id
    assert engine.state.lines == goal


def test_two_damaged_words_on_one_line_are_independent_targets() -> None:
    tracker = FreeRepairProgress(("alpha alpha",), ("Alpha Alpha",))
    first = tracker.update(EditorState(("Alpha alpha",)))
    assert first.total == 2 and first.solved == 1
    assert first.events[0].column == 0
    second = tracker.update(EditorState(("Alpha Alpha",)))
    assert second.solved == second.first_solved == 2
    assert len(second.events) == 1 and second.events[0].column == 6


def test_insert_session_waits_for_escape_before_first_success() -> None:
    initial, goal = ("alpha", "bravo"), ("Alpha", "Bravo")
    tracker = FreeRepairProgress(initial, goal)
    engine = EditEngine(EditorState(initial))
    inserting = _type(tracker, engine, "sA")
    assert engine.state.mode == "insert"
    assert inserting.solved == 1 and inserting.first_solved == 0
    assert not inserting.events
    engine.submit(KeyToken("special", "esc"))
    finished = _observe(tracker, engine)
    assert finished.first_solved == 1 and len(finished.events) == 1
    assert not _observe(tracker, engine).events


def test_undo_and_redo_update_marks_without_replaying_success() -> None:
    initial, goal = ("alpha", "bravo"), ("Alpha", "Bravo")
    tracker = FreeRepairProgress(initial, goal)
    engine = EditEngine(EditorState(initial))
    first = _type(tracker, engine, "~")
    assert first.solved == first.first_solved == 1
    reverted = _type(tracker, engine, "u")
    assert reverted.solved == 0 and reverted.first_solved == 1
    assert not reverted.marks and not reverted.events
    assert engine.submit(KeyToken("chord", "ctrl+r")).accepted
    restored = _observe(tracker, engine)
    assert restored.solved == restored.first_solved == 1
    assert restored.marks and not restored.events
    moved = _type(tracker, engine, "jklh")
    assert not moved.events and moved.first_solved == 1


def test_new_line_before_a_repaired_target_remaps_its_mark() -> None:
    tracker = FreeRepairProgress(("alpha", "bravo"), ("Alpha", "Bravo"))
    first = tracker.update(EditorState(("extra", "Alpha", "bravo")))
    assert first.solved == 1 and first.remaining_changes == 2
    assert first.events[0].row == 1 and first.events[0].column == 0
    assert first.marks[0][0] == 1
    shifted = tracker.update(EditorState(("Alpha", "bravo")))
    assert shifted.solved == 1 and shifted.marks[0][0] == 0
    assert not shifted.events


@pytest.mark.parametrize(
    ("initial", "goal", "wrong"),
    [
        (("head", "extra", "tail"), ("head", "tail"), ("head", "other", "tail")),
        (("head", "tail", "extra"), ("head", "tail"), ("head", "tail", "other")),
        (("abcX",), ("abc",), ("abcY",)),
        (("ac",), ("abc",), ("axc",)),
        (("head", "tail"), ("head", "", "tail"), ("head", "wrong", "tail")),
        (("head", ""), ("head",), ("head", "wrong")),
        (("head",), ("head", ""), ("head", "wrong")),
        (("",), ("alpha",), ("wrong",)),
    ],
)
def test_insert_delete_boundaries_and_eof_require_the_goal(
    initial: tuple[str, ...], goal: tuple[str, ...], wrong: tuple[str, ...]
) -> None:
    tracker = FreeRepairProgress(initial, goal)
    unchanged = tracker.update(EditorState(initial))
    assert unchanged.solved == 0 and not unchanged.events
    incorrect = tracker.update(EditorState(wrong))
    assert incorrect.solved == 0 and not incorrect.events
    repaired = tracker.update(EditorState(goal))
    assert repaired.total == repaired.solved == repaired.first_solved
    assert repaired.remaining_changes == 0 and repaired.events
    assert all(0 <= event.row < len(goal) for event in repaired.events)


@pytest.mark.parametrize(
    "initial",
    [("bad", "same", "tail"), ("same", "bad", "tail")],
)
def test_deleting_one_of_repeated_rows_does_not_fake_a_repair(
    initial: tuple[str, ...],
) -> None:
    goal = ("same", "same", "tail")
    tracker = FreeRepairProgress(initial, goal)
    missing = tracker.update(EditorState(("same", "tail")))
    assert missing.solved == missing.first_solved == 0
    assert not missing.events
    corrected = tracker.update(EditorState(goal))
    assert corrected.solved == corrected.total and corrected.events


def test_one_substitution_can_resolve_several_repeated_rows_together() -> None:
    initial = ("alpha", "alpha", "bravo")
    goal = ("Alpha", "Alpha", "Bravo")
    tracker = FreeRepairProgress(initial, goal)
    partial = tracker.update(EditorState(("Alpha", "Alpha", "bravo")))
    assert (partial.total, partial.solved, partial.first_solved) == (3, 2, 2)
    assert [event.row for event in partial.events] == [0, 1]
    assert [event.first_solved_total for event in partial.events] == [1, 2]
    assert not tracker.update(EditorState(("Alpha", "Alpha", "bravo"))).events


def test_original_targets_and_new_damage_do_not_imply_full_completion() -> None:
    tracker = FreeRepairProgress(("alpha", "unchanged"), ("Alpha", "unchanged"))
    state = EditorState(("Alpha", "new damage"))
    snapshot = tracker.update(state)
    assert snapshot.total == snapshot.solved == 1
    assert snapshot.remaining_changes > 0
    assert state.lines != ("Alpha", "unchanged")


def test_pending_and_suppressed_refreshes_do_not_award_new_events() -> None:
    tracker = FreeRepairProgress(("alpha",), ("Alpha",))
    pending = EditorState(("Alpha",), pending="r")
    assert not tracker.update(pending).events
    assert tracker.update(pending).first_solved == 0
    stable = replace(pending, pending="")
    suppressed = tracker.update(stable, celebrate=False)
    assert suppressed.solved == 1 and suppressed.first_solved == 0
    assert not suppressed.events
    # 숨은 화면의 갱신 후 커서만 이동해도 과거 성공을 뒤늦게 재생하지 않는다.
    assert not tracker.update(replace(stable, column=1)).events
    assert tracker.update(stable).first_solved == 0


def test_supplied_diff_is_reused_and_initially_equal_document_has_no_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial, goal = ("alpha",), ("Alpha",)
    tracker = FreeRepairProgress(initial, goal)
    diff = compare_documents(goal, goal)

    def unexpected(*args: object) -> None:
        raise AssertionError("화면에서 이미 계산한 diff를 다시 계산했습니다.")

    monkeypatch.setattr(
        "vim_key_trainer.domain.free_repair_progress.compare_documents", unexpected
    )
    snapshot = tracker.update(EditorState(goal), diff=diff)
    assert snapshot.solved == snapshot.first_solved == 1


def test_suppressed_success_stays_consumed_during_later_edits_and_redo() -> None:
    tracker = FreeRepairProgress(("alpha", "bravo"), ("Alpha", "Bravo"))
    hidden = tracker.update(EditorState(("Alpha", "bravo")), celebrate=False)
    assert hidden.solved == 1 and hidden.first_solved == 0 and not hidden.events

    visible = tracker.update(EditorState(("Alpha", "Bravo")))
    assert visible.solved == 2 and visible.first_solved == 1
    assert len(visible.events) == 1 and visible.events[0].row == 1
    assert visible.events[0].first_solved_total == 1

    tracker.update(EditorState(("alpha", "Bravo")))
    restored = tracker.update(EditorState(("Alpha", "Bravo")))
    assert restored.solved == 2 and restored.first_solved == 1
    assert not restored.events


def test_unchanged_document_has_no_synthetic_rewards() -> None:
    tracker = FreeRepairProgress(("same",), ("same",))
    snapshot = tracker.update(EditorState(("same",)))
    assert snapshot.total == snapshot.solved == snapshot.first_solved == 0
    assert not snapshot.events and not snapshot.marks


@pytest.mark.parametrize(
    ("initial", "goal", "missing"),
    [
        (("abcX",), ("abc",), ("",)),
        (("abcX",), ("abc",), ("ab",)),
        (("Xabc",), ("abc",), ("bc",)),
        (("head", "extra"), ("head",), ("",)),
        (("abcdclient",), ("client",), ("c",)),
        (("abcdclient",), ("client",), ("cl",)),
        (('abcd"client"',), ('"client"',), ('""',)),
        (
            ("head", "extra", "  client"),
            ("head", "  client"),
            ("head", "  c"),
        ),
    ],
)
def test_delete_target_requires_its_surviving_goal_boundary(
    initial: tuple[str, ...], goal: tuple[str, ...], missing: tuple[str, ...]
) -> None:
    tracker = FreeRepairProgress(initial, goal)
    erased = tracker.update(EditorState(missing))
    assert erased.solved == erased.first_solved == 0
    assert not erased.events and erased.remaining_changes > 0
    repaired = tracker.update(EditorState(goal))
    assert repaired.solved == repaired.first_solved == repaired.total
    assert repaired.events and repaired.remaining_changes == 0


def test_original_fragment_column_survives_a_longer_repaired_prefix() -> None:
    initial = ("x ... bad",)
    goal = ("supercalifragilistic ... GOOD",)
    tracker = FreeRepairProgress(initial, goal)
    prefix = tracker.update(EditorState(("supercalifragilistic ... bad",)))
    assert prefix.solved == prefix.first_solved == 1
    fixed = tracker.update(EditorState(goal))
    assert len(fixed.events) == 1
    event = fixed.events[0]
    assert event.column == goal[0].index("GOOD")
    assert event.source_column == initial[0].index("bad")
    assert event.source_column is not None
    assert event.old_text[event.source_column :] == "bad"


def test_dw_cannot_award_a_repair_after_deleting_the_required_word() -> None:
    tracker = FreeRepairProgress(("abcdclient",), ("client",))
    engine = EditEngine(EditorState(("abcdclient",)))
    erased = _type(tracker, engine, "dw")
    assert engine.state.lines == ("",)
    assert erased.solved == erased.first_solved == 0
    assert not erased.events and not erased.marks
    assert erased.remaining_changes > 0
    _type(tracker, engine, "iclient")
    engine.submit(KeyToken("special", "esc"))
    fixed = _observe(tracker, engine)
    assert fixed.solved == fixed.first_solved == fixed.total == 1
    assert fixed.events and fixed.marks
