"""manifest에 기록된 원문·라이선스를 내려받는 개발용 공통 기능."""

# Standard library imports
import os
import tempfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import TypedDict
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_MAX_BYTES = 512_000


class SourceFiles(TypedDict):
    raw_url: str
    source_path: str
    license_raw_url: str
    license_path: str


def fetch_one(root: Path, entry: tuple[str, str]) -> None:
    url, relative = entry
    parsed = urlparse(url)
    path = PurePosixPath(relative)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "raw.githubusercontent.com"
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in relative
        or ":" in relative
    ):
        raise ValueError(f"manifest 다운로드 항목이 올바르지 않습니다: {relative}")
    request = Request(url, headers={"User-Agent": "vim-key-trainer corpus refresh"})
    with urlopen(request, timeout=30) as response:
        data = response.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise ValueError(f"{relative}: 다운로드 크기가 512,000바이트를 넘었습니다.")
    destination = root.joinpath(*path.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = tempfile.NamedTemporaryFile(dir=destination.parent, delete=False)
    temporary = Path(output.name)
    try:
        with output:
            output.write(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def download_corpus(root: Path, sources: Iterable[SourceFiles]) -> int:
    entries = {
        entry
        for source in sources
        for entry in (
            (source["raw_url"], source["source_path"]),
            (source["license_raw_url"], source["license_path"]),
        )
    }
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_one, root, entry) for entry in sorted(entries)]
        for future in futures:
            future.result()
    return len(entries)
