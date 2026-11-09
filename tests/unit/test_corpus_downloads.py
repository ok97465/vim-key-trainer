"""문서·코드 다운로드의 경로 경계와 파일 교체 실패 처리를 검증한다."""

# Standard library imports
import hashlib
import io
import runpy
import tempfile
from pathlib import Path
from typing import Any

# Third party imports
import pytest


@pytest.fixture(params=["fetch_code_corpus.py", "fetch_document_corpus.py"])
def corpus_script(request: pytest.FixtureRequest) -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / request.param


@pytest.mark.parametrize(
    "relative",
    [r"source/..\..\outside.txt", r"source/D:\outside.txt"],
)
@pytest.mark.parametrize("verify_only", [False, True])
def test_windows_path_syntax_is_rejected_before_download_or_local_read(
    relative: str,
    verify_only: bool,
    monkeypatch: pytest.MonkeyPatch,
    corpus_script: Path,
) -> None:
    def unexpected_io(*_args: object, **_kwargs: object) -> None:
        pytest.fail("잘못된 경로를 검증하기 전에 파일이나 네트워크에 접근했습니다.")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_io)
    monkeypatch.setattr(Path, "read_bytes", unexpected_io)
    fetch_one = runpy.run_path(str(corpus_script))["fetch_one"]
    url = "https://raw.githubusercontent.com/example/project/" + "0" * 40 + "/source"

    with pytest.raises(ValueError, match="다운로드 항목"):
        fetch_one((url, relative, "0" * 64), verify_only=verify_only)


@pytest.mark.parametrize("failure_stage", ["write", "replace"])
def test_download_failure_preserves_original_and_removes_temporary_file(
    failure_stage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corpus_script: Path,
) -> None:
    data = b"verified source"
    destination = tmp_path / "source" / "source.txt"
    destination.parent.mkdir()
    destination.write_bytes(b"original source")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_args, **_kwargs: io.BytesIO(data)
    )
    named_temporary_file = tempfile.NamedTemporaryFile

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk failure")

    def create_temporary_file(*args: Any, **kwargs: Any) -> Any:
        output = named_temporary_file(*args, **kwargs)
        if failure_stage == "write":
            monkeypatch.setattr(output, "write", fail)
        return output

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", create_temporary_file)
    if failure_stage == "replace":
        monkeypatch.setattr("os.replace", fail)
    fetch_one = runpy.run_path(str(corpus_script))["fetch_one"]
    monkeypatch.setitem(fetch_one.__globals__, "ROOT", tmp_path)
    url = "https://raw.githubusercontent.com/example/project/" + "0" * 40 + "/source"

    with pytest.raises(OSError, match="disk failure"):
        fetch_one(
            (url, "source/source.txt", hashlib.sha256(data).hexdigest()),
            verify_only=False,
        )

    assert destination.read_bytes() == b"original source"
    assert list(destination.parent.iterdir()) == [destination]
