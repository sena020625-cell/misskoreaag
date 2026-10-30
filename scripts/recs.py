"""매일 아침 소재 추천(제품 + 영상 링크 2~3개)을 작업 화면과 잇는 저장소.

예약 작업이 TikTok 트렌드에서 고른 제품을 add 로 쌓으면, 작업 화면의 '오늘의 추천'에 보이고
버튼 한 번으로 작업 요청(대기열)으로 넘어간다. 파일: <작업 폴더>/input/recommendations.json

  python recs.py add  --workdir . --product "제품명" --links 링크1 링크2 [링크3] [--brand ..] [--creators "@a, @b"] [--reason ..] [--check ..]
  python recs.py list --workdir .
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
URL_RE = re.compile(r"^https?://\S+$", re.I)
DEDUP_DAYS = 14
MAX_LINKS = 6


def path_of(workdir: Path) -> Path:
    p = workdir / "input" / "recommendations.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load(workdir: Path) -> list[dict]:
    p = path_of(workdir)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(workdir: Path, items: list[dict]) -> None:
    p = path_of(workdir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def uploaded_links(workdir: Path) -> set[str]:
    """업로드 완료로 표시한 작업에서 쓴 원본 영상 링크(주소의 ? 이하는 뺀다)."""
    used: set[str] = set()
    for sj in (workdir / "output").glob("*/*/script.json"):
        try:
            s = json.loads(sj.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if s.get("uploaded") is True:
            for l in (s.get("video_links") or [s.get("video_link", "")]):
                if l:
                    used.add(l.split("?")[0])
    return used


def add(workdir: Path, product: str, links: list[str], brand: str = "", creators: str = "",
        reason: str = "", check: str = "") -> tuple[bool, str]:
    product = product.strip()
    links = [l.strip() for l in links if l and l.strip()]
    if not product:
        return False, "제품명이 비어 있습니다"
    bad = [l for l in links if not URL_RE.match(l)]
    if bad or not links:
        return False, "영상 링크는 http로 시작하는 주소가 1개 이상 필요합니다"
    if len(links) > MAX_LINKS:
        return False, f"링크는 최대 {MAX_LINKS}개입니다"
    used = uploaded_links(workdir)
    if any(l.split("?")[0] in used for l in links):
        return False, "이미 업로드를 마친 영상 링크가 포함돼 있습니다"
    items = load(workdir)
    limit = datetime.now(KST) - timedelta(days=DEDUP_DAYS)
    for it in items:
        try:
            when = datetime.fromisoformat(it["created_at"])
        except (KeyError, ValueError):
            continue
        if it.get("product", "").strip().lower() == product.lower() and when >= limit:
            return False, f"최근 {DEDUP_DAYS}일 안에 이미 추천한 제품입니다"
    now = datetime.now(KST)
    items.append({"rid": f"r{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}", "date": now.strftime("%Y%m%d"),
                  "created_at": now.isoformat(timespec="seconds"), "product": product, "brand": brand.strip(),
                  "links": links, "creators": creators.strip(), "reason": reason.strip(), "check": check.strip(),
                  "status": "추천", "qid": ""})
    save(workdir, items)
    return True, "추가했습니다"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--workdir", default=".")
    a.add_argument("--product", required=True)
    a.add_argument("--links", nargs="+", required=True)
    a.add_argument("--brand", default="")
    a.add_argument("--creators", default="")
    a.add_argument("--reason", default="")
    a.add_argument("--check", default="")
    l = sub.add_parser("list")
    l.add_argument("--workdir", default=".")
    args = ap.parse_args()
    wd = Path(args.workdir).resolve()
    if args.cmd == "add":
        ok, msg = add(wd, args.product, args.links, args.brand, args.creators, args.reason, args.check)
        print(("추천 저장: " if ok else "건너뜀: ") + args.product + f" ({msg})")
        return 0 if ok else 1
    for it in load(wd):
        print(it["rid"], it["status"], it["product"], f"링크 {len(it['links'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
