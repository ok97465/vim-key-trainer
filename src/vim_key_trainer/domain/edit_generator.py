"""분야·문서 길이·seed로 긴 편집 과제를 생성한다.

문서/수정 레시피와 가이드 실행을 분리한다. 목표는 레시피가 명시하고,
동일한 엔진에서 실제 키를 재생해 각 가이드 단계의 기대 상태를 기록한다.
"""

# Standard library imports
from dataclasses import dataclass
from random import Random

# Local imports
from vim_key_trainer.domain.code_edit_templates import (
    CODE_GENERATOR_VERSION,
    build_code_document_plan,
)
from vim_key_trainer.domain.code_samples import CodeSource
from vim_key_trainer.domain.document_types import DocumentLanguage
from vim_key_trainer.domain.edit_builder import GuideBuilder, navigation_keys
from vim_key_trainer.domain.edit_templates import build_document_plan
from vim_key_trainer.domain.editing import (
    CODE_DOCUMENT_LENGTHS,
    EditLesson,
    EditPracticeSpec,
)
from vim_key_trainer.domain.editing import (
    EDIT_DOCUMENT_LENGTHS as EDIT_DOCUMENT_LENGTHS,
)
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState

EDIT_GENERATOR_VERSION = 9
CODE_SOURCE_SELECTION_VERSION = 9


@dataclass(frozen=True, slots=True)
class EditProfile:
    id: str
    title: str
    description: str
    free_enabled: bool = True
    content_version: int = 9
    language: DocumentLanguage = "text"
    document_lengths: tuple[int, ...] = EDIT_DOCUMENT_LENGTHS
    default_document_lines: int = 24


_PROFILES = (
    EditProfile(
        "editing_numbers",
        "숫자·설정값 수정",
        "숫자를 교체하거나 Control+A/X로 증감합니다. 값의 자리 수와 위치가 달라집니다.",
    ),
    EditProfile(
        "editing_delete_line",
        "불필요한 줄 삭제",
        "문서 곳곳의 오래된 줄과 중복된 줄 묶음을 삭제합니다.",
    ),
    EditProfile(
        "editing_delete_word",
        "단어·표식 정리",
        "word·WORD 삭제·변경과 따옴표·괄호 객체로 경로·설정값을 정리합니다.",
    ),
    EditProfile(
        "editing_append",
        "주석·메모 추가",
        "A·o·O로 주석과 새 메모 줄을 추가하고 yy·p로 줄을 복사합니다.",
    ),
    EditProfile(
        "editing_compound",
        "복합 문서 수정",
        "숫자·객체·괄호짝 %·검색·치환·Visual·복사 등 여러 기술을 함께 풉니다.",
    ),
    EditProfile(
        "editing_undo",
        "실행 취소·다시 실행",
        "다양한 변경을 u와 실제 Control+R로 되돌리고 복원합니다.",
        free_enabled=False,
    ),
)


_CODE_PROFILES = (
    EditProfile(
        "code_python",
        "Python Code 수정 연습",
        "들여쓰기·문자열·인자·리스트 객체와 검색·치환으로 Python 코드를 수정합니다.",
        content_version=4,
        language="python",
        document_lengths=CODE_DOCUMENT_LENGTHS["code_python"],
        default_document_lines=360,
    ),
    EditProfile(
        "code_cpp",
        "C++ Code 수정 연습",
        "괄호짝·인자·문자열·구분자와 들여쓰기·검색·치환으로 C++ 코드를 수정합니다.",
        content_version=4,
        language="cpp",
        document_lengths=CODE_DOCUMENT_LENGTHS["code_cpp"],
        default_document_lines=360,
    ),
    EditProfile(
        "code_json",
        "JSON 파일 수정 연습",
        "키·문자열·배열·객체와 숫자 설정·쉼표·들여쓰기를 수정합니다.",
        content_version=3,
        language="json",
        document_lengths=CODE_DOCUMENT_LENGTHS["code_json"],
        default_document_lines=60,
    ),
)


