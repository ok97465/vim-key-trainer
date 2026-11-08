# 게임 그림과 효과음

모든 파일은 앱에 포함되며 실행 중 네트워크나 이미지 생성 서비스를 사용하지 않습니다. 전체 배포 라이선스는 [LICENSE.txt](LICENSE.txt)입니다.

| 파일 | 제작·용도 |
| --- | --- |
| `bomb-mascot.png` | 내장 image_gen으로 제작한 고해상도 투명 폭탄 캐릭터 |
| `cat-mascot.png` | 같은 방식으로 제작한 고양이 모양 해금 캐릭터 |
| `library-workshop.png` | 같은 방식으로 제작한 수집 작업실 그림 |
| `success.wav` | 자체 합성한 0.32초 성공 차임 |
| `timeout.wav` | 자체 합성한 0.34초 금속성 두 번 타격음 |
| `countdown.wav` | 자체 합성한 0.055초 초읽기음 |

이미지 생성의 최종 프롬프트·고정 버전·출처·SHA-256은 [manifest.json](manifest.json)에 기록합니다. 앱은 사용 시 리소스와 전체 라이선스의 해시를 검증합니다. 음원은 외부 샘플 없이 [생성 스크립트](../../../../scripts/generate_game_audio.py)로 재현할 수 있습니다. 재생성한 음원을 배포할 때 목록의 해시도 갱신합니다.

연출은 [Qt QVariantAnimation](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QVariantAnimation.html)과 [QSoundEffect](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QSoundEffect.html)를 사용합니다. 기본 무음이며 음량·개별 소리·화면 효과·모션 줄이기를 설정할 수 있습니다. 실제 오디오 장치의 청취 검증은 자동 GUI 검증과 별도로 수행합니다.
