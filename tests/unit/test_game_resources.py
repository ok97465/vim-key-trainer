"""그림·음원을 메타데이터 선검사 없이 패키지에서 사용할 수 있다."""

# Standard library imports
import wave
from pathlib import Path

# Third party imports
import pytest

# Local imports
from vim_key_trainer.ui.game_resources import game_resource_path


def test_packaged_images_and_audio_are_available() -> None:
    for name in ("success", "timeout", "countdown"):
        path = game_resource_path(name + ".wav")
        with wave.open(path, "rb") as stream:
            assert stream.getnchannels() == 1
            assert stream.getsampwidth() == 2
            assert stream.getframerate() == 44_100
            assert 0 < stream.getnframes() / stream.getframerate() < 0.5
    for name in ("bomb-mascot.png", "cat-mascot.png", "library-workshop.png"):
        assert (
            Path(game_resource_path(name)).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        )


@pytest.mark.parametrize("metadata_present", [False, True])
def test_resource_paths_do_not_read_metadata_license_or_asset_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata_present: bool
) -> None:
    target = tmp_path / "resources" / "game"
    target.mkdir(parents=True)
    if metadata_present:
        (target / "manifest.json").write_bytes(b"modified metadata\r\n")
        (target / "LICENSE.txt").write_bytes(b"modified license\r\n")
    monkeypatch.setattr("vim_key_trainer.ui.game_resources.files", lambda _: tmp_path)
    for name in ("success.wav", "bomb-mascot.png"):
        assert game_resource_path(name) == str(target / name)
        (target / name).write_bytes(b"modified asset")
        assert game_resource_path(name) == str(target / name)


def test_unregistered_resource_paths_are_rejected() -> None:
    with pytest.raises(ValueError, match="등록되지 않은"):
        game_resource_path("../LICENSE.txt")
