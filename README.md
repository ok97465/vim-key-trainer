# vim-key-trainer

Python과 PySide6로 만든 데스크톱 키보드 연습기입니다. 현재 메뉴 화면과 숫자·기호 연습을 사용할 수 있습니다. 계정·서버·Vim 설치 없이 로컬에서 동작합니다.

## 설치와 실행

Python 3.12와 [uv](https://docs.astral.sh/uv/getting-started/installation/)를 준비한 뒤 저장소에서 실행합니다.

```sh
uv sync --dev
uv run vim-key-trainer
```

모듈 실행도 가능합니다.

```sh
uv run python -m vim_key_trainer
```

uv 없이 설치하려면 macOS/Linux에서 다음 명령을 사용합니다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m vim_key_trainer
```

의존성 선언은 [pyproject.toml](pyproject.toml), 정확한 버전은 [uv.lock](uv.lock)으로 관리합니다. [requirements.txt](requirements.txt)는 실행 의존성을 다음 명령으로 내보낸 파일이며, 실행 패키지 자체는 포함하지 않습니다.

```sh
uv export --no-dev --no-emit-project --no-hashes --output-file requirements.txt
```

## 현재 사용할 수 있는 기능

| 화면 | 기능 |
| --- | --- |
| 메뉴 | 숫자, Shift 숫자 기호, 기타 기호, 숫자·기호 혼합 중 선택. 이번 실행의 완료 횟수와 레슨별 최고 별 표시 |
| 연습 | 준비 → 시작 → 연속 입력 → 결과. 기본 20자를 동시에 표시하고 총 100자를 입력하면 완료 |
| 결과 | 정확도, CPM, 활성 연습 시간, 최대 콤보, 별, 자주 틀린 목표 키, 키패드 오류 확인 |
| 재도전 | 같은 문제·seed로 다시 연습하거나 새 문제 생성 |
| 설정 | 총 목표 20/50/100/200자, 표시량 10/20/40자, 연습 글꼴 크기 16~30pt 선택 |
| 키 입력 진단 | 문자·논리 키·modifier·키패드 여부·자동 반복·native scan code 확인 |

메뉴에서 레슨의 **연습 준비**를 누르고 **연습 시작** 후 강조된 문자부터 순서대로 입력합니다. 표시 구간이 끝나면 다음 구간으로 자동 전환하며, 구분용 공백이나 Enter를 입력할 필요가 없습니다. 오타는 현재 위치를 유지하므로 올바른 문자를 다시 누르면 됩니다.

정확도는 `정답 / (정답 + 오답) × 100`, CPM은 `정답 수 × 60 / 활성 연습 시간(초)`입니다. 완주하면 별 1개, 정확도 95% 이상이면 2개, 100%이면 3개를 받습니다. 개인 최고 기록은 같은 문제·seed·목표 길이·표시량·일시정지 사용 조건끼리 정확도, 활성 시간 순서로 비교합니다. 기록과 설정은 앱 실행 중에만 유지되며 종료하면 초기화됩니다.

## 입력과 시간 측정

- 영문 입력 모드와 US QWERTY 배열을 기준으로 합니다. Shift 기호는 결과 문자 하나로 비교하고 1타로 셉니다.
- Backspace, modifier 단독, KeyRelease, 길게 누르기의 자동 반복, 붙여넣기·드롭, IME 조합 입력은 연습 진행과 채점에 포함하지 않습니다.
- 첫 채점 대상 입력부터 시간을 측정하며, 첫 입력이 오타여도 측정을 시작합니다. 일시정지와 포커스 상실 시간은 제외하고 마지막 정답에서 측정을 끝냅니다.
- 연습 영역에서 포커스를 잃거나 다른 창으로 전환하면 일시정지합니다. 돌아온 뒤 **연습 재개** 버튼으로 계속합니다. Esc·Enter는 연습 입력이며 일시정지·메뉴 이동은 화면 버튼을 사용합니다.
- `KeypadModifier`로 식별된 숫자는 상단 숫자열 사용을 안내하고 별도의 위치 오류로 셉니다. 물리 위치를 알 수 없는 입력은 문자로 비교하며 native scan code로 키 위치를 추정하지 않습니다.
- macOS의 기본 Qt 매핑에서 Qt Control은 Command, Qt Meta는 실제 Control로 구분합니다. 진단 화면은 이 정규화 결과를 보여 주며 앱 밖에서 키를 수집하지 않습니다.

## 다음 구현 범위

Vim 명령 연습과 가이드·자유 문서 수정은 메뉴에서 준비 중으로 표시합니다. JSON 레슨 로더, 설정·학습 기록의 영구 저장, 오답 복습, 효과음·움직이는 화면 효과도 아직 구현하지 않았습니다.

전체 목표는 숫자·기호 → 명령 타이핑과 의미 학습 → 좌우 문서를 비교하는 편집 학습입니다. 편집 동작은 Python 내부 시뮬레이터에서 구현하며 실제 Vim/Neovim 실행·임베딩·RPC 연동이나 사용자 파일 편집은 제품에 포함하지 않습니다.

## 개발과 검증

Python 3.12.12/macOS arm64, PySide6 6.12.0에서 설치·패키징, 순수 Python 단위 테스트와 `pytest-qt` 입력·화면 전환을 검증했습니다. 네이티브 cocoa 백엔드에서 독립 창을 띄워 합성 키 입력과 일시정지·재개·완료 흐름을 확인했습니다. 최소 960×680·기본 1200×800의 메뉴·연습·결과와 40자 표시를 렌더해 확인했으며, 작은 창의 추가 안내·화면 키보드는 스크롤할 수 있습니다.

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

화면이 없는 환경에서는 `QT_QPA_PLATFORM=offscreen uv run pytest`로 Qt 테스트를 실행할 수 있습니다. 자동 Qt 이벤트·렌더 검증은 실제 키보드·IME 검증과 구분합니다. 실제 macOS 하드웨어 키보드·한글 IME·고해상도 화면 수동 검증과 Windows/Linux 검증은 아직 수행하지 않았습니다.

- [소프트웨어 설계와 게임 규칙](sw_design.md)
- [구현 단계와 완료 조건](todo.md)
- [작업 지침](agents.md)
