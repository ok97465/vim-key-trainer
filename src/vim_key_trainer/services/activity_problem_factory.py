"""네트워크 없이 재현하는 일일 미션과 독립된 세 기술 보스 문서."""

# Standard library imports
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from random import Random
from zoneinfo import ZoneInfo

# Local imports
from vim_key_trainer.content.edit_loader import validate_edit_replay
from vim_key_trainer.domain.activities import (
    ACTIVITY_RULE_VERSION,
    ActivitySpec,
    BonusObjective,
    daily_seed,
)
from vim_key_trainer.domain.edit_builder import GuideBuilder
from vim_key_trainer.domain.edit_templates import ESC, characters
from vim_key_trainer.domain.editing import EditLesson, EditPracticeSpec
from vim_key_trainer.domain.keys import KeyToken
from vim_key_trainer.domain.practice_words import PRACTICE_WORDS
from vim_key_trainer.engine import SUPPORTED_COMMANDS, EditorState
from vim_key_trainer.services.edit_problem_factory import create_edit_problem


def create_daily_problem(
    profile_id: str = "editing_compound",
    *,
    today: Callable[[], date] | None = None,
    timezone_name: str | None = None,
    objectives: tuple[BonusObjective, ...] = (),
) -> EditLesson:
    """호출 시의 로컬 날짜를 한 번 고정한다. 진행 중 자정이 지나도 바뀌지 않는다."""
    local_now = datetime.now().astimezone()
    if timezone_name is not None:
        local_now = datetime.now(ZoneInfo(timezone_name))
    else:
        timezone_name = str(local_now.tzinfo)
    local_date = (today() if today is not None else local_now.date()).isoformat()
    lines = {"code_python": 360, "code_cpp": 360, "code_json": 60}.get(profile_id, 24)
    spec = ActivitySpec(
        "daily",
        ACTIVITY_RULE_VERSION,
        profile_id,
        daily_seed(profile_id, local_date, timezone_name),
        lines,
        local_date,
        timezone_name,
        objectives,
    )
    return create_activity_problem(spec)


def create_boss_problem(
    seed: int,
    *,
    objectives: tuple[BonusObjective, ...] = (),
) -> EditLesson:
    return create_activity_problem(
        ActivitySpec(
            "boss",
            ACTIVITY_RULE_VERSION,
            "editing_compound",
            seed,
            18,
            objectives=objectives,
        )
    )


def create_activity_problem(spec: ActivitySpec) -> EditLesson:
    """저장 기록에서도 원시 입력 없이 같은 조건으로 정답·수정 예를 재구성한다."""
    if spec.kind == "daily":
        if spec.profile_id == "editing_undo":
            raise ValueError(
                "오늘의 미션에는 문서를 실제로 수정하는 유형을 선택하세요."
            )
        lesson = create_edit_problem(
            EditPracticeSpec(
                spec.profile_id,
                spec.seed,
                spec.document_lines,
            )
        )
        lesson = replace(
            lesson,
            title=f"오늘의 미션 · {spec.local_date}",
            description=(
                f"{spec.timezone} · 오늘의 고정 문제. 연속 출석 불이익 없이 "
                "언제든 같은 조건으로 다시 도전할 수 있어요."
            ),
            activity=spec,
        )
        return lesson
    lesson = _boss_lesson(spec)
    validate_edit_replay(lesson)
    return lesson


def _boss_lesson(spec: ActivitySpec) -> EditLesson:
    rng = Random(spec.seed)
    names = rng.sample(PRACTICE_WORDS, 4)
    initial_value = rng.randrange(2, 7)
    increase = rng.randrange(1, 4)
    title = rng.choice(("별빛 관측소", "달빛 우체국", "구름 도서관"))
    initial_lines = (
        "# Observatory dispatch",
        "# Restore three systems for tonight.",
        "",
        f"station = '{names[0]}'",
        f"retry_limit = {initial_value}",
        "window = 'evening'",
        "",
        f"operator = '{names[1]}'",
        'status = "sleeping"',
        "signal = 'quiet'",
        "",
        f"route = '{names[2]}'",
        f"cargo = '{names[3]}'",
        "delivery = 'pending'",
        "",
        "# End of dispatch",
        "",
        "ready = True",
    )
    goal = list(initial_lines)
    goal[4] = f"retry_limit = {initial_value + increase}"
    goal[8] = 'status = "ready"'
    goal[13] += " # checked"
    builder = GuideBuilder(EditorState(initial_lines), SUPPORTED_COMMANDS)
    builder.navigate(4, initial_lines[4].index(str(initial_value)))
    keys = characters(str(increase)) if increase > 1 else ()
    builder.record(
        keys + (KeyToken("chord", "ctrl+a"),), "Control+A로 재시도 값을 올립니다."
    )
    builder.finish_segment(0, 4)
    start = len(builder.steps)
    builder.navigate(8, initial_lines[8].index("sleeping"))
    builder.record(characters('ci"ready') + (ESC,), "따옴표 안을 ready로 바꿉니다.")
    builder.finish_segment(start, 8)
    start = len(builder.steps)
    builder.navigate(13, None)
    builder.record(
        characters("A # checked") + (ESC,), "배송 행 끝에 확인 메모를 붙입니다."
    )
    builder.finish_segment(start, 13)
    baseline = tuple(key for step in builder.steps for key in step.keys)
    return EditLesson(
        schema_version=1,
        content_version=ACTIVITY_RULE_VERSION,
        id="boss_observatory",
        title=f"보스 문서 · {title}",
        description="숫자 증감·따옴표 객체·메모 추가의 세 기술로 작업실을 복구하세요.",
        initial=EditorState(initial_lines),
        goal_lines=tuple(goal),
        goal_cursor=None,
        allowed_commands=SUPPORTED_COMMANDS,
        guide=tuple(builder.steps),
        baseline_version=ACTIVITY_RULE_VERSION,
        baseline=baseline,
        baseline_keys=len(baseline),
        generator_version=ACTIVITY_RULE_VERSION,
        segments=tuple(builder.segments),
        activity=spec,
    )
