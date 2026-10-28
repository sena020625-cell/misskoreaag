# 다른 컴퓨터에서 테스트하는 방법

팀원 PC나 새 PC에서 플러그인이 제대로 동작하는지 확인하는 방법을 정리했습니다.
**방법을 고르는 표 → 준비 → 설치 방법 → 단계별 테스트 → 결과 보고 양식** 순서입니다.

> 이 문서의 명령은 Windows 11 + PowerShell에서 검증했습니다. macOS/Linux에서는 아직 시험하지 않았습니다(스크립트는 경로를 OS에 맞게 처리하도록 짰지만 확인되지 않았습니다).

---

## 0. 어떤 방법으로 테스트할까

| 상황 | 방법 | Claude 로그인 | 비용 |
|---|---|---|---|
| 팀원이 실제로 쓰는 흐름 그대로 확인 | **A. 마켓플레이스로 설치** | 필요 | 대본 생성은 Claude 사용량 |
| 설치 없이 폴더만으로 확인, 디버깅 | **B. `git clone` + `--plugin-dir`** | 필요 | 위와 같음 |
| GitHub에 접근할 수 없는 PC (사내망, 비공개 등) | **C. 폴더 복사(압축) + `--plugin-dir`** | 필요 | 위와 같음 |
| 내 Claude 설정을 건드리고 싶지 않음 | **D. 격리 설치** (임시 설정 폴더) | 필요 | 위와 같음 |
| **Claude 없이** 영상 만들기 부분(TTS·자막·렌더링)만 확인 | **E. 스크립트 직접 실행 (스모크 테스트)** | **불필요** | **무료** (mock 음성) |
| 코드가 이 PC에서 도는지만 빠르게 확인 | **F. 단위 테스트** | 불필요 | 무료 |

처음 해보는 PC라면 **F → E → A** 순서를 권합니다. 앞의 두 개가 통과하면 환경(Python, ffmpeg, 폰트)은 정상이고, 남는 문제는 Claude 쪽(명령어 호출, 대본 생성)으로 좁혀집니다.

---

## 1. 준비 (모든 방법 공통)

| 항목 | 설치와 확인 |
|---|---|
| Python 3.10 이상 | `winget install Python.Python.3.12` 후 **터미널을 새로 열고** `python --version` |
| ffmpeg | `winget install Gyan.FFmpeg` 후 **터미널을 새로 열고** `ffmpeg -version` (`ffprobe`도 같이 설치됩니다) |
| Python 패키지 | `pip install requests python-dotenv PyYAML Pillow` |
| Git | 방법 B, E, F에서 `git clone`에 필요합니다 |
| Claude Code | 방법 A~D에서 필요합니다. 설치 후 **로그인**되어 있어야 합니다 |

`python`이 안 잡히면 `py -3`을 대신 써도 됩니다(아래 명령에서 `python`을 `py -3`으로 바꿉니다).

---

## 2. 방법 E: Claude 없이 스크립트만 테스트 (스모크 테스트)

TTS, 자막, 렌더링이 이 PC에서 동작하는지 **무료로** 확인합니다. 무음 mock 음성을 쓰므로 API 키가 필요 없습니다. 결과 영상은 **테스트 전용**입니다.

저장소는 `C:\misskoreaag`에 받았다고 가정합니다. 다른 곳이면 경로만 바꾸세요.

```text
git clone https://github.com/sena020625-cell/misskoreaag C:\misskoreaag
```

작업 폴더를 만들고 샘플 대본과 더미 영상을 준비합니다.

```text
mkdir misskorea-work\input\videos, misskorea-work\output\20260101\001
copy C:\misskoreaag\templates\sample_script.json misskorea-work\output\20260101\001\script.json
cd misskorea-work
ffmpeg -f lavfi -i testsrc2=size=1080x1920:rate=30:duration=10 -f lavfi -i sine=frequency=440:duration=10 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest input\videos\001.mp4
```

세 단계를 차례로 실행합니다.

```text
python C:\misskoreaag\scripts\tts.py 001 --date 20260101 --provider mock --allow-unapproved
```

