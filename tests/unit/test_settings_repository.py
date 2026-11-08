"""설정 손상·원자적 교체 실패에서도 안전한 기본값/이전 파일을 보존한다."""

# Standard library imports
import json
from pathlib import Path
from unittest.mock import patch

# Third party imports
import pytest

# Local imports
from vim_key_trainer.domain.challenge import ChallengeOptions
from vim_key_trainer.domain.preferences import PresentationSettings
from vim_key_trainer.services.settings_repository import AppSettings, SettingsRepository


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
