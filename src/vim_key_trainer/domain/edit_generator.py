"""분야·문서 길이·seed로 긴 편집 과제를 생성한다.

문서/수정 레시피와 가이드 실행을 분리한다. 목표는 레시피가 명시하고,
동일한 엔진에서 실제 키를 재생해 각 가이드 단계의 기대 상태를 기록한다.
"""

# Standard library imports
from dataclasses import dataclass
from random import Random

# Local imports
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import build_document_plan
from vim_key_trainer.domain.editing import (
    EDIT_DOCUMENT_LENGTHS as EDIT_DOCUMENT_LENGTHS,
)
from vim_key_trainer.domain.editing import (
    EditLesson,
    EditPracticeSpec,
)
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState

EDIT_GENERATOR_VERSION = 7


@dataclass(frozen=True, slots=True)
class EditProfile:
    id: str
    title: str
    description: str
    free_enabled: bool = True
    content_version: int = 8


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


def list_edit_profiles() -> tuple[EditProfile, ...]:
    return _PROFILES


def get_edit_profile(profile_id: str) -> EditProfile:
    for profile in _PROFILES:
        if profile.id == profile_id:
            return profile
    raise ValueError(f"알 수 없는 문서 수정 유형입니다: {profile_id}")


def generate_edit_lesson(spec: EditPracticeSpec) -> EditLesson:
    profile = get_edit_profile(spec.profile_id)
    plan = build_document_plan(
        profile.id, spec.document_lines, Random(spec.seed), spec.technique_weights
    )
    initial = EditorState(plan.lines)
    # 유형은 가이드의 학습 기술을 정한다. 자유 풀이는 다른 유효한 명령을 막지 않는다.
    allowed = SUPPORTED_COMMANDS
    guide = GuideBuilder(initial, allowed)
    for recipe in plan.recipes:
        for index, action in enumerate(recipe.actions):
            if index == 0 or action.column is not None:
                guide.navigate(recipe.row, action.column)
            guide.record(action.keys, action.text)
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
        baseline_version=7,
        baseline=baseline,
        baseline_keys=len(baseline),
        free_enabled=profile.free_enabled,
        practice_spec=spec,
        generator_version=EDIT_GENERATOR_VERSION,
    )
