# 작업 요청 처리 예약 작업 (각자 컴퓨터에서 한 번 설정)

작업 화면의 "새 작업 요청"으로 접수된 건을 Claude 앱이 가져가 처리하게 하는 예약 작업입니다. 각자 컴퓨터의 Claude 앱, 각자 계정의 크레딧으로 돌아갑니다.

## 설정 방법

Claude 앱의 사이드바 **Scheduled**에서 새 예약 작업을 만들거나, Claude에게 "아래 내용으로 예약 작업을 만들어줘"라고 요청합니다.

- 이름: `미쓰코리아 작업 요청 처리`
- 반복: **10분마다, 09~21시** (cron: `*/10 9-21 * * *`). 접수 후 시작까지 평균 5분 안팎입니다.
- 내용: 아래 프롬프트에서 **작업 폴더 경로만 본인 것으로 바꿔서** 붙여 넣습니다.

## 알아 둘 점

- **크레딧:** 대기 요청이 없으면 한 줄만 보고하고 끝나지만, 10분마다 짧은 세션이 시작됩니다. 부담되면 간격을 늘리거나(예: `*/20`), 예약 작업을 꺼 두고 필요할 때 Claude 앱에서 `/misskorea:queue`를 직접 실행하세요(대기열을 한 번에 처리).
- **조건:** Claude 앱이 켜져 있고 Chrome이 켜져 있어야 합니다(영상을 Chrome으로 읽습니다). 앱이 꺼져 있으면 다음에 앱을 열 때 처리됩니다.
- **한 번에 한 건:** Chrome 하나를 같이 쓰므로 요청은 차례로 처리됩니다.
- 처리 중에 Chrome 창이 잠깐 열리고 닫힐 수 있습니다.

## 프롬프트

```
너는 유튜브 쇼츠 채널 '미쓰코리아'의 작업 요청 처리 담당이다. 작업 화면에서 접수된 요청을 대기열에서 꺼내 처리한다. **대기 요청이 없으면 아무것도 하지 말고 한 줄만 보고하고 끝낸다.**

작업 폴더: <여기에 본인 작업 폴더 전체 경로> (모든 명령은 이 폴더에서 실행한다. 대기열은 이 폴더의 input/queue/ 이다.)

1. Python 은 `python` 을 먼저, 안 되면 `py -3`. 스크립트 폴더를 찾는다: `~/.claude/plugins/cache/misskorea-marketplace/misskorea/*/scripts/jobqueue.py` 를 Glob 으로 찾아 가장 새 버전 폴더를 쓴다. 이 폴더를 SCRIPTS 라 부른다. 같은 방식으로 명령 문서 폴더(`commands/`)와 스킬 폴더(`skills/misskorea-script/`)도 찾는다.
2. 작업 폴더에서 먼저 실행한다: `python SCRIPTS/jobqueue.py next --workdir .`
   - 종료코드 3(출력 없음)이면 "대기 요청 없음" 한 줄만 보고하고 **즉시 끝낸다.** 다른 어떤 작업도 하지 않는다.
   - 성공하면 JSON(qid, product, links, official, hook, emphasis, memo, date)이 나온다. 그 요청은 이미 '진행중'이다.
3. 명령 문서 `commands/queue.md` 와 `commands/run.md` 를 읽고 그 절차대로 이 요청 하나를 처리한다(Chrome 으로 영상 읽기, 공식몰 확인, misskorea-script 스킬로 대본 생성(Skill 도구로 `misskorea:misskorea-script`를 호출하고, 안 되면 스킬 폴더의 SKILL.md 와 references 3개를 읽고 수행), `jobqueue.py` 와 같은 폴더의 `source_credit.py apply-many` 로 출처 반영, `video_analysis` 와 검수 메모 반영, 검증). 입력값은 JSON 의 값을 쓰고 출력 폴더는 `output/<date>/<id>/` (id 는 그 날짜 폴더의 기존 번호 다음 3자리)이다.
4. 결과를 반드시 기록한다. 성공: `python SCRIPTS/jobqueue.py done <qid> --workdir . --date <date> --id <id> --message "영상 N개 읽음, 검수 주의 N건"`. 실패: `python SCRIPTS/jobqueue.py fail <qid> --workdir . --message "<사람이 읽을 사유와 고치는 방법 한 줄>"`. 요청을 '진행중'으로 남겨 두지 않는다.
5. 한 번 실행에 최대 2건까지 처리하고, 다음 `next` 가 종료코드 3이면 끝낸다. 마지막에 처리한 건마다 한 줄(qid · 제품명 · 완료/실패 · id)로 보고한다.

지켜야 할 것: 영상 내려받기와 스크래핑 금지(링크를 열어 읽기만), 좋아요·팔로우·댓글·로그인·CAPTCHA 우회 금지, 읽지 못한 소리와 확인하지 못한 수치와 제품명 추측 금지, 대기열 파일을 직접 고치지 말고 항상 jobqueue.py 로 상태를 바꾼다.
```
