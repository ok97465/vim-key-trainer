"""설정 손상과 원자적 교체 실패에도 기본값·이전 파일을 보존한다."""

# Standard library imports
import json
from pathlib import Path
from unittest.mock import patch

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.editing import EditMode
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.services.settings_repository import (
    SETTINGS_VERSION,
    AppSettings,
    SettingsRepository,
)


def test_settings_roundtrip_and_failed_replace_preserves_previous(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config" / "settings.json"
    repository = SettingsRepository(path)
    original = AppSettings(
        ChallengeOptions("bomb", "challenge", False),
        PresentationSettings(reduced_motion=True, volume=0.2),
        17,
        True,
    )
    assert repository.load() == AppSettings()
    assert repository.last_error is None
    assert repository.save(original)
    assert repository.load() == original
    raw = path.read_bytes()
    with patch(
        "vim_key_trainer.services.settings_repository.os.replace",
        side_effect=OSError("disk"),
    ):
        assert not repository.save(AppSettings())
    assert repository.last_error
    assert path.read_bytes() == raw
    assert sorted(item.name for item in path.parent.iterdir()) == ["settings.json"]


@pytest.mark.parametrize("mode", ["guided", "free"])
def test_last_edit_choices_survive_settings_roundtrip(
    tmp_path: Path, mode: EditMode
) -> None:
    path = tmp_path / "settings.json"
    repository = SettingsRepository(path)
    settings = AppSettings(
        challenge=ChallengeOptions("bomb", "relaxed", False),
        edit_mode=mode,
    )
    assert repository.save(settings)
    restored = SettingsRepository(path).load()
    assert restored.edit_mode == mode
    assert restored.challenge == settings.challenge
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == SETTINGS_VERSION


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": 99},
        {"font_size": True},
        {"font_size": 31},
        {"record_rival": 1},
        {"extra": "unknown"},
        {"challenge": {"kind": "bomb", "difficulty": "normal", "auto_repair": 1}},
        {"presentation": {"volume": float("nan")}},
        {"edit_mode": "visual"},
        {"edit_mode": True},
        {"edit_mode": ["guided"]},
    ],
)
def test_invalid_settings_reset_all_fields(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    path = tmp_path / "settings.json"
    repository = SettingsRepository(path)
    assert repository.save(AppSettings(font_size=20))
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(mutation)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert repository.load() == AppSettings()
    assert repository.last_error


def test_old_settings_version_resets_choices_without_rewriting_the_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    repository = SettingsRepository(path)
    assert repository.save(
        AppSettings(challenge=ChallengeOptions("bomb", "challenge"), edit_mode="free")
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 1
    del data["edit_mode"]
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    assert repository.load() == AppSettings()
    assert repository.last_error
    assert path.read_bytes() == before


@pytest.mark.parametrize("raw", [b"\xff", b"{", b" " * 16_385, b"[1,2]"])
def test_broken_settings_use_defaults(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(raw)
    repository = SettingsRepository(path)
    assert repository.load() == AppSettings()
    assert repository.last_error


def test_presentation_rejects_invalid_volume_and_boolean_values() -> None:
    for volume in (-1, 1.01, float("inf"), float("nan"), True):
        with pytest.raises(ValueError):
            PresentationSettings(volume=volume)
