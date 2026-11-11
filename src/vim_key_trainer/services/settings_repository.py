"""버전이 있는 UTF-8 설정 파일. 손상은 초기화하고 저장은 원자적으로 교체한다."""

# Standard library imports
import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

# Third party imports
from platformdirs import user_config_path

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.preferences import AppearanceSettings, PresentationSettings

SETTINGS_VERSION = 2
_MAX_SETTINGS_BYTES = 16_384


@dataclass(frozen=True, slots=True)
class AppSettings:
    challenge: ChallengeOptions = field(default_factory=ChallengeOptions)
    presentation: PresentationSettings = field(default_factory=PresentationSettings)
    font_size: int = 12
    record_rival: bool = False
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    edit_mode: EditMode = "guided"

    def __post_init__(self) -> None:
        if not isinstance(self.challenge, ChallengeOptions) or not isinstance(
            self.presentation, PresentationSettings
        ):
            raise ValueError("설정 데이터 형식이 올바르지 않습니다.")
        if type(self.font_size) is not int or not 10 <= self.font_size <= 30:
            raise ValueError("문서 글씨 크기는 10~30pt여야 합니다.")
        if type(self.record_rival) is not bool:
            raise ValueError("개인 기록 표시는 참/거짓이어야 합니다.")
        if not isinstance(self.appearance, AppearanceSettings):
            raise ValueError("꾸미기 설정이 올바르지 않습니다.")
        if type(self.edit_mode) is not str or self.edit_mode not in {"guided", "free"}:
            raise ValueError("문서 수정 풀이 방식이 올바르지 않습니다.")


def default_settings_path() -> Path:
    return user_config_path("vim-key-trainer", appauthor=False) / "settings.json"


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("설정 필드가 올바르지 않습니다.")
    return value


class SettingsRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_error: str | None = None

    def load(self) -> AppSettings:
        self.last_error = None
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(_MAX_SETTINGS_BYTES + 1)
            if len(raw) > _MAX_SETTINGS_BYTES:
                raise ValueError("설정 파일이 너무 큽니다.")
            data = _object(
                json.loads(raw.decode("utf-8")),
                {
                    "version",
                    "challenge",
                    "presentation",
                    "font_size",
                    "record_rival",
                    "appearance",
                    "edit_mode",
                },
            )
            if type(data["version"]) is not int or data["version"] != SETTINGS_VERSION:
                raise ValueError("설정 버전이 달라 기본값으로 초기화합니다.")
            challenge = _object(
                data["challenge"], {"kind", "difficulty", "auto_repair"}
            )
            presentation = _object(
                data["presentation"],
                {
                    "effects",
                    "reduced_motion",
                    "success_sound",
                    "failure_sound",
                    "countdown_sound",
                    "volume",
                },
            )
            return AppSettings(
                challenge=ChallengeOptions(**challenge),
                presentation=PresentationSettings(**presentation),
                font_size=data["font_size"],
                record_rival=data["record_rival"],
                appearance=AppearanceSettings(
                    **_object(
                        data["appearance"], {"mascot", "fuse", "stamp", "decorations"}
                    )
                ),
                edit_mode=data["edit_mode"],
            )
        except FileNotFoundError:
            return AppSettings()
        except (OSError, ValueError, TypeError, RecursionError) as error:
            self.last_error = f"설정을 읽지 못해 기본값을 사용합니다. {error}"
            return AppSettings()

    def save(self, settings: AppSettings) -> bool:
        self.last_error = None
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": SETTINGS_VERSION, **asdict(settings)}
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".settings-",
                suffix=".json",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return True
        except (OSError, ValueError) as error:
            self.last_error = f"설정 저장 실패 · {error}"
            return False
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
