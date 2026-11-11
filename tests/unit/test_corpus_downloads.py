"""공통 다운로드의 경로 경계·원본 교체·실패 처리를 검증한다."""

# Standard library imports
import io
import json
import runpy
import sys
import tempfile
from pathlib import Path
from typing import Any

# Third party imports
import pytest

HELPER = Path(__file__).resolve().parents[2] / "scripts" / "corpus_download.py"
SOURCE_URL = "https://raw.githubusercontent.com/example/project/main/source"


@pytest.mark.parametrize(
    "url,relative",
    [
        (SOURCE_URL, r"source/..\..\outside.txt"),
        (SOURCE_URL, r"source/D:\outside.txt"),
        (SOURCE_URL, "../outside.txt"),
        (SOURCE_URL, "/outside.txt"),
        (SOURCE_URL, ""),
        ("http://raw.githubusercontent.com/example/project/main/source", "source.txt"),
        ("https://example.com/source", "source.txt"),
    ],
)
def test_invalid_destination_or_url_is_rejected_before_download(
    url: str, relative: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_io(*_args: object, **_kwargs: object) -> None:
        pytest.fail("잘못된 항목으로 다운로드를 시작했습니다.")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_io)
    fetch_one = runpy.run_path(str(HELPER))["fetch_one"]
    with pytest.raises(ValueError, match="다운로드 항목"):
        fetch_one(tmp_path, (url, relative))
    assert not list(tmp_path.iterdir())


def test_download_replaces_existing_content_without_a_digest_or_commit_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"new source\r\n"
    destination = tmp_path / "source" / "source.txt"
    destination.parent.mkdir()
    destination.write_bytes(b"previous source")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: io.BytesIO(data))
    fetch_one = runpy.run_path(str(HELPER))["fetch_one"]

    fetch_one(tmp_path, (SOURCE_URL, "source/source.txt"))

    assert destination.read_bytes() == data
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize("failure_stage", ["download", "size", "write", "replace"])
def test_download_failure_preserves_original_and_removes_temporary_file(
    failure_stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"new source" if failure_stage != "size" else b"x" * 512_001
    destination = tmp_path / "source" / "source.txt"
    destination.parent.mkdir()
    destination.write_bytes(b"original source")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk or network failure")

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fail if failure_stage == "download" else lambda *_a, **_kw: io.BytesIO(data),
    )
    named_temporary_file = tempfile.NamedTemporaryFile

    def create_temporary_file(*args: Any, **kwargs: Any) -> Any:
        output = named_temporary_file(*args, **kwargs)
        if failure_stage == "write":
            monkeypatch.setattr(output, "write", fail)
        return output

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", create_temporary_file)
    if failure_stage == "replace":
        monkeypatch.setattr("os.replace", fail)
    fetch_one = runpy.run_path(str(HELPER))["fetch_one"]

    with pytest.raises(ValueError if failure_stage == "size" else OSError):
        fetch_one(tmp_path, (SOURCE_URL, "source/source.txt"))

    assert destination.read_bytes() == b"original source"
    assert list(destination.parent.iterdir()) == [destination]


def test_shared_sources_download_each_physical_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def download(request: Any, **_kwargs: object) -> io.BytesIO:
        calls.append(request.full_url)
        return io.BytesIO(b"downloaded\r\n")

    monkeypatch.setattr("urllib.request.urlopen", download)
    download_corpus = runpy.run_path(str(HELPER))["download_corpus"]
    source = {
        "raw_url": SOURCE_URL,
        "source_path": "source/source.txt",
        "license_raw_url": SOURCE_URL + "-license",
        "license_path": "source/LICENSE.txt",
    }

    assert download_corpus(tmp_path, [source, source]) == 2

    assert sorted(calls) == [SOURCE_URL, SOURCE_URL + "-license"]
    assert (tmp_path / "source/source.txt").read_bytes() == b"downloaded\r\n"
    assert (tmp_path / "source/LICENSE.txt").read_bytes() == b"downloaded\r\n"


@pytest.mark.parametrize("script", ["fetch_code_corpus.py", "fetch_document_corpus.py"])
def test_entry_points_use_the_shared_downloader(
    script: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripts = HELPER.parent
    monkeypatch.syspath_prepend(str(scripts))
    namespace = runpy.run_path(str(scripts / script))
    main = namespace["main"]
    sources = [{"id": "sample"}]
    manifest = {"sources": sources, "missions": [{"source": sources[0]}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    calls: list[tuple[Path, list[dict[str, str]]]] = []

    def download(root: Path, entries: Any) -> int:
        calls.append((root, list(entries)))
        return 2

    monkeypatch.setitem(main.__globals__, "ROOT", tmp_path)
    monkeypatch.setitem(main.__globals__, "download_corpus", download)
    monkeypatch.setattr(sys, "argv", [script])

    main()

    assert calls == [(tmp_path, sources)]