```text
python C:\misskoreaag\scripts\subtitle.py 001 --date 20260101
```

```text
python C:\misskoreaag\scripts\render.py 001 --date 20260101 --allow-unapproved
```

**통과 기준:** 세 명령 모두 마지막 줄이 `끝: 1/1건 성공`이고, `output\20260101\001\`에 `voice.mp3`, `timing.json`, `subtitle.srt`, `final.mp4`가 생깁니다. `final.mp4`를 재생하면 위쪽에 검은 띠와 흰 글씨·초록 박스 타이틀, 아래쪽에 노란 자막이 보여야 합니다.

화면 배치만 한 장으로 보려면:

```text
python C:\misskoreaag\scripts\render.py 001 --date 20260101 --allow-unapproved --preview 3
```

`output\20260101\001\preview.png`가 생깁니다.

---

## 3. 방법 F: 단위 테스트

```text
cd C:\misskoreaag
python -m unittest discover -s tests
```

**통과 기준:** `Ran 44 tests ... OK`. 실패하면 Python 버전이나 패키지(`pip install ...`)부터 확인하세요.

---

## 4. 방법 A: 마켓플레이스로 설치 (실제 팀원 흐름)

Claude Code 입력창에서 차례로 입력하고, 끝나면 Claude Code를 **다시 시작**합니다.

```text
/plugin marketplace add sena020625-cell/misskoreaag
```

```text
/plugin install misskorea@misskorea-marketplace
```

**확인:** 입력창에 `/misskorea`까지 치면 `/misskorea:batch`, `/misskorea:render`가 목록에 보여야 합니다. 터미널에서 `claude plugin list`로도 확인됩니다(`misskorea@misskorea-marketplace`, 활성화).

**업데이트(새 버전이 올라온 뒤):** 터미널에서 아래 두 줄을 실행하고 Claude Code를 다시 시작합니다. 새 버전은 `plugin.json`의 `version`이 올라가야 받아집니다.

```text
claude plugin marketplace update misskorea-marketplace
```

```text
claude plugin update misskorea@misskorea-marketplace
```

**삭제(테스트가 끝난 뒤):**

```text
claude plugin uninstall misskorea@misskorea-marketplace
```

```text
claude plugin marketplace remove misskorea-marketplace
```

---

## 5. 방법 B: `git clone` + `--plugin-dir` (설치 없이)

설치하지 않고 받은 폴더를 그대로 불러옵니다. 이미 설치된 플러그인과 충돌하지 않아 디버깅에 편합니다. 수정한 코드를 바로 시험할 때도 씁니다.

```text
git clone https://github.com/sena020625-cell/misskoreaag C:\misskoreaag
```

작업 폴더에서 실행합니다.

```text
cd misskorea-work
claude --plugin-dir C:\misskoreaag
```

**확인:** `/misskorea`를 치면 명령어가 보입니다. 이 방법은 Claude Code를 닫으면 끝나며, 설치 기록이 남지 않습니다.

## 6. 방법 C: 폴더 복사 + `--plugin-dir` (GitHub 접근 불가)

1. 개발 PC에서 저장소 폴더(`misskorea`)를 압축합니다. `.git` 폴더는 빼도 됩니다. `input\`, `output\`은 넣지 마세요(테스트 데이터).
2. USB, 사내 드라이브 등으로 옮겨 풉니다. 예: `C:\misskoreaag`
3. 방법 B와 같이 `claude --plugin-dir C:\misskoreaag`로 실행합니다.

## 7. 방법 D: 격리 설치 (내 Claude 설정을 건드리지 않음)

방법 A의 설치를 **임시 설정 폴더**에서만 하고 싶을 때 씁니다. 평소 설정, 로그인, 설치된 플러그인에는 영향이 없습니다. PowerShell에서:

```text
$env:CLAUDE_CONFIG_DIR = "$env:TEMP\claude-test"
claude plugin marketplace add sena020625-cell/misskoreaag
claude plugin install misskorea@misskorea-marketplace
claude plugin list
Remove-Item Env:CLAUDE_CONFIG_DIR
```

설치본은 `%TEMP%\claude-test\plugins\cache\misskorea-marketplace\misskorea\<버전>\`에 생깁니다. 이 폴더의 `scripts\`로 방법 E를 그대로 실행해, **설치된 사본**에서도 폰트와 설정이 정상인지 볼 수 있습니다. 끝나면 `%TEMP%\claude-test` 폴더를 지우면 됩니다.

> 이 방식은 새 설정 폴더라 Claude Code 로그인이 비어 있습니다. `--version`, `plugin list`, 설치 확인까지만 되고, 명령어를 실행(모델 호출)하려면 그 환경에서 로그인해야 합니다.

---

## 8. 단계별 실제 테스트 (방법 A, B, C, D 공통)

작업 폴더 만들기와 `batch.csv`, `.env` 작성 방법은 [README.md](../README.md)의 3장과 같습니다. 아래 순서로 비용이 적은 것부터 확인합니다.

### 8-1. 대본 생성 (Claude 사용량만 듭니다)

`input\batch.csv`에 샘플 한 줄을 넣습니다(UTF-8).

```text
id,제품명,공식몰URL,원본링크,원본메모,훅,강조포인트,크리에이터
001,히어로 올데이 플럼핑 틴트,https://aprilskin.com/product/%ED%9E%88%EC%96%B4%EB%A1%9C-%EC%98%AC%EB%8D%B0%EC%9D%B4-%ED%94%8C%EB%9F%BC%ED%95%91-%ED%8B%B4%ED%8A%B8/1434/,,,,,
```

작업 폴더에서 Claude Code를 열고 입력합니다.

```text
/misskorea:batch
```

**통과 기준:** `output\날짜\001\script.json`, `script.md`, `output\날짜\summary.md`가 생깁니다. `script.md`에서 확인할 것:
- 캡션 2버전이 각각 4~7줄이고 끝맺음이 줄마다 다릅니다.
- 검수 메모에 근거 URL과 "확인 못 한 것"이 있습니다(없는 수치를 지어내지 않았는지).

### 8-2. 검수 흉내

`script.json`에서 `"approved": false`를 `true`로 바꿉니다.

### 8-3. 음성 없이 렌더링 (무료)

작업 폴더의 `.env`에 아래 한 줄만 넣고, `input\videos\001.mp4`에 영상(방법 E의 더미 영상 가능)을 둡니다.

```text
TTS_PROVIDER=mock
```

```text
/misskorea:render
```

**통과 기준:** `output\날짜\001\final.mp4`가 만들어지고 재생됩니다. 화면 배치만 보려면 `/misskorea:render 001 --preview 3`을 쓰세요.

### 8-4. 실제 음성 (ElevenLabs 크레딧이 듭니다)

`.env`를 아래처럼 바꿉니다. 키는 본인 것을 쓰고 공유하지 마세요.

```text
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=본인_키
ELEVENLABS_VOICE_ID=팀이_정한_보이스_ID
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
```

```text
/misskorea:render 001 --force-tts
```

**통과 기준:** `final.mp4`에서 한국어 음성이 나오고 자막이 말과 맞습니다. **이 단계는 아직 개발 PC에서도 실제 키로 검증하지 못했으므로, 가장 중요한 확인 대상입니다.** 오류가 나면 안내 문구(401 키 오류, 404 보이스 ID 오류, 429 크레딧 부족)를 그대로 알려주세요.

### 8-5. 타입캐스트 음성 (타입캐스트 API 크레딧이 듭니다)

`.env`를 아래처럼 바꿉니다(키는 [개발자 콘솔](https://studio.typecast.ai/developers/api)에서 발급).

```text
TTS_PROVIDER=typecast
TYPECAST_API_KEY=본인_키
TYPECAST_VOICE_ID=tc_로_시작하는_보이스_ID
TYPECAST_MODEL=ssfm-v30
TYPECAST_LANGUAGE=kor
```

```text
/misskorea:render 001 --force-tts
```

**통과 기준:** 위 8-4와 같습니다. **실제 타입캐스트 API로는 아직 호출해 보지 못했습니다**(공식 문서의 응답 구조를 본뜬 가짜 응답으로만 검증). 확인할 것:
- `output\날짜\001\timing.json`의 `lines[].chars` 글자 수가 문구 글자 수와 같은지, 자막 타이밍이 말과 맞는지.
- "글자 수가 문구의 글자 수와 다르다"는 오류가 나면 `.env`를 `TTS_PROVIDER=per_line`, `PER_LINE_BACKEND=typecast`로 바꿔 다시 시도하고, 그 오류 문구와 문구 내용(숫자, 기호 포함 여부)을 알려주세요.
- "응답 글자 N개가 문구와 달라 순서대로 대응시켰습니다" 주의 문구가 나오면 발음과 자막 타이밍을 귀로 확인해주세요.

---

## 9. 체크리스트

| # | 확인 항목 | 방법 | 결과 |
|---|---|---|---|
| 1 | `python --version`, `ffmpeg -version`이 실행된다 | 1장 | ☐ |
| 2 | 단위 테스트 44건이 통과한다 | F | ☐ |
| 3 | 스모크 테스트 3단계가 성공하고 `final.mp4`가 재생된다 | E | ☐ |
| 4 | 플러그인이 설치·활성화된다 | A (또는 B, C, D) | ☐ |
| 5 | `/misskorea`에 `batch`, `render`가 보인다 | A~D | ☐ |
| 6 | `/misskorea:batch`가 실행되어 `script.json`과 `summary.md`가 생긴다 | 8-1 | ☐ |
| 7 | 대본에 근거 없는 수치·판매량·수상이 없다 | 8-1 | ☐ |
| 8 | mock 음성으로 `/misskorea:render`가 `final.mp4`를 만든다 | 8-3 | ☐ |
| 9 | 실제 원본 영상 위에서 타이틀·자막 위치와 크기가 괜찮다 | 8-3 | ☐ |
| 10 | 실제 ElevenLabs 음성이 나오고 발음·자막 타이밍이 맞다 | 8-4 | ☐ |
| 11 | 원본 소리가 TTS를 가리지 않는다(볼륨 밸런스) | 8-4 | ☐ |
| 12 | 타입캐스트 음성이 나오고 자막 타이밍이 맞는다(타입캐스트를 쓰는 경우) | 8-5 | ☐ |

## 10. 결과 보고 양식

문제가 있으면 아래를 복사해 채워서 전달해주세요.

```text
- PC: Windows 11 / macOS / 기타 (버전)
- Python: (python --version 결과)
- ffmpeg: (ffmpeg -version 첫 줄)
- 사용한 방법: A / B / C / D / E / F
- 막힌 단계: (체크리스트 번호)
- 실행한 명령:
- 화면에 나온 오류 마지막 5줄:
- 시도해 본 것:
```

## 11. 자주 막히는 곳

| 증상 | 해결 |
|---|---|
| `python`을 찾을 수 없다 | 설치 후 터미널·Claude Code를 완전히 껐다 켜기. 또는 `py -3` |
| `/misskorea`에 아무것도 안 나온다 | 설치·활성화 확인(`claude plugin list`) 후 Claude Code 재시작. 방법 B라면 `--plugin-dir` 경로 확인 |
| `Unknown command` | 이름은 `/misskorea:batch`, `/misskorea:render`입니다(`/batch` 같은 짧은 이름은 안 됨) |
| 옛 이름(`misskorea-batch`)이 보인다 | 0.1.0이 설치된 상태입니다. 4장의 업데이트 두 줄을 실행하세요 |
| 방법 E에서 "폰트 파일을 찾을 수 없습니다" | 저장소를 통째로 받았는지(`assets\fonts\`에 폰트 2개), 스크립트를 저장소의 `scripts\`에서 실행했는지 확인 |
| `ModuleNotFoundError` | `pip install requests python-dotenv PyYAML Pillow` |
| Claude 명령이 로그인 오류(401)로 끝난다 | 그 PC의 Claude Code에서 다시 로그인 |
