# 산출물 양식

## 폴더

`/misskorea:batch`가 지정하는 폴더: `output/YYYYMMDD/<id>/`

```
script.json   # 기계용. 이후 단계(tts, subtitle, render)가 읽는다
script.md     # 사람 검수용
```

## script.json 스키마

```json
{
  "id": "001",
  "product": "히어로 올데이 플럼핑 틴트",
  "brand": "에이프릴스킨",
  "brand_en": "APRILSKIN",
  "product_line_en": "Hero Allday Plumping Lip Stain",
  "creator": "",
  "source_url": "https://...",
  "video_link": "",
  "selected_version": 1,
  "approved": false,
  "versions": [
    {
      "version": 1,
      "lines": ["첫 줄", "둘째 줄", "..."],
      "est_seconds": 22.5
    },
    {
      "version": 2,
      "lines": ["..."],
      "est_seconds": 24.0
    }
  ],
  "alt_hooks": ["대체 훅 1", "대체 훅 2", "대체 훅 3"],
  "titles": ["제목1", "제목2", "제목3", "제목4"],
  "best_title": { "text": "제목2", "reason": "한 줄 이유" },
  "top_title": { "line1": "흰 글씨 줄", "line2_green": "초록 박스 줄" },
  "description": "설명란 전문(해시태그와 크리에이터 줄 포함, 줄바꿈은 \\n)",
  "review": {
    "sources": [
      { "label": "공식몰 상세페이지", "url": "https://...", "used_for": "성분, 사용법" }
    ],
    "unverified": ["확인 못 한 것 1"],
    "compliance_flags": [
      { "text": "완벽하게", "issue": "절대 표현", "fix": "깔끔하게" }
    ],
    "needs_test_disclaimer": false,
    "needs_review": true,
    "notes": "기타 메모(품절 표기, 발음 확인 필요 등)"
  }
}
```

규칙:

- `selected_version`은 1로 시작한다. 사람이 1 또는 2로 바꾼다.
- `approved`는 항상 `false`로 시작한다. 사람이 검수 후 `true`로 바꾼다.
- `versions[].lines`가 TTS 입력이다. 줄 하나가 자막과 타이밍의 기본 단위가 된다.
- `needs_review`: `unverified`, `compliance_flags`, `needs_test_disclaimer` 중 하나라도 해당되거나 품절 표기가 있으면 `true`. 해당 항목이 없어도 사람 검수는 항상 거치므로, 이 값은 "특히 주의해서 볼 것이 있는가"를 뜻한다.
- 모르는 값(크리에이터, 영문 제품 라인 등)은 빈 문자열로 둔다. 지어내지 않는다.
- `permission`({"granted": true/false, "note": "허락 근거"})과 `video_file`(영상링크로 받은 경우 경로, 출처 주소, 크기, 해시, 시각)은 `/misskorea:batch`가 `scripts/permission.py`, `scripts/fetch_source.py`로 기록한다. 스킬은 이 값을 만들거나 바꾸지 않는다. `permission`이 근거와 함께 `granted: true`가 아니면 tts.py와 render.py가 처리하지 않는다.
- `source`, 설명란 맨 아래의 `📷I @핸들`과 `🔗 원본: 주소` 줄, `review.sources`의 "원본 영상 출처" 항목은 `/misskorea:batch`가 대본을 만든 뒤 `scripts/source_credit.py`로 자동으로 채운다. 스킬은 이 값을 직접 만들지 않는다(크리에이터를 입력받지 못했다면 기존 규칙대로 `📷I` 줄을 빼고 검수 메모에 알린다).
- 파일은 UTF-8, 들여쓰기 2칸, 한글을 이스케이프하지 않는다.

## script.md 양식

```markdown
# [id] [제품명] ([브랜드])

- 상태: 검수 대기 | 선택 버전: 1 | 주의 필요: 예/아니오
- 공식몰: [URL]

## 상단 타이틀
- 1줄(흰 글씨): ...
- 2줄(초록 박스): ...

## TTS 캡션 버전 1 (약 N초)
1. ...
2. ...

## TTS 캡션 버전 2 (약 N초)
1. ...

## 첫 줄 대체 훅
1. ...
2. ...
3. ...

## 제목 후보
1. ...
2. ...
3. ...
4. ...
- **1순위:** [제목], 이유: ...

## 설명란
[설명란 전문, 코드블록 없이 그대로]

## 검수 메모
### 사용한 근거
- [라벨]: [URL] (사용: ...)
### 확인 못 한 것
- ...  (없으면 "없음")
### 심의 위험 표현
- "..." → "..." (이유)  (없으면 "없음")
### 표기 필요 사항
- 영상 하단에 '인체적용시험 결과, 개인차 있음' 표기 필요  (해당 시에만)
```

## 설명란 템플릿

```
[훅 문장]

바로 [브랜드]의 [제품명]인데요!
[핵심 특징 1~2줄]
[해외 반응 또는 인기 한 줄]✨

[해시태그]

📷I [원본 크리에이터]
```

- `[훅 문장]`은 선택한 캡션 첫 줄을 쓰거나 비슷한 톤으로 쓴다.
- `[해외 반응 또는 인기 한 줄]`은 근거가 확인된 경우에만 쓴다. 근거가 없으면 그 줄은 빼고(✨는 앞줄 끝에 붙인다) 검수 메모에 적는다.
- 크리에이터가 비어 있으면 `📷I` 줄을 통째로 빼고 검수 메모에 "크리에이터 미기재, 원본 출처 표기 필요"를 적는다.

## 해시태그 규칙

순서: 한글 브랜드 → 영문 브랜드 → 영문 제품 라인 → `#kbeauty` → 카테고리·고민 태그(한글) → 해외에서 많이 쓰는 영문 태그(있으면)

- 영문 제품 라인은 공백 없이 붙인다: `#HeroAlldayPlumpingLipStain`
- 한 줄에 공백으로 구분한다. 총 7~12개 정도.
- 근거 없는 효능 태그(심의 금지 표현)는 쓰지 않는다.

예: `#에이프릴스킨 #APRILSKIN #HeroAlldayPlumpingLipStain #lipstain #kbeauty #립틴트 #립타투`

## summary.md 행 (참고: /misskorea:batch 가 만든다)

| id | 제품 | 1순위 제목 | 검수 필요 |
|---|---|---|---|
| 001 | ... | ... | 예/아니오 (사유 요약) |
