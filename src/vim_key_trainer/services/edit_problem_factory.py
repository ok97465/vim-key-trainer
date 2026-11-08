"""문제 생성과 재생 검증을 묶는 Qt 독립 서비스 경계."""

# Local imports
from vim_key_trainer.content.code_corpus import load_code_sources
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.edit_generator import (
    edit_generator_version,
    generate_edit_lesson,
    get_edit_profile,
)
from vim_key_trainer.domain.editing import EditLesson, EditPracticeSpec


def create_edit_problem(spec: EditPracticeSpec) -> EditLesson:
    """요청 조건과 가이드·기준 풀이가 일치하는 문제만 세션에 전달한다."""
    profile = get_edit_profile(spec.profile_id)
    sources = load_code_sources() if profile.language in {"python", "cpp"} else ()
    lesson = (
        generate_edit_lesson(spec, code_sources=sources)
        if sources
        else generate_edit_lesson(spec)
    )
    if (
        lesson.id != spec.profile_id
        or lesson.practice_spec != spec
        or lesson.generator_version != edit_generator_version(profile, spec)
        or lesson.content_version != profile.content_version
        or len(lesson.initial.lines) != spec.document_lines
    ):
        raise ValueError("생성된 편집 문제의 재현 조건이 요청과 다릅니다.")
    if sources:
        excerpt = lesson.code_excerpt
        original = next(
            (entry for entry in sources if excerpt and entry.source == excerpt.source),
            None,
        )
        if (
            excerpt is None
            or original is None
            or excerpt.source.language != profile.language
            or (
                spec.code_source_id is not None
                and excerpt.source.id != spec.code_source_id
            )
            or excerpt.start_line < excerpt.source.excerpt_start
            or excerpt.end_line > excerpt.source.excerpt_end
            or excerpt.lines != lesson.goal_lines
            or excerpt.lines
            != original.lines[
                excerpt.start_line - excerpt.source.excerpt_start : excerpt.end_line
                - excerpt.source.excerpt_start
                + 1
            ]
        ):
            raise ValueError("생성된 코드의 원문·발췌 범위가 검증한 출처와 다릅니다.")
    validate_edit_replay(lesson)
    return lesson
