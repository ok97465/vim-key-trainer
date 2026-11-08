"""배포 그림·음원의 출처/라이선스 검증과 변조 시 거부를 확인한다."""

# Standard library imports
import json
import shutil
import wave
from pathlib import Path

# Third party imports
import pytest

# Local imports
from vim_key_trainer.ui.game_resources import game_resource_path


def test_packaged_audio_and_license_are_verified() -> None:
    for name in ("success", "timeout", "countdown"):
        path = game_resource_path(name + ".wav")
        with wave.open(path, "rb") as stream:
            assert stream.getnchannels() == 1
            assert stream.getsampwidth() == 2
            assert stream.getframerate() == 44_100
            assert 0 < stream.getnframes() / stream.getframerate() < 0.5
    for name in ("bomb-mascot.png", "cat-mascot.png", "library-workshop.png"):
        assert Path(game_resource_path(name)).is_file()


def test_resource_tamper_and_unregistered_path_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path(game_resource_path("success.wav")).parent
    target = tmp_path / "resources" / "game"
    target.mkdir(parents=True)
    for name in ("manifest.json", "LICENSE.txt", "success.wav"):
        shutil.copyfile(original / name, target / name)
    monkeypatch.setattr("vim_key_trainer.ui.game_resources.files", lambda _: tmp_path)
    game_resource_path.cache_clear()
    try:
        assert game_resource_path("success.wav") == str(target / "success.wav")
        game_resource_path.cache_clear()
        (target / "success.wav").write_bytes(b"tampered")
        with pytest.raises(ValueError):
            game_resource_path("success.wav")
        with pytest.raises(ValueError):
            game_resource_path("../LICENSE.txt")
        metadata = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        metadata["schema_version"] = True
        (target / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
        with pytest.raises(ValueError):
            game_resource_path("success.wav")
    finally:
        game_resource_path.cache_clear()
