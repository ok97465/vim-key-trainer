"""manifest에 기록된 코드 원문·라이선스를 다시 내려받는다.

앱은 이 개발용 명령을 호출하지 않는다. 원격 코드를 실행하지 않고
패키지 리소스 폴더 안의 파일만 교체한다.
"""

# Standard library imports
import argparse
import json
from pathlib import Path

# Third party imports
from corpus_download import download_corpus

ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "vim_key_trainer"
    / "resources"
    / "code_corpus"
)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    count = download_corpus(ROOT, manifest["sources"])
    print(f"코드 원문·라이선스 {count}개 다운로드 완료")


if __name__ == "__main__":
    main()
