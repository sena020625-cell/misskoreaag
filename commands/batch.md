---
description: input/batch.csv의 모든 줄에 대해 misskorea-script 스킬을 실행해 script.json/script.md와 summary.md를 만든다
argument-hint: "[--date YYYYMMDD] [--csv 경로] [--only id1,id2] [--overwrite]"
---

# /misskorea:batch

현재 작업 폴더의 `input/batch.csv`를 읽어, 줄마다 `misskorea-script` 스킬(정식 이름 `misskorea:misskorea-script`)을 실행하고 결과를 `output/YYYYMMDD/<id>/`에 저장한다. 마지막에 `output/YYYYMMDD/summary.md`를 만든다.

사용자 인자: `$ARGUMENTS`

## 인자

| 인자 | 기본값 | 의미 |
|---|---|---|
| `--date YYYYMMDD` | 오늘 날짜 | 출력 폴더 날짜 |
| `--csv 경로` | `input/batch.csv` | 입력 CSV |
| `--only id1,id2` | 전체 | 지정한 id만 처리 |
| `--overwrite` | 끔 | 이미 있는 `script.json`도 다시 생성 |

## 절차

### 1. CSV 읽기와 검증

1. CSV 파일을 UTF-8로 읽는다(BOM이 있으면 제거). 파일이 없으면 "작업 폴더에 `input/batch.csv`가 없습니다. 플러그인의 `templates/batch.csv`를 `input/`에 복사해 채워주세요."라고 알리고 멈춘다.
2. 헤더가 아래 8개 열을 모두 갖는지 확인한다. 열 순서는 달라도 되지만 이름은 같아야 한다.
   `id, 제품명, 공식몰URL, 원본링크, 원본메모, 훅, 강조포인트, 크리에이터`
3. 헤더 8개 중 하나라도 이름이 일치하지 않거나 `�`(U+FFFD) 문자가 보이면 CP949로 저장된 것으로 보고 처리를 멈춘다. "엑셀에서 'CSV UTF-8(쉼표로 분리)'로 다시 저장해주세요."라고 안내한다.
4. 줄마다 검사한다. 실패한 줄은 출력 폴더를 만들지 않고, 마무리 보고와 summary에 "무엇을 채워 다시 실행하라"는 안내를 함께 적는다(예: "공식몰URL을 채워 다시 실행하세요").
   - `id`, `제품명`, `공식몰URL`은 필수다. 비어 있으면 그 줄은 **실패**로 기록하고 다음 줄로 넘어간다. `공식몰URL`은 `http://` 또는 `https://`로 시작해야 한다.
   - `id`는 문자열 그대로 쓴다(`001`을 `1`로 바꾸지 않는다). 폴더 이름으로 쓸 수 없는 문자(`\ / : * ? " < > |` 와 공백)가 있으면 실패로 기록한다.
   - 같은 `id`가 두 번 나오면 두 번째부터 실패로 기록한다.
   - 완전히 빈 줄은 무시한다.
5. `--only`가 있으면 해당 id만 남긴다.

### 2. 건너뛸 줄 정하기

출력 폴더는 `output/<날짜>/<id>/`이다.

- 그 폴더에 `script.json`이 이미 있고 `--overwrite`가 없으면 **건너뜀**으로 기록한다. 사람이 고친 내용을 덮어쓰지 않기 위해서다.
- `--overwrite`가 있는데 기존 `script.json`의 `approved`가 `true`이면 그 id는 건너뛰고 "승인된 대본이라 덮어쓰지 않음"이라고 기록한다. 덮어쓰려면 사용자가 `approved`를 직접 `false`로 바꿔야 한다.

### 3. 스킬 실행

생성할 줄마다 `misskorea-script` 스킬을 실행한다. 입력은 CSV 값 그대로 넘기고, **출력 폴더 경로를 반드시 함께 넘긴다**(그러면 스킬이 파일로 저장한다).

- 서브에이전트(Agent 도구)를 쓸 수 있으면 **한 번에 최대 4줄씩** 병렬로 실행한다. 한 줄에 서브에이전트 하나다. 서브에이전트에게 줄 프롬프트에는 아래를 모두 넣는다.
  - 제품명, 공식몰URL, 원본링크, 원본메모, 훅, 강조포인트, 크리에이터(빈 값은 "없음"으로 표기)
  - 출력 폴더 경로 `output/<날짜>/<id>/`와 id
  - "Skill 도구로 `misskorea:misskorea-script`를 호출해 그 절차대로 수행하라(이름이 안 맞으면 `misskorea-script`로도 시도). 스킬을 호출할 수 없으면 플러그인 폴더(`${CLAUDE_PLUGIN_ROOT}`)의 `skills/misskorea-script/SKILL.md`를 읽어라. 그 경로가 없으면 `~/.claude/plugins` 아래에서 `**/skills/misskorea-script/SKILL.md`를 Glob으로 찾아라. 읽은 뒤에는 SKILL.md 안내대로 references 3개도 읽고 수행하라. 그래도 SKILL.md를 찾지 못하면 임의로 작성하지 말고 '스킬을 찾지 못함'이라고 실패로 보고하라."
  - "summary.md는 쓰지 말 것(메인 에이전트가 쓴다)."
  - "원본 영상을 내려받거나 스크래핑하지 말 것. 확인되지 않은 수치를 쓰지 말 것."
  - "저장이 끝나면 id, 1순위 제목, 검수 필요 여부(`needs_review`)만 한 줄로 보고하라."
