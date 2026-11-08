"""오늘의 미션·보스·선택 목표의 시작 조건. 날짜와 난수는 외부에서 확정한다."""

# Standard library imports
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

ActivityKind = Literal["daily", "boss"]
BonusObjective = Literal["no_hints", "baseline_keys", "all_direct"]
ACTIVITY_RULE_VERSION = 1
BONUS_RULE_VERSION = 1
BONUS_POINTS: dict[BonusObjective, int] = {
    "no_hints": 200,
    "baseline_keys": 300,
    "all_direct": 500,
}
BONUS_TITLES: dict[BonusObjective, str] = {
    "no_hints": "추가 힌트 없이 해결",
    "baseline_keys": "기준 입력 수 이내",
    "all_direct": "전 구간 직접 해체",
}


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    kind: ActivityKind
    version: int
    profile_id: str
    seed: int
    document_lines: int = 24
    local_date: str | None = None
    timezone: str | None = None
    objectives: tuple[BonusObjective, ...] = ()

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"daily", "boss"}:
            raise ValueError("지원하지 않는 미션 종류입니다.")
        if type(self.version) is not int or self.version != ACTIVITY_RULE_VERSION:
            raise ValueError("지원하지 않는 미션 규칙 버전입니다.")
        if (
            type(self.profile_id) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]*", self.profile_id) is None
        ):
            raise ValueError("미션 연습 유형이 올바르지 않습니다.")
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("미션 seed 범위가 올바르지 않습니다.")
        if type(self.document_lines) is not int or self.document_lines < 1:
            raise ValueError("미션 문서 길이가 올바르지 않습니다.")
        if (
            type(self.objectives) is not tuple
            or any(
                type(objective) is not str or objective not in BONUS_POINTS
                for objective in self.objectives
            )
            or len(set(self.objectives)) != len(self.objectives)
        ):
            raise ValueError("선택 목표가 잘못되었거나 중복되었습니다.")
        if self.kind == "daily":
            if (
                type(self.local_date) is not str
                or date.fromisoformat(self.local_date).isoformat() != self.local_date
            ):
                raise ValueError("오늘의 미션 날짜가 올바르지 않습니다.")
            if (
                type(self.timezone) is not str
                or not self.timezone.strip()
                or len(self.timezone) > 100
            ):
                raise ValueError("오늘의 미션 시간대가 올바르지 않습니다.")
            expected = daily_seed(self.profile_id, self.local_date, self.timezone)
            if expected != self.seed:
                raise ValueError("오늘의 미션 seed가 날짜·시간대·규칙과 다릅니다.")
        elif (
            self.local_date is not None
            or self.timezone is not None
            or self.profile_id != "editing_compound"
            or self.document_lines != 18
        ):
            raise ValueError("보스 미션의 조건이 올바르지 않습니다.")

    def reward_key(self) -> tuple[object, ...]:
        """일일 미션은 같은 날 반복해도 새 보상을 만들지 않는다."""
        if self.kind == "daily":
            return (
                self.kind,
                self.version,
                self.profile_id,
                self.local_date,
                self.timezone,
            )
        # 선택 목표는 원문을 바꾸지 않으므로 같은 seed의 보상을 재발급하지 않는다.
        return (
            self.kind,
            self.version,
            self.profile_id,
            self.seed,
            self.document_lines,
        )


@dataclass(frozen=True, slots=True)
class BonusObjectiveResult:
    id: BonusObjective
    achieved: bool


def daily_seed(profile_id: str, local_date: str, timezone: str) -> int:
    value = f"daily:{ACTIVITY_RULE_VERSION}:{profile_id}:{local_date}:{timezone}"
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:4], "big")


def evaluate_objectives(
    objectives: tuple[BonusObjective, ...],
    *,
    eligible: bool,
    extra_hints: int,
    key_count: int,
    baseline_keys: int,
    efficiency_eligible: bool,
    all_direct: bool,
) -> tuple[BonusObjectiveResult, ...]:
    conditions = {
        "no_hints": extra_hints == 0,
        "baseline_keys": efficiency_eligible and key_count <= baseline_keys,
        "all_direct": all_direct,
    }
    return tuple(
        BonusObjectiveResult(objective, eligible and conditions[objective])
        for objective in objectives
    )
