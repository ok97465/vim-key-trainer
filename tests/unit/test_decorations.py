"""반복 풀이·부분 실패는 꾸미기 해금을 중복 지급하지 않는다."""

# Standard library imports
from dataclasses import replace

# Local imports
from vim_key_trainer.content.edit_loader import get_edit_lesson
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.decorations import summarize_decorations
from vim_key_trainer.domain.preferences import AppearanceSettings
from vim_key_trainer.domain.sessions import EditingSessionResult
from vim_key_trainer.services.edit_session import EditingSession


def _complete(lesson_id: str) -> EditingSessionResult:
    lesson = get_edit_lesson(lesson_id)
    session = EditingSession(lesson, clock_ns=lambda: 0)
    for token in lesson.baseline:
        session.submit(token)
    assert session.result is not None
    return session.result


def test_unlocks_require_different_completed_lessons() -> None:
    first = _complete("editing_numbers")
    second = _complete("editing_delete_line")
    third = _complete("editing_delete_word")
    repeated = replace(first, attempt_id="different-attempt")
    progress = summarize_decorations((first, first, repeated, second))
    assert progress.completed_lessons == 2
    assert not progress.allows("mascot", "cat")
    progress = summarize_decorations((first, repeated, second, third))
    assert progress.completed_lessons == 3
    assert progress.allows("mascot", "cat")
    assert progress.allows("stamp", "star")
    assert not progress.allows("stamp", "flower")
    locked = AppearanceSettings("cat", "peach", "flower", False)
    assert progress.effective(locked) == replace(locked, stamp="check")


def test_repaired_document_and_revenge_do_not_unlock() -> None:
    now = 0
    lesson = get_edit_lesson("editing_numbers")
    session = EditingSession(
        lesson, challenge=ChallengeOptions("bomb"), clock_ns=lambda: now
    )
    session.submit(lesson.baseline[0])
    now = 10**15
    assert session.check_deadline()
    assert session.result is not None
    assert summarize_decorations((session.result,)).completed_lessons == 0
    revenge = session.create_revenge()
    while revenge.expected_token is not None:
        revenge.submit(revenge.expected_token)
    assert revenge.result is not None
    assert (
        summarize_decorations((session.result, revenge.result)).completed_lessons == 0
    )
