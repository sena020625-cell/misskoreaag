"""작업 요청 대기열. 작업 화면이 요청을 쌓고, Claude(예약 작업 또는 /misskorea:queue)가 하나씩 꺼내 처리한다.

요청 한 건 = input/queue/<qid>.json 파일 하나. 상태: 대기 → 진행중 → 완료 | 실패 (대기 상태에서는 취소 가능)

  python jobqueue.py add  --workdir . --text "<링크들 + 제품명: ...>"   요청을 쌓는다(화면과 같은 규칙)
  python jobqueue.py next --workdir .                                    가장 오래된 대기 건을 진행중으로 바꾸고 JSON 으로 출력 (없으면 종료코드 3)
  python jobqueue.py done <qid> --date YYYYMMDD --id 001 [--message ..]  완료로 표시
  python jobqueue.py fail <qid> --message "사유"                         실패로 표시
  python jobqueue.py list --workdir .                                    목록
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
STALE_MINUTES = 45          # 진행중인 채로 이 시간이 지나면 멈춘 것으로 보고 실패 처리
MAX_LINKS = 6
STATUSES = ("대기", "진행중", "완료", "실패", "취소")
URL_RE = re.compile(r"^https?://\S+$", re.I)
FIELD_RE = re.compile(r"^\s*(제품명|공식몰|훅|강조|메모)\s*[:：]\s*(.+?)\s*$")


def now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(KST).strftime("%Y%m%d")


def queue_dir(workdir: Path) -> Path:
    d = workdir / "input" / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse_request(text: str) -> tuple[list[dict], list[str]]:
    """붙여 넣은 글을 제품 단위로 나눈다. (요청 목록, 오류 목록)

    링크는 한 줄에 하나, 제품명은 '제품명: ...' 줄. 제품이 여러 개면 빈 줄 또는 '---'로 나눈다.
    """
    blocks, cur = [], []
    for raw in (text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or re.fullmatch(r"-{3,}", line):
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)

    items, errors = [], []
    for n, block in enumerate(blocks, 1):
        item = {"product": "", "links": [], "official": "", "hook": "", "emphasis": "", "memo": ""}
        for line in block:
            m = FIELD_RE.match(line)
            if m:
                key = {"제품명": "product", "공식몰": "official", "훅": "hook", "강조": "emphasis", "메모": "memo"}[m.group(1)]
                item[key] = m.group(2)
            elif URL_RE.match(line):
                if line not in item["links"]:
                    item["links"].append(line)
            else:
                errors.append(f"{n}번째 묶음: 알 수 없는 줄 '{line[:40]}' (링크는 http로 시작, 나머지는 '제품명: ...' 형식)")
        label = f"{n}번째 묶음" if len(blocks) > 1 else "입력"
        if not item["product"]:
            errors.append(f"{label}: '제품명: ...' 줄이 없습니다. 제품명은 직접 적어 주세요")
            continue
        if not item["links"]:
            errors.append(f"{label}({item['product']}): 영상 링크가 없습니다")
            continue
        if len(item["links"]) > MAX_LINKS:
            errors.append(f"{label}({item['product']}): 링크가 너무 많습니다(최대 {MAX_LINKS}개)")
            continue
        if item["official"] and not URL_RE.match(item["official"]):
            errors.append(f"{label}({item['product']}): 공식몰은 http로 시작하는 주소여야 합니다")
            continue
        items.append(item)
    if not blocks:
        errors.append("입력이 비어 있습니다")
    return items, errors


def _write(path: Path, data: dict) -> None:
    data["updated_at"] = now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def add(workdir: Path, text: str) -> tuple[list[dict], list[str]]:
    items, errors = parse_request(text)
    out = []
    for it in items:
        qid = f"q{datetime.now(KST).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
        data = {"qid": qid, "status": "대기", "created_at": now(), **it, "date": "", "id": "", "message": ""}
        _write(queue_dir(workdir) / f"{qid}.json", data)
        out.append(data)
        time.sleep(0.01)
    return out, errors


def items(workdir: Path) -> list[dict]:
    out = []
    for p in sorted(queue_dir(workdir).glob("q*.json")):
        try:
            out.append(_read(p))
        except (OSError, ValueError):
            continue
    return out


def reap_stale(workdir: Path) -> None:
    limit = datetime.now(KST) - timedelta(minutes=STALE_MINUTES)
    for p in queue_dir(workdir).glob("q*.json"):
        try:
            d = _read(p)
            if d.get("status") == "진행중" and datetime.fromisoformat(d.get("claimed_at", d["updated_at"])) < limit:
                d["status"] = "실패"
                d["message"] = f"{STALE_MINUTES}분 넘게 끝나지 않아 멈춘 것으로 처리했습니다. 다시 요청해 주세요"
                _write(p, d)
        except (OSError, ValueError, KeyError):
            continue


def claim_next(workdir: Path) -> dict | None:
    reap_stale(workdir)
    if any(i.get("status") == "진행중" for i in items(workdir)):
        return None  # 한 번에 한 건만 처리(Chrome 을 같이 쓰므로)
    for p in sorted(queue_dir(workdir).glob("q*.json")):
        try:
            d = _read(p)
        except (OSError, ValueError):
            continue
        if d.get("status") == "대기":
            d["status"] = "진행중"
            d["claimed_at"] = now()
            d["date"] = today()
            _write(p, d)
            return d
    return None


def finish(workdir: Path, qid: str, status: str, message: str = "", date: str = "", item_id: str = "") -> dict:
    p = queue_dir(workdir) / f"{qid}.json"
    if not re.fullmatch(r"q[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", qid) or not p.exists():
        raise SystemExit(f"요청을 찾을 수 없습니다: {qid}")
    d = _read(p)
    d["status"] = status
    d["message"] = message
    if date:
        d["date"] = date
    if item_id:
        d["id"] = item_id
    _write(p, d)
    return d


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add", "next", "list"):
        s = sub.add_parser(name)
        s.add_argument("--workdir", default=".")
        if name == "add":
            s.add_argument("--text", required=True)
    d = sub.add_parser("done")
    d.add_argument("qid")
    d.add_argument("--workdir", default=".")
    d.add_argument("--date", required=True)
    d.add_argument("--id", required=True)
    d.add_argument("--message", default="")
    f = sub.add_parser("fail")
    f.add_argument("qid")
    f.add_argument("--workdir", default=".")
    f.add_argument("--message", required=True)
    a = ap.parse_args()
    wd = Path(a.workdir).resolve()

    if a.cmd == "add":
        out, errors = add(wd, a.text)
        for e in errors:
            print("오류:", e)
        for o in out:
            print("접수:", o["qid"], o["product"], f"(링크 {len(o['links'])}개)")
        return 0 if out and not errors else 1
    if a.cmd == "next":
        got = claim_next(wd)
        if not got:
            return 3
        print(json.dumps(got, ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "done":
        finish(wd, a.qid, "완료", a.message, a.date, a.id)
        return 0
    if a.cmd == "fail":
        finish(wd, a.qid, "실패", a.message)
        return 0
    for i in items(wd):
        print(i["qid"], i["status"], i["product"], i.get("message", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
