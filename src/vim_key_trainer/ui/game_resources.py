"""앱에 포함된 이미지·음원과 전체 라이선스의 고정 해시를 검증한다."""

# Standard library imports
import hashlib
import json
from functools import lru_cache
from importlib.resources import files

_ALLOWED_ASSETS = frozenset(
    {
        "bomb-mascot.png",
        "cat-mascot.png",
        "library-workshop.png",
        "success.wav",
        "timeout.wav",
        "countdown.wav",
    }
)


@lru_cache(maxsize=len(_ALLOWED_ASSETS))
def game_resource_path(name: str) -> str:
    if name not in _ALLOWED_ASSETS:
        raise ValueError("등록되지 않은 게임 리소스입니다.")
    root = files("vim_key_trainer").joinpath("resources/game")
    metadata = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("게임 리소스 정보가 올바르지 않습니다.")
    if (
        type(metadata.get("schema_version")) is not int
        or metadata.get("schema_version") != 1
        or type(metadata.get("version")) is not int
        or metadata.get("version") != 1
        or metadata.get("license_file") != "LICENSE.txt"
        or metadata.get("license") != "MIT"
        or hashlib.sha256(root.joinpath("LICENSE.txt").read_bytes()).hexdigest()
        != metadata.get("license_sha256")
    ):
        raise ValueError("게임 리소스 버전·라이선스가 일치하지 않습니다.")
    entries = metadata.get("assets")
    if not isinstance(entries, list) or len(entries) != len(_ALLOWED_ASSETS):
        raise ValueError("게임 리소스 목록이 올바르지 않습니다.")
    names = [entry.get("file") for entry in entries if isinstance(entry, dict)]
    if (
        len(names) != len(entries)
        or any(type(name) is not str for name in names)
        or set(names) != _ALLOWED_ASSETS
    ):
        raise ValueError("게임 리소스 이름이 올바르지 않습니다.")
    entry = next(entry for entry in entries if entry["file"] == name)
    path = root.joinpath(name)
    if (
        type(entry.get("version")) is not int
        or entry.get("version") != 1
        or not isinstance(entry.get("source"), str)
        or not entry["source"]
        or hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256")
    ):
        raise ValueError("게임 리소스의 출처·고정 해시가 일치하지 않습니다.")
    return str(path)
