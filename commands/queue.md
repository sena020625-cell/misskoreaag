---
description: 작업 화면에서 접수한 요청(링크+제품명)을 대기열에서 꺼내 /misskorea:run 절차로 하나씩 처리한다
argument-hint: "[--max N] (기본 3건)"
---

# /misskorea:queue

작업 화면의 "새 작업 요청"으로 접수된 건을 `input/queue/`에서 꺼내, `/misskorea:run`과 같은 절차로 처리한다. 예약 작업이 이 명령을 주기적으로 실행하거나, 사람이 직접 실행한다.

사용자 입력: `$ARGUMENTS`

## 절차

작업 폴더는 현재 폴더(`.env`, `input/`, `output/`이 있는 곳)다. 안내가 따로 없으면 현재 폴더에서 한다. Python은 `python`을 먼저, 안 되면 `py -3`. 스크립트 위치는 `${CLAUDE_PLUGIN_ROOT}/scripts/`(치환이 안 되면 `~/.claude/plugins/cache/misskorea-marketplace/misskorea/*/scripts/jobqueue.py`를 Glob으로 찾아 가장 새 버전 폴더를 쓴다).

1. **요청 꺼내기:** 

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/jobqueue.py" next --workdir .
   ```
   - 종료코드 3이면 대기 중인 요청이 없거나 이미 진행 중인 건이 있다는 뜻이다. **한 줄("대기 요청 없음")만 보고하고 끝낸다.** 다른 작업은 하지 않는다.
   - 성공하면 JSON이 나온다: `qid`, `product`, `links`, `official`, `hook`, `emphasis`, `memo`, `date`. 이 요청은 이미 `진행중`으로 바뀌었다.
2. **처리:** `/misskorea:run`(`commands/run.md`)의 0~3단계를 이 요청 하나에 대해 그대로 수행한다.
   - 입력값은 JSON의 값을 쓴다: 제품명=`product`, 링크=`links`, `공식몰:`=`official`, `훅:`=`hook`, `강조:`=`emphasis`, `메모:`=`memo`(비어 있으면 없는 것으로).
   - 날짜 폴더는 JSON의 `date`. id는 `output/<date>/` 아래 기존 번호를 보고 `001`부터 이어서 붙인다.
3. **결과 기록:**
   - 성공(대본 저장과 검증까지 끝남): `python ".../jobqueue.py" done <qid> --workdir . --date <date> --id <id> --message "영상 N개 읽음, 검수 주의 N건"`
   - 실패(Chrome 연동 불가, 링크를 열 수 없음, 대본 검증 2회 실패 등): `python ".../jobqueue.py" fail <qid> --workdir . --message "<사유, 사람이 읽을 한 줄>"`. 사유에는 고치는 방법을 포함한다(예: "Chrome을 켜고 Claude in Chrome에 로그인한 뒤 다시 요청하세요").
   - **어떤 경우에도 요청을 `진행중`으로 남겨 두지 않는다.** 중간에 멈추게 되면 `fail`로 표시한다.
4. **다음 요청:** `--max`(기본 3) 건까지 1~3을 반복한다. 다음 `next`가 종료코드 3이면 끝낸다.
5. **보고(짧게):** 처리한 건마다 `qid · 제품명 · 완료/실패 · id`. 끝에 "작업 화면에서 검수하세요."

## 하지 않을 것

- 대기열 파일(`input/queue/*.json`)을 직접 고치지 않는다. 항상 `jobqueue.py`로 상태를 바꾼다
- `/misskorea:run`이 하지 않는 것을 하지 않는다(영상 내려받기, 계정 활동, 로그인 우회, 소리·제품명 추측)
- 대기 요청이 없을 때 아무 작업도 하지 않는다