def list_code_edit_profiles() -> tuple[EditProfile, ...]:
    return _CODE_PROFILES


def edit_generator_version(
    profile: EditProfile, spec: EditPracticeSpec | None = None
) -> int:
    if spec is not None and spec.code_source_id is not None:
        return CODE_SOURCE_SELECTION_VERSION
    if profile.id == "code_json":
        return 5
    return (
        CODE_GENERATOR_VERSION if profile.language != "text" else EDIT_GENERATOR_VERSION
    )


def list_edit_profiles() -> tuple[EditProfile, ...]:
    return _PROFILES


def get_edit_profile(profile_id: str) -> EditProfile:
    for profile in _PROFILES + _CODE_PROFILES:
        if profile.id == profile_id:
            return profile
    raise ValueError(f"알 수 없는 문서 수정 유형입니다: {profile_id}")


def generate_edit_lesson(
    spec: EditPracticeSpec, *, code_sources: tuple[CodeSource, ...] = ()
) -> EditLesson:
    profile = get_edit_profile(spec.profile_id)
    is_code = profile.language != "text"
    if spec.code_source_id is not None:
        selected = tuple(
            source for source in code_sources if source.source.id == spec.code_source_id
        )
        if not selected:
            raise ValueError(
                "선택한 코드 원문을 찾을 수 없습니다. 다른 문서를 선택하세요."
            )
        if any(source.source.language != profile.language for source in selected):
            raise ValueError("선택한 코드 원문의 언어가 연습 유형과 다릅니다.")
        code_sources = selected
    if is_code:
        plan = build_code_document_plan(
            profile.id,
            spec.document_lines,
            Random(spec.seed),
            spec.technique_weights,
            code_sources=code_sources,
        )
    else:
        plan = build_document_plan(
            profile.id, spec.document_lines, Random(spec.seed), spec.technique_weights
        )
    initial = EditorState(plan.lines)
    # 유형은 가이드의 학습 기술을 정한다. 자유 풀이는 다른 유효한 명령을 막지 않는다.
    allowed = SUPPORTED_COMMANDS
    guide = GuideBuilder(initial, allowed)
    for recipe in plan.recipes:
        start_step = len(guide.steps)
        for index, action in enumerate(recipe.actions):
            if index == 0 or action.column is not None:
                if is_code:
                    guide.navigate(recipe.row, None)
                    if action.column is not None:
                        current = guide.engine.state
                        local = EditorState(
                            (current.lines[current.row],), column=current.column
                        )
                        moves = navigation_keys(
                            local,
                            0,
                            action.column,
                            allowed - {"/", "?", "G", "gg", "%"},
                        )
                        if moves:
                            guide.record(
                                moves, "줄 안의 식별자·구분자 위치로 이동합니다."
                            )
                else:
                    guide.navigate(recipe.row, action.column)
            guide.record(action.keys, action.text)
        guide.finish_segment(
            start_step, recipe.row, max(recipe.span, len(recipe.replacement))
        )
    if (
        guide.engine.state.lines != plan.goal_lines
        or guide.engine.state.mode != "normal"
        or guide.engine.state.pending
    ):
        raise ValueError("생성한 풀이가 명시한 목표 문서와 일치하지 않습니다.")
    baseline = tuple(key for step in guide.steps for key in step.keys)
    return EditLesson(
        schema_version=1,
        content_version=profile.content_version,
        id=profile.id,
        title=f"{profile.title} · {plan.context_title}",
        description=(
            f"{plan.context_title} {spec.document_lines}줄 · "
            f"{len(plan.recipes)}곳 수정. {profile.description}"
        ),
        initial=initial,
        goal_lines=plan.goal_lines,
        goal_cursor=None,
        allowed_commands=allowed,
        guide=tuple(guide.steps),
        baseline_version=2 if is_code else 7,
        baseline=baseline,
        baseline_keys=len(baseline),
        free_enabled=profile.free_enabled,
        practice_spec=spec,
        generator_version=edit_generator_version(profile, spec),
        code_excerpt=plan.code_excerpt,
        segments=tuple(guide.segments),
    )
