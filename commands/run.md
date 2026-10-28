---
description: 영상 링크(여러 개)와 제품명만 붙여넣으면 Chrome으로 영상 내용을 읽고 대본·제목·설명란(출처 포함)까지 만든다
argument-hint: "링크 1줄에 1개 + 제품명: ... (제품이 여러 개면 빈 줄로 나눔)"
---

# /misskorea:run

영상 링크와 제품명을 받아, **Chrome으로 영상 내용을 읽고** `misskorea-script` 스킬로 대본 패키지를 만들어 `output/YYYYMMDD/<id>/`에 저장한다. 만든 뒤의 검수·음성·캡컷은 작업 화면(`start.bat`)에서 한다.

사용자 입력: `$ARGUMENTS`

## 입력 형식

링크는 한 줄에 하나, 제품명은 `제품명:` 줄. 제품이 여러 개면 빈 줄 또는 `---`로 나눈다.

```
https://www.tiktok.com/@albina/video/7532577426111515922
https://www.tiktok.com/@albina/video/7641618564272753941
제품명: 스킨1004 마다가스카르 센텔라 라이트 클렌징오일
```

선택 줄(있으면 쓴다): `공식몰: <주소>`, `훅: <첫 줄 문구>`, `강조: <꼭 넣을 특징>`, `메모: <영상에서 일어나는 일>`.

- 링크는 제품당 2~3개를 권한다(편집에서 섞는다). 1개여도 진행하되 "영상이 1개뿐"이라고 알린다.
- **제품명이 없는 블록은 만들지 않고** "제품명을 `제품명: ...` 줄로 적어 주세요"라고 알린 뒤 그 블록만 건너뛴다. 영상 속 제품을 추측하지 않는다.
- 링크가 하나도 없는 블록도 건너뛴다.
- 인자가 비어 있으면 위 형식을 보여주고 멈춘다.

## 절차

### 0. 준비

- 날짜는 오늘(한국 시간) `YYYYMMDD`. `output/<날짜>/` 아래 기존 폴더를 보고 id를 `001`부터 이어서 붙인다(3자리, 이미 있는 번호는 건너뜀).
- Python은 `python`을 먼저 시도하고 안 되면 `py -3`. 스크립트는 `${CLAUDE_PLUGIN_ROOT}/scripts/`(치환이 안 되면 `~/.claude/plugins` 아래에서 `**/scripts/source_credit.py`를 Glob으로 찾음).
- Chrome 도구가 필요하다. ToolSearch로 `mcp__claude-in-chrome__tabs_context_mcp`, `navigate`, `computer`, `javascript_tool`, `tabs_create_mcp`, `tabs_close_mcp`를 한 번에 불러온다. **불러올 수 없으면** 영상 분석 없이 진행하고(공식몰 정보와 링크 주소만 근거) 각 대본의 `review.unverified`에 "영상 내용을 확인하지 못함(Chrome 연동 필요)"을 넣고, 마무리 보고에 "Claude Code를 `--chrome`으로 켜고 Chrome 확장 'Claude in Chrome'에 로그인하면 영상 분석이 됩니다"라고 알린다.

### 1. 영상 읽기 (Chrome, 한 번에 한 개씩 차례로)

한 Chrome을 같이 쓰므로 **병렬로 하지 않는다**. 새 탭에서 작업하고 끝나면 닫는다. 영상은 **내려받지 않는다**. 페이지를 열어 읽기만 한다. 좋아요·팔로우·댓글 등 계정 활동, 로그인, CAPTCHA 우회는 하지 않는다(로그인이나 CAPTCHA가 뜨면 그 링크는 멈추고 "직접 확인 필요"로 기록한다).

TikTok 링크(`tiktok.com/@계정/video/숫자`)는 아래대로 한다.

1. `navigate`로 링크를 연다(주소의 `?q=...` 같은 검색 파라미터는 지워도 된다). **5초 기다린 뒤** 읽는다. 바로 읽으면 빈 화면이다.
2. `javascript_tool`로 영상 영역만 읽는다. **`get_page_text`는 쓰지 않는다**(옆 추천 영상의 문구가 섞여 들어온다).

   ```js
   const v=document.querySelector('video');
   const d=document.querySelector('[data-e2e="browse-video-desc"]')||document.querySelector('[data-e2e="video-desc"]');
   JSON.stringify({desc:d&&d.innerText.replace(/\n+/g,' '), dur:v&&v.duration,
     og:(document.querySelector('meta[property="og:description"]')||{}).content,
     user:(document.querySelector('[data-e2e="browse-username"]')||{}).innerText})
   ```
