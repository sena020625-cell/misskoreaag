---
description: 검수가 끝난(approved=true) 대본에 대해 TTS 더빙 → 자막 → 렌더링을 한 번에 실행해 final.mp4를 만든다
argument-hint: "[id ...] [--date YYYYMMDD] [--preview 초] [--force-tts]"
---

# /misskorea:render

검수가 끝난 id들에 대해 `tts.py` → `subtitle.py` → `render.py`를 차례로 실행해 `output/YYYYMMDD/<id>/final.mp4`를 만든다. 작업 폴더(현재 폴더)에서 실행한다.

사용자 인자: `$ARGUMENTS`

## 인자

| 인자 | 기본값 | 의미 |
|---|---|---|
| `id ...` | 승인된 id 전부 | 처리할 id. 지정해도 `approved`가 `true`가 아니면 처리하지 않는다 |
| `--date YYYYMMDD` | 오늘 날짜 | `output/` 아래 날짜 폴더 |
| `--preview 초` | 끔 | 해당 초 지점 한 장(`preview.png`)만 만든다. TTS를 새로 만들지 않는다 |
| `--force-tts` | 끔 | 문구가 같아도 TTS를 다시 만든다(크레딧이 다시 쓰인다) |

## 스크립트 위치와 실행 방법

- 스크립트는 플러그인 폴더의 `scripts/`에 있다. 경로는 `${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py`다. 이 값이 치환되지 않은 채로 보이면 `~/.claude/plugins` 아래에서 `**/scripts/render.py`를 Glob으로 찾아 같은 폴더를 쓴다. 그래도 없으면 "플러그인 스크립트를 찾지 못했습니다. 플러그인을 다시 설치해주세요."라고 알리고 멈춘다.
- Python 실행 파일은 `python`을 먼저 시도하고(`python --version`), 안 되면 `py -3`을 쓴다. 둘 다 안 되면 "Python 3.10 이상을 설치해주세요."라고 알리고 멈춘다.
- 모든 스크립트는 작업 폴더에서 `--workdir .`와 함께 실행한다.

## 절차

### 1. 사전 점검

1. `ffmpeg -version`이 실행되는지 확인한다. 안 되면 "ffmpeg를 설치하고 PATH에 추가해주세요."라고 알리고 멈춘다.
2. 필요한 패키지를 점검한다: `python -c "import requests, yaml, PIL, dotenv"`. 실패하면 `pip install -r "${CLAUDE_PLUGIN_ROOT}/scripts/requirements.txt"`를 안내하고 멈춘다.
3. `--preview`가 없으면 작업 폴더의 `.env`를 확인한다. 없으면 "`.env`가 없습니다. 플러그인의 `templates/.env.example`을 `.env`로 복사해 API 키와 보이스 ID를 채워주세요."라고 알리고 멈춘다. (키가 비어 있는 오류는 `tts.py`가 한글로 안내한다.)

### 2. 대상 id 정하기

1. `id`가 주어지면 그 id들을, 없으면 `output/<날짜>/*/script.json` 중 `approved`가 `true`인 id 전부를 대상으로 한다.
2. 대상이 없으면 "승인된 대본이 없습니다. `script.json`에서 검수 후 `approved`를 `true`로 바꿔주세요."라고 알리고 멈춘다.
3. 주어진 id 중 `approved`가 `true`가 아닌 것은 대상에서 빼고 이유를 알린다. `--allow-unapproved` 같은 우회 옵션은 쓰지 않는다.
4. 대상 중 `input/videos/<id>.mp4`가 없는 id는 빼고 "원본 영상을 `input/videos/<id>.mp4`로 넣어주세요."라고 알린다.
5. 남은 id가 없으면 멈춘다.

### 3. 실행 (남은 id 전부를 한 번씩 넘긴다)

`--preview`가 있으면 3번의 TTS·자막 단계를 건너뛰고 `render.py <id들> --date <날짜> --preview <초>`만 실행한다. `voice.mp3`나 `subtitle.srt`가 없다는 오류가 나면 "먼저 `/misskorea:render <id>`를 한 번 실행해주세요."라고 알린다.

그렇지 않으면 아래를 순서대로 실행한다. 단계에서 실패한 id는 다음 단계에서 뺀다.

1. **TTS**: `tts.py <id들> --date <날짜> --workdir .` (`--force-tts`가 있으면 `--force` 추가)
   - 먼저 같은 인자에 `--dry-run`을 붙여 한 번 실행해 "합성 예정 N건, 약 X자"를 사용자에게 알려준다. `voice.mp3`가 이미 있고 문구가 같으면 `tts.py`가 건너뛰므로 크레딧이 다시 쓰이지 않는다.
2. **자막**: `subtitle.py <id들> --date <날짜> --workdir .`
3. **렌더링**: `render.py <id들> --date <날짜> --workdir .`

각 스크립트의 출력에서 id별 성공·실패 한 줄을 읽어 실패 사유를 기록한다.

### 4. 보고

대화에는 아래만 짧게 보고한다.

- 성공한 id와 `output/<날짜>/<id>/final.mp4` 경로
- 실패한 id와 사유, 그리고 고치는 방법(예: "원본 영상 없음", "API 키 오류", "크레딧 부족")
- TTS 길이가 16~30초를 벗어났다는 경고가 나온 id(문구를 줄이거나 늘리라고 안내)
- `script.json`의 `review.needs_test_disclaimer`가 `true`인 id: "**영상 하단에 '인체적용시험 결과, 개인차 있음' 표기가 필요합니다. 자동으로 들어가지 않으니 업로드 전에 직접 확인해주세요.**"
- 사람이 확인할 것: 영상 속 발음(영문·긴 제품명), 자막이 영상과 어긋나지 않는지, 업로드 전 `review.notes`의 품절 표기

## 하지 않을 것

- 승인되지 않은 대본으로 TTS를 만들거나 렌더링하기
- 영상 업로드(이번 범위 제외)
- API 키를 출력하거나 파일에 쓰기
