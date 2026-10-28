# misskorea: 미쓰코리아 쇼츠 제작 자동화 플러그인

유튜브 쇼츠 채널 **미쓰코리아**(@미쓰코리아K)의 영상 제작을 돕는 Claude Code 플러그인입니다.
사람은 **소재 선정, 원본 영상 확보, 최종 검수**만 하고, 대본·더빙·자막·렌더링은 자동으로 처리합니다.

```
batch.csv 작성 ─ 원본 영상 넣기 ─ 대본 일괄 생성 ─ 검수(대본 고치기·승인) ─ 렌더링 ─ final.mp4
                                   (Claude)                                (TTS·자막·ffmpeg)
```

| 명령어 | 하는 일 |
|---|---|
| `/misskorea:batch` | `input/batch.csv`의 모든 줄에 대해 대본 패키지를 만들고 요약표를 만든다 |
| `/misskorea:render` | 검수가 끝난 영상들의 TTS 더빙 → 자막 → 렌더링을 한 번에 실행한다 |

> 명령어 이름은 플러그인 이름이 앞에 붙은 `/misskorea:...` 형태입니다. `/batch`나 `/misskorea-batch`처럼 짧게 치면 "Unknown command"가 나올 수 있습니다. 입력창에 `/misskorea`까지만 치고 목록에서 고르세요.

---

## 1. 준비물

| 항목 | 설명 |
|---|---|
| Claude Code | 데스크톱 앱 또는 CLI |
| Python 3.10 이상 | Windows: `winget install Python.Python.3.12`. 설치 후 터미널을 새로 열어야 `python`이 잡힙니다 |
| ffmpeg | Windows: `winget install Gyan.FFmpeg`. `ffmpeg -version`이 실행돼야 합니다 |
| Python 패키지 | `pip install requests python-dotenv PyYAML Pillow` |
| TTS 계정 (둘 중 하나) | 더빙용. **ElevenLabs**(기본) 또는 **타입캐스트**의 API 키와 **채널 고정 보이스 ID**가 필요합니다. 상업적 사용 가능 여부는 각 플랜 약관을 확인하세요. 타입캐스트는 개인 구독과 별도의 API 요금제가 필요할 수 있습니다 |
| 원본 영상 | **사용 허락을 받은 영상**을 직접 `mp4`로 준비합니다 |

## 2. 설치

Claude Code에서 아래 두 줄을 차례로 입력합니다.

```
/plugin marketplace add sena020625-cell/misskoreaag
/plugin install misskorea@misskorea-marketplace
```

설치가 끝나면 Claude Code를 다시 시작합니다. 입력창에 `/misskorea`를 치면 명령어 두 개가 보여야 합니다.

**업데이트:** 팀 저장소가 갱신되면 터미널에서 아래 두 줄을 실행하고 Claude Code를 다시 시작합니다.

```
claude plugin marketplace update misskorea-marketplace
claude plugin update misskorea@misskorea-marketplace
```

설치된 폴더는 `~/.claude/plugins/cache/misskorea-marketplace/misskorea/<버전>/`입니다.

## 3. 작업 폴더 만들기 (처음 한 번)

플러그인과 **작업 폴더는 따로**입니다. 영상과 결과물은 작업 폴더에 쌓이고, Claude Code도 이 폴더에서 실행합니다. 폴더 위치와 이름은 자유입니다.

```powershell
mkdir misskorea-work
cd misskorea-work
mkdir input\videos, output
```

### 3-1. `.env` 만들기

작업 폴더에 `.env` 파일을 만들고 아래처럼 채웁니다. 팀에서 정한 보이스 ID를 전원이 똑같이 씁니다.

```
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=여기에_본인_API_키
ELEVENLABS_VOICE_ID=팀이_정한_보이스_ID
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
```

