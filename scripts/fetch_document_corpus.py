"""검토된 manifest의 고정 commit 문서·라이선스를 재다운로드한다.

실행 앱에서는 네트워크를 사용하지 않는다. 이 명령은 개발용이며 원격 문서를
실행하지 않고, SHA-256이 기록과 같은 경우에만 패키지 원본 파일을 교체한다.
"""

# Standard library imports
import argparse
import hashlib
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "vim_key_trainer"
    / "resources"
    / "documents"
)


def fetch_one(entry: tuple[str, str, str], *, verify_only: bool) -> None:
    url, relative, digest = entry
    parsed = urlparse(url)
    path = PurePosixPath(relative)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "raw.githubusercontent.com"
        or re.search(r"/[a-f0-9]{40}/", parsed.path) is None
        or path.is_absolute()
        or ".." in path.parts
        or len(path.parts) != 2
        or "\\" in relative
        or ":" in relative
        or re.fullmatch(r"[a-f0-9]{64}", digest) is None
    ):
        raise ValueError(f"manifest 다운로드 항목이 올바르지 않습니다: {relative}")
    destination = ROOT.joinpath(*path.parts)
    if verify_only:
        data = destination.read_bytes()
    else:
        request = Request(url, headers={"User-Agent": "vim-key-trainer corpus refresh"})
        with urlopen(request, timeout=30) as response:
            data = response.read(512_001)
    if len(data) > 512_000 or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"{relative}: SHA-256 불일치. 기존 파일을 보존합니다.")
    if verify_only:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = tempfile.NamedTemporaryFile(dir=destination.parent, delete=False)
    temporary = Path(output.name)
    try:
        with output:
            output.write(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only", action="store_true", help="네트워크 없이 번들 검증"
    )
    args = parser.parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    entries: set[tuple[str, str, str]] = set()
    for mission in manifest["missions"]:
        source = mission["source"]
        entries.add((source["raw_url"], source["source_path"], source["sha256"]))
        entries.add(
            (
                source["license_raw_url"],
                source["license_path"],
                source["license_sha256"],
            )
        )
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(fetch_one, entry, verify_only=args.verify_only)
            for entry in sorted(entries)
        ]
        for future in futures:
            future.result()
    print(f"문서·라이선스 {len(entries)}개 검증 완료")


if __name__ == "__main__":
    main()