3. 장면 확인: `video.pause()` 후 `video.currentTime`을 길이의 0%, 25%, 50%, 75%, 95%로 옮기며 `screenshot`(scale 0.5)을 찍어 화면에서 일어나는 일을 적는다(무엇을 바르는지, 질감, 화면 속 글자, 용기·로고). **소리(대사)는 읽을 수 없다.** 안 들렸다고 지어내지 말고 "음성 미확인"으로 둔다.
4. 기록할 것: 계정(@핸들), 캡션 전문, 해시태그와 태그된 브랜드, 길이(초), 장면별 설명, 협찬·광고 표시가 영상 쪽에 보이는지(옆 추천 영상 것과 구분이 안 되면 "확인 못 함"), 제품 일치 여부.
5. **제품 일치 확인**: 제품명과 캡션·태그·화면 속 용기가 맞는지 본다. 맞는지 불확실하면 그 영상 항목에 "제품 일치 확인 필요"를 적는다(예: 캡션에 브랜드 태그만 있고 화면은 다른 질감). 맞지 않는다고 확신하면 그 링크는 대본 근거에서 빼고 보고에 적는다.

TikTok이 아닌 링크(Instagram, YouTube, X)는 같은 방식으로 페이지를 열어 캡션·계정·화면을 읽는다. 읽을 수 없으면 "직접 확인 필요"로 기록한다.

### 2. 대본 만들기

`Skill` 도구로 `misskorea:misskorea-script`를 호출한다(이름이 안 맞으면 `misskorea-script`로도 시도). 입력은 다음과 같이 채운다.

- 제품명: 입력의 `제품명:` 값 그대로
- 공식몰 상세페이지 URL: `공식몰:` 줄이 있으면 그 주소. 없으면 스킬 절차대로 WebSearch/WebFetch로 브랜드 **공식몰**을 찾아 쓴다. 찾지 못하면 해외 판매처로 보완하고 검수 메모에 적는다(WebFetch가 429면 잠시 뒤 다시 시도하거나 브라우저로 읽는다).
- 원본 링크: 첫 번째 링크. 원본 메모: 1단계에서 읽은 **영상별 장면 요약**(영상 1, 영상 2 ... 순서로, 확인한 것만)과 입력의 `메모:`, `훅:`, `강조:`
- 출력 폴더: `output/<날짜>/<id>/`

대본은 영상 여러 개를 섞어 한 편으로 편집한다고 가정하고 쓴다. 장면은 **확인한 것만** 묘사한다.

글자 수 규칙(유튜브 화면 안에 들어오게): 상단 타이틀은 **각 줄 10자 안팎, 최대 13자**로 쓰고 글자 수를 세어 확인한다. 자막은 편집 단계에서 한 화면에 10자씩 자동으로 나뉘므로 캡션 문장은 그대로 써도 된다.

### 3. 후처리 (대본을 저장한 뒤)

1. 출처 반영(여러 링크를 한 번에, 영상은 내려받지 않고 링크 주소만 읽는다):

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/source_credit.py" apply-many <id> --date <날짜> --workdir . --links "<링크1>" "<링크2>" ...
   ```
   설명란 맨 아래에 `📷I @계정`(여러 계정이면 쉼표로)과 링크마다 `🔗 원본:` 줄이 들어가고 `script.json`에 `video_links`가 기록된다. 계정을 알 수 없으면 `needs_review`가 켜진다.
2. `script.json`에 `video_analysis` 배열을 추가한다. 영상마다 `{"link","creator","duration_sec","caption","scenes":["..."],"notes":"제품 일치 확인 필요 등"}`. (검수 화면과 편집에서 참고한다.)
3. 영상 분석에서 나온 "확인 못 한 것"(음성 미확인, 제품 일치 확인 필요, 협찬 표기 불명 등)을 `review.unverified`에 추가하고 `script.md`의 "확인 못 한 것"에도 반영한다.
4. 검증(배치와 같은 기준): `script.json`이 파싱된다, `versions`가 2개이고 각 `lines`가 4~7줄, `selected_version` 1, `approved` false, `est_seconds`가 `lines`를 이어 붙인 글자 수 ÷ 7.5(소수 첫째 자리)와 같고 16~30초 안. 값만 틀렸으면 계산해서 고치고, 범위를 벗어나면 그 id를 1회 다시 만든다. 그래도 안 되면 실패로 알린다.
5. **사용 허락은 묻거나 기록하지 않는다.** 허락받은 영상만 수급하는 것이 이 팀의 전제이며, 허락은 사람이 따로 관리한다.

### 4. 마무리 보고 (짧게)

제품마다 한 줄: `id · 제품명 · 1순위 제목 · 영상 N개 읽음 · 검수 주의 N건`. 이어서

- 영상을 읽지 못했거나 제품 일치가 불확실한 링크와 사유
- 공식몰을 찾지 못해 해외 판매처로 대신한 경우
- 다음 단계: "`start.bat`을 더블클릭해 작업 화면에서 검수 → 영상 파일 넣기 → 음성 → 캡컷"

## 하지 않을 것

- 영상 내려받기, 스크래핑, 다운로더 사이트 이용. 파일은 제작자가 준 것을 작업 화면에서 넣는다
- 좋아요·팔로우·댓글, 로그인, CAPTCHA 우회
- 읽지 못한 소리·장면·수치를 지어 쓰기, 제품명 추측
- 사람이 고친 기존 `script.json` 덮어쓰기(id는 항상 새 번호)