타입캐스트를 쓰려면 `TTS_PROVIDER`를 바꾸고 타입캐스트 값을 채웁니다. 키는 [타입캐스트 개발자 콘솔](https://studio.typecast.ai/developers/api)에서 발급합니다.

```
TTS_PROVIDER=typecast
TYPECAST_API_KEY=여기에_본인_API_키
TYPECAST_VOICE_ID=tc_로_시작하는_보이스_ID
TYPECAST_MODEL=ssfm-v30
TYPECAST_LANGUAGE=kor
```

- 속도, 음높이, 음량, 감정(`TYPECAST_EMOTION=smart` 등)은 선택입니다. 설명은 `templates/.env.example`에 있습니다.
- 타입캐스트의 글자 타이밍이 문구와 맞지 않는다는 오류가 나면 `TTS_PROVIDER=per_line`, `PER_LINE_BACKEND=typecast`로 바꿔 보세요. 줄마다 합성해 이어 붙이는 대안입니다.
- **API 키는 본인 것만 쓰고 절대 공유·커밋하지 마세요.** `.env`는 작업 폴더 안에만 둡니다.
- 모든 설정 항목은 플러그인의 `templates/.env.example`에 설명과 함께 있습니다.

### 3-2. `input/batch.csv` 만들기

첫 줄(헤더)은 아래와 똑같이 씁니다. 파일은 **UTF-8**로 저장합니다(엑셀: "CSV UTF-8(쉼표로 분리)").

```
id,제품명,공식몰URL,원본링크,원본메모,훅,강조포인트,크리에이터
```

| 열 | 필수 | 설명 |
|---|---|---|
| id | O | 영상 번호. **원본 영상 파일 이름과 같아야 합니다**(예: `001` → `input/videos/001.mp4`) |
| 제품명 | O | 한글 제품명 |
| 공식몰URL | O | 공식몰 상세페이지 주소(`https://`로 시작) |
| 원본링크 | | 참고용 링크. 영상을 내려받는 데 쓰지 않습니다 |
| 원본메모 | | 원본 영상에서 무슨 일이 일어나는지 적어주면 첫 줄 훅이 훨씬 좋아집니다 |
| 훅 | | 원하는 첫 줄이 있으면 적습니다 |
| 강조포인트 | | 꼭 넣고 싶은 특징 |
| 크리에이터 | | 설명란의 `📷I` 줄에 들어갑니다. 비워두면 그 줄이 빠지고 검수 메모에 알림이 뜹니다 |

---

## 4. 하루 작업 흐름

### ① CSV 작성
오늘 만들 제품을 `input/batch.csv`에 한 줄씩 적습니다.

### ② 원본 영상 넣기
`input/videos/<id>.mp4`로 직접 넣습니다. 틱톡·인스타그램 영상을 자동으로 받는 기능은 **일부러 만들지 않았습니다**. 사용 허락을 받은 파일만 넣어주세요.

### ③ 대본 일괄 생성
작업 폴더에서 Claude Code를 열고 입력합니다.

```
/misskorea:batch
```

줄마다 공식 상세페이지를 읽고(이미지뿐이면 해외 판매처로 보완) 대본을 만들어 `output/오늘날짜/<id>/`에 저장합니다. 확인된 사실만 쓰고, 확인 못 한 것은 검수 메모에 남깁니다.

옵션: `--date 20261026`(날짜 폴더 지정), `--only 001,003`(일부만), `--overwrite`(이미 있는 대본 다시 만들기). 이미 있는 대본은 사람이 고친 내용을 지키기 위해 기본적으로 건너뜁니다.

### ④ 검수 (사람이 하는 가장 중요한 단계)

1. `output/날짜/summary.md`를 엽니다. 제품별 1순위 제목, 검수 필요 사유, 영상 파일 유무가 표로 보입니다.
2. `output/날짜/<id>/script.md`를 읽고 아래를 확인합니다.
   - **검수 메모**: 확인 못 한 것, 심의 위험 표현, 품절 표기, 영문 제품명 발음
   - 캡션 2버전 중 어느 쪽을 쓸지
3. `output/날짜/<id>/script.json`을 열어 고칩니다.

   | 항목 | 하는 일 |
   |---|---|
   | `selected_version` | 쓸 캡션 버전(`1` 또는 `2`) |
   | `versions[].lines` | 캡션 문구. **한 줄 = 자막과 음성의 한 단위**입니다. 줄 수는 4~7줄 |
   | `top_title` | 상단 타이틀. `line1`은 흰 글씨, `line2_green`은 초록 박스(10자 안팎) |
   | `approved` | 검수가 끝나면 `false`를 **`true`**로 바꿉니다 |

4. 설명란과 제목은 `script.md`에서 복사해 업로드할 때 씁니다.

**인체적용시험 수치를 쓴 영상**은 검수 메모에 "영상 하단에 '인체적용시험 결과, 개인차 있음' 표기 필요"가 적힙니다. 이 문구는 렌더링에 **자동으로 들어가지 않으니** 업로드 전에 직접 확인하세요.

### ⑤ 렌더링

```
/misskorea:render
```

`approved`가 `true`인 영상 전부에 대해 TTS 더빙 → 자막 → 렌더링을 실행합니다. 결과는 `output/날짜/<id>/final.mp4`입니다.

- 특정 영상만: `/misskorea:render 001 003`
- 어제 만든 폴더: `/misskorea:render --date 20261025`
- 화면 배치만 빨리 확인: `/misskorea:render 001 --preview 3` (3초 지점 한 장을 `preview.png`로 저장, TTS 비용 없음)
- 음성을 다시 만들기: `--force-tts` (문구가 같으면 기본으로 재사용해 크레딧을 아낍니다)

### ⑥ 최종 확인 후 업로드
`final.mp4`를 눈과 귀로 확인합니다(발음, 자막 타이밍, 원본 영상과의 일치). 업로드는 직접 하세요(자동 업로드는 이번 범위에 없습니다).

### 결과물 위치

```
output/20261026/
├─ summary.md              전체 요약표
└─ 001/
   ├─ script.json          기계용 (고치는 파일)
   ├─ script.md            검수용 (읽는 파일)
   ├─ voice.mp3            TTS 음성
   ├─ timing.json          줄별 시작·끝 시간
   ├─ subtitle.srt         자막
   └─ final.mp4            완성 영상 (1080x1920)
```

---

## 5. 화면 모양 바꾸기

기본 모양은 플러그인의 `config/template.yaml`에 있습니다. 바꾸고 싶은 항목만 **작업 폴더의 `config/template.yaml`**에 적으면 기본값을 덮어씁니다.

```yaml
# misskorea-work/config/template.yaml (예시)
video:
  source_volume: 0.08     # 원본 소리를 더 작게
subtitle:
  size: 70                # 자막 글씨 크기
  color: "#FFFFFF"        # 자막 색
title:
  line2:
    box_color: "#00B050"  # 초록 박스 색
```

바꾼 뒤에는 `/misskorea:render <id> --preview 3`으로 먼저 확인하세요. 항목별 설명은 `config/template.yaml`의 주석에 있습니다. 가로 영상은 `video.fit: contain_blur`로 바꾸면 원본 전체를 보이고 남는 곳을 흐린 배경으로 채웁니다.

폰트는 상업적 사용이 가능한 **Black Han Sans**(타이틀)와 **Pretendard Bold**(자막)를 `assets/fonts`에 넣어 두었습니다(SIL OFL 1.1, 라이선스 파일 동봉).

---

## 6. 자주 나는 오류와 해결

| 증상 | 원인과 해결 |
|---|---|
| `Unknown command: /batch` (또는 `/misskorea-batch`) | 정식 이름은 `/misskorea:batch`입니다. 그래도 안 나오면 플러그인이 설치·활성화됐는지 `/plugin`으로 확인하고 Claude Code를 다시 시작하세요 |
| `python`을 찾을 수 없다 | Python 설치 후 **터미널과 Claude Code를 완전히 껐다 켜세요**(PATH 갱신). Windows에서는 `py -3`로도 시도합니다 |
| `ModuleNotFoundError` (requests, yaml, PIL, dotenv) | `pip install requests python-dotenv PyYAML Pillow` |
| `ffmpeg를 찾을 수 없습니다` | ffmpeg 설치 후 터미널을 새로 엽니다. `ffmpeg -version`이 실행돼야 합니다 |
| CSV 한글이 깨진다 | 엑셀에서 "CSV UTF-8(쉼표로 분리)"로 다시 저장하세요 |
| 엑셀이 `001`을 `1`로 바꾼다 | 그 열의 서식을 "텍스트"로 하거나, 영상 파일 이름도 `1.mp4`로 맞추세요. id와 영상 파일 이름만 같으면 됩니다 |
| 어떤 줄이 "실패" | `summary.md`의 "실패한 줄"에 사유와 고칠 방법이 적혀 있습니다(보통 `공식몰URL` 누락) |
| 대본이 다시 안 만들어진다 | 이미 있는 대본은 건너뜁니다. 다시 만들려면 `--overwrite`. 단 `approved`가 `true`인 대본은 보호됩니다. 다시 만들려면 `approved`를 직접 `false`로 바꾸세요 |
| "승인된 대본이 없습니다" | `script.json`의 `approved`를 `true`로 바꿨는지, 날짜 폴더가 맞는지(`--date`) 확인하세요 |
| `.env에 ELEVENLABS_API_KEY 값이 없습니다` | 작업 폴더(Claude Code를 연 폴더)에 `.env`가 있는지, 키 이름이 정확한지 확인하세요 |
| ElevenLabs 오류 401 | API 키가 틀렸거나 권한이 없습니다 |
| ElevenLabs 오류 404 | `ELEVENLABS_VOICE_ID`가 틀렸습니다 |
| ElevenLabs 오류 429 | 크레딧이 부족하거나 요청이 너무 많습니다. 크레딧을 확인하고 잠시 뒤 다시 실행하세요 |
| 타입캐스트 오류 401 / 404 | API 키(`TYPECAST_API_KEY`) 또는 보이스 ID(`TYPECAST_VOICE_ID`, `tc_`로 시작)가 틀렸습니다 |
| 타입캐스트 오류 402 / 429 | 크레딧 부족 / 요청 한도 초과입니다. 요금제를 확인하고 잠시 뒤 다시 실행하세요 |
| 타입캐스트 오류 422 | 합성할 수 없는 문구입니다. 이모지나 특수 기호를 빼세요 |
| "타입캐스트가 돌려준 글자 수가 문구의 글자 수와 다르다" | 숫자·기호를 다르게 읽은 경우입니다. `.env`를 `TTS_PROVIDER=per_line`, `PER_LINE_BACKEND=typecast`로 바꾸세요 |
| "길이가 16~30초 범위를 벗어났습니다" | 캡션이 너무 길거나 짧습니다. `script.json`에서 문구를 줄이거나 늘리고 다시 렌더링하세요 |
| 발음이 이상하다 | 영문·긴 제품명이 흔한 원인입니다. 캡션 문구를 TTS가 읽기 쉽게 고치세요(착붙 같은 줄임말은 풀어 쓰기). 문구를 고치면 음성은 자동으로 다시 만들어집니다 |
| "원본 영상이 없습니다" | `input/videos/<id>.mp4`가 있는지, 이름이 id와 같은지 확인하세요 |
| "폰트 파일을 찾을 수 없습니다" | 플러그인을 다시 설치하세요. 직접 폰트를 바꿨다면 `template.yaml`의 `font` 경로를 확인하세요 |
| 자막이 화면 밖으로 나간다 | `subtitle.max_chars_per_line`을 줄이거나 `subtitle.size`를 작게 하세요. 폭을 넘는 자막은 자동으로 작아지긴 합니다 |
| ffmpeg 렌더링 실패 | 오류 마지막 줄을 확인하세요. 원본 mp4가 깨졌을 수 있으니 다른 플레이어에서 재생되는지 먼저 확인하세요 |

---

## 7. 비용이 생기는 곳

| 단계 | 비용 |
|---|---|
| 대본 생성(batch) | Claude 사용량. 영상 1개당 웹 페이지 몇 개를 읽고 작성합니다 |
| TTS(render 안) | **ElevenLabs 또는 타입캐스트 크레딧**(글자 수 기준으로 추정, 타입캐스트의 차감 방식은 요금제에서 확인). 영상 1개당 대략 150~300자입니다. 같은 문구는 다시 합성하지 않습니다 |
| 자막·렌더링 | 없음(내 컴퓨터의 ffmpeg) |

## 8. 지켜야 할 것

- 원본 영상은 **사용 허락을 받은 것**만 씁니다. 이 플러그인은 영상을 내려받지 않습니다.
- 영상 속 문구는 **확인된 사실**만 씁니다. 판매량·수상·수치를 만들어 넣지 않습니다. 검수 메모의 "확인 못 한 것"을 꼭 읽어주세요.
- 심의 표현(단정·절대 표현, 기능성 미확인 효능)은 `skills/misskorea-script/references/compliance.md`에 정리돼 있습니다.
- 업로드 전에 공식몰의 **품절·판매 중단 표기**를 확인하세요(검수 메모에 알림이 뜹니다).

---

## 9. 개발·관리자 메모

```
misskorea/
├─ .claude-plugin/{plugin.json, marketplace.json}   저장소 자체가 마켓플레이스
├─ skills/misskorea-script/                         대본 생성 스킬 + references(스타일·심의·스키마)
├─ commands/{batch.md, render.md}
├─ scripts/{tts.py, subtitle.py, render.py, common.py, tts_providers/}
├─ config/template.yaml                             화면 모양 기본값
├─ assets/fonts/                                    폰트와 라이선스
├─ templates/{batch.csv, .env.example}
└─ tests/                                           python -m unittest discover -s tests
```

- **TTS 공급자 추가**: `scripts/tts_providers/`에 `TTSProvider`를 상속한 클래스를 만들고 `__init__.py`의 `PROVIDERS`에 등록합니다. 글자 타이밍을 주지 않는 TTS는 `per_line.py`의 `BACKENDS`에 함수 하나만 추가하면 됩니다. `TTS_PROVIDER=mock`은 키 없이 무음 오디오로 시험하는 용도이며 실제 영상에는 쓰지 마세요.
- **자동 업로드(추후)**: 영상마다 `final.mp4`와 `script.json`(제목, 설명란)이 한 폴더에 있으므로, YouTube Data API 예약 업로드를 붙일 때 이 폴더를 그대로 읽으면 됩니다.
- **버전 올리기**: `.claude-plugin/plugin.json`과 `marketplace.json`의 `version`을 같이 올린 뒤 푸시합니다.
- **로컬 시험**: `claude --plugin-dir <이 폴더>`로 설치 없이 불러올 수 있습니다.
- **다른 컴퓨터에서 테스트**: 설치, 폴더 복사, 격리 설치, Claude 없이 스크립트만 돌리는 방법과 체크리스트는 [docs/TESTING.md](docs/TESTING.md)에 있습니다.