- 서브에이전트를 쓸 수 없으면 줄을 하나씩 순서대로 직접 처리한다.
- 한 줄이 실패해도(웹 조회 실패, 저장 실패 등) 나머지는 계속 처리한다. 실패 사유는 summary에 적는다.

### 4. 결과 검증

줄마다 저장된 파일을 확인한다.

- `script.json`과 `script.md`가 둘 다 있다.
- `script.json`이 JSON으로 파싱된다.
- `versions`가 2개이고 각각 `lines`가 4~7줄이다.
- `selected_version`이 1, `approved`가 `false`다.
- `best_title.text`와 `top_title.line1`, `top_title.line2_green`이 비어 있지 않다.
- 버전마다 `est_seconds`가 `lines`를 이어 붙인 글자 수(공백 포함) ÷ 5.5와 소수 첫째 자리까지 일치하고, 16~30초 범위 안이다. 값만 틀렸으면 다시 생성하지 말고 계산한 값으로 고친다. 범위를 벗어나면 다시 생성 대상이다.

하나라도 어긋나면 그 id를 **다시 1회** 생성해 본다. 그래도 어긋나면 실패로 기록하고 사유를 적는다.

### 5. summary.md 만들기

`output/<날짜>/` 아래 **모든** `<id>/script.json`을 읽어 `output/<날짜>/summary.md`를 새로 만든다. 서브에이전트가 아니라 **메인 에이전트가** 쓴다. 이번 실행에서 건너뛴 id, 이전 실행에서 만든 id, 이번 실행에서 실패한 줄도 표에 포함한다. 형식은 아래와 같다.

```markdown
# 미쓰코리아 일괄 생성 요약 (YYYYMMDD)

이번 실행: 생성 N건 · 건너뜀 N건 · 실패 N건 / 표 전체 N건 중 검수 주의 N건

| id | 제품 | 1순위 제목 | 검수 필요 | 영상 | 승인 | 상태 |
|---|---|---|---|---|---|---|
| 001 | 제품명 | 1순위 제목 | 예: 확인 못 한 것 3건, 심의 1건 | 있음 | 대기 | 생성 |

## 실패한 줄
- id 004: 사유

## 다음 단계
1. 각 `<id>/script.md`를 읽고 `script.json`에서 `selected_version`(1 또는 2)과 문구를 고친다.
2. 검수가 끝난 id는 `script.json`의 `approved`를 `true`로 바꾼다.
3. `input/videos/<id>.mp4`가 없는 id는 영상 파일을 넣는다.
4. `/misskorea:render`를 실행한다.
```

- **건수 기준**: 맨 윗줄의 생성/건너뜀/실패는 **이번 실행** 기준이다. "검수 주의"는 표에 있는 모든 id 중 `needs_review`가 `true`인 건수다.
- **검수 필요**: `review.needs_review`가 `true`면 "예: " 뒤에 사유를 쉼표로 이어 붙인다. 사유는 아래 규칙으로 만든다. `false`면 "아니오". 사람은 모든 줄을 검수하므로 "아니오"도 검수 면제를 뜻하지 않는다.
  - `unverified` 항목이 있으면 `확인 못 한 것 N건`(N은 배열 길이)
  - `compliance_flags` 항목이 있으면 `심의 N건`
  - `needs_test_disclaimer`가 `true`면 `인체적용시험 표기 필요`
  - `notes`에 "품절" 또는 "SOLD OUT"이 있으면 `품절 표기`
- **영상**: `input/videos/<id>.mp4` 존재 여부(있음/없음). 실패한 줄도 확인한다.
- **승인**: `approved`가 `true`면 "승인", 아니면 "대기".
- **상태**: 생성 / 건너뜀(이미 있음) / 건너뜀(승인됨) / 기존(이전 실행) / 실패.
- 실패한 줄은 `script.json`이 없으므로 제품명만 CSV에서 가져와 표에 넣고 제목·검수 열은 `-`로 둔다.

### 6. 마무리 보고

대화에는 아래만 짧게 보고한다.

- 생성/건너뜀/실패 건수와 `output/<날짜>/summary.md` 경로
- 검수 주의가 필요한 id와 한 줄 사유
- 영상 파일이 없는 id
- 다음 단계(검수 후 `approved` 변경, `/misskorea:render`)

## 하지 않을 것

- 원본 영상(틱톡, 인스타그램 등) 다운로드, 스크래핑
- 사람이 고친 `script.json` 덮어쓰기(`--overwrite` 없이, 또는 승인된 id)
- CSV나 `script.json`에 없는 정보 지어내기
