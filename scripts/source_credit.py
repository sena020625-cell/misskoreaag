"""출처 자동 표기: 원본 링크에서 크리에이터(@핸들)와 원본 주소를 뽑아 script.json/script.md 의 설명란에 넣는다.

영상을 내려받지 않는다. 링크 주소만 읽는다(TikTok 단축 링크는 원래 주소를 알아내려고 리다이렉트만 따라간다).
출처 표기는 사용 허락을 대신하지 않는다. 허락은 사람이 따로 확인해야 한다.

사용 예 (작업 폴더에서 실행):
    python source_credit.py parse "https://www.tiktok.com/@someone/video/7300000000000000000"
    python source_credit.py apply 001 --date 20261026 --link "<원본링크>" --creator "<크리에이터>"
    python source_credit.py apply 001            # script.json 의 video_link 를 사용
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urljoin, urlsplit

from common import ScriptError, configure_stdout, item_dir, load_script, today

TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}
TIKTOK_SHORT_HOSTS = {"vm.tiktok.com", "vt.tiktok.com"}
_TT_VIDEO = re.compile(r"^/@([A-Za-z0-9._]{1,40})/(video|photo)/(\d{5,25})")
_IG_KINDS = {"reel", "reels", "p", "tv"}
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SOURCE_LABEL = "원본 영상 출처"
NOTE_PREFIX = "[출처]"


@dataclass
class SourceInfo:
    platform: str = ""
    handle: str = ""      # '@핸들' 또는 빈 문자열
    url: str = ""         # 추적 값을 뺀 원본 주소
    original: str = ""    # 입력한 링크 그대로
    status: str = "none"  # ok(핸들 확인) | manual(사람이 확인해야 함) | none(링크 없음)
    note: str = ""


Resolver = Callable[[str], Optional[str]]


def resolve_redirect(url: str, max_hops: int = 5) -> Optional[str]:
    """TikTok 단축 링크의 리다이렉트를 따라가 영상 주소를 돌려준다. 본문은 받지 않고, TikTok 주소로만 이동한다."""
    import requests
    from urllib.parse import urlsplit as _split

    current = url
    for _ in range(max_hops):
        host = (_split(current).hostname or "").lower()
        if host not in TIKTOK_HOSTS | TIKTOK_SHORT_HOSTS:
            return None
        try:
            resp = requests.get(current, allow_redirects=False, timeout=10, stream=True, headers={"User-Agent": _UA})
        except requests.RequestException:
            return None
        try:
            status, location = resp.status_code, resp.headers.get("Location")
        finally:
            resp.close()
        if status in (301, 302, 303, 307, 308) and location:
            current = urljoin(current, location)
            if _TT_VIDEO.match(_split(current).path):
                return current
            continue
        return None
    return None


def _clean(parts) -> str:
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _manual(platform: str, original: str, url: str, note: str) -> SourceInfo:
    return SourceInfo(platform=platform, original=original, url=url, status="manual", note=note)


def parse_source_link(link: str, resolver: Optional[Resolver] = resolve_redirect) -> SourceInfo:
    """링크에서 플랫폼, 핸들, 정리된 원본 주소를 알아낸다. 알 수 없으면 status='manual' 로 표시한다."""
    raw = (link or "").strip()
    if not raw:
        return SourceInfo(note="원본 링크가 없습니다.")
    candidate = raw if "://" in raw else "https://" + raw
    try:
        parts = urlsplit(candidate)
        host = (parts.hostname or "").lower()
    except ValueError:
        return _manual("", raw, "", "링크 형식이 올바르지 않습니다.")
    if "." not in host:
        return _manual("", raw, "", "링크 형식이 올바르지 않습니다.")
    segs = [s for s in parts.path.split("/") if s]

    if host in TIKTOK_HOSTS or host in TIKTOK_SHORT_HOSTS:
        m = _TT_VIDEO.match(parts.path)
        if m:
            handle, kind, vid = m.groups()
            return SourceInfo("TikTok", f"@{handle}", f"https://www.tiktok.com/@{handle}/{kind}/{vid}", raw, "ok")
        if (host in TIKTOK_SHORT_HOSTS or (segs and segs[0] == "t")) and resolver is not None:
            resolved = resolver(f"https://{host}{parts.path}")
            if resolved:
                info = parse_source_link(resolved, resolver=None)
                info.original = raw
                return info
            return _manual("TikTok", raw, _clean(parts),
                           "단축 링크의 원래 주소를 알아내지 못했습니다. 영상 전체 주소(tiktok.com/@계정/video/...)로 바꿔 적거나 직접 확인하세요.")
        return _manual("TikTok", raw, _clean(parts), "TikTok 링크에서 계정을 찾지 못했습니다. 영상 주소가 맞는지 확인하세요.")

    if host in {"instagram.com", "www.instagram.com"}:
        if len(segs) >= 3 and segs[1] in _IG_KINDS:
            return SourceInfo("Instagram", f"@{segs[0]}", f"https://www.instagram.com/{segs[0]}/{segs[1]}/{segs[2]}/", raw, "ok")
        if len(segs) >= 2 and segs[0] in _IG_KINDS:
            return _manual("Instagram", raw, f"https://www.instagram.com/{segs[0]}/{segs[1]}/",
                           "인스타그램 링크에는 계정 이름이 없어 직접 확인해야 합니다.")
        return _manual("Instagram", raw, _clean(parts), "인스타그램 링크에서 계정을 찾지 못했습니다.")

    if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
        if len(segs) >= 3 and segs[1] == "status" and segs[0] not in {"i", "home", "search"}:
            return SourceInfo("X", f"@{segs[0]}", f"https://x.com/{segs[0]}/status/{segs[2]}", raw, "ok")
        return _manual("X", raw, _clean(parts), "X 링크에서 계정을 찾지 못했습니다.")

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        if segs and segs[0].startswith("@"):
            return SourceInfo("YouTube", segs[0], _clean(parts), raw, "ok")
        url = _clean(parts)
        if parts.path == "/watch":
            vid = parse_qs(parts.query).get("v", [""])[0]
            url = f"{url}?v={vid}" if vid else url
        return _manual("YouTube", raw, url, "유튜브 영상 링크에는 채널 이름이 없어 직접 확인해야 합니다.")

    return _manual("기타", raw, _clean(parts), "지원하지 않는 사이트라 크리에이터를 직접 확인해야 합니다.")


# ---- script.json / script.md 에 반영 ----

def build_description(description: str, creator: str, url: str) -> str:
    """설명란에서 기존 출처 줄(📷, 🔗 원본)을 걷어내고 맨 아래에 새 출처 줄을 붙인다. 여러 번 실행해도 결과가 같다."""
    kept = [ln for ln in description.split("\n") if not ln.startswith(("📷", "🔗 원본"))]
    text = "\n".join(kept).rstrip()
    extra = []
    if creator:
        extra.append(f"📷I {creator}")
    if url:
        extra.append(f"🔗 원본: {url}")
    return text + ("\n\n" + "\n".join(extra) if extra else "")


def _clean_notes(notes: str, creator_known: bool, new_sentence: str) -> str:
    sentences = [s for s in re.split(r"(?<=[.])\s+", notes.strip()) if s]
    sentences = [s for s in sentences if not s.startswith(NOTE_PREFIX)]
    if creator_known:
        sentences = [s for s in sentences if "크리에이터 미기재" not in s]
    if new_sentence:
        sentences.append(f"{NOTE_PREFIX} {new_sentence}")
    return " ".join(sentences)


def _update_markdown(md: str, description: str, line: str, creator_known: bool) -> str:
    md = re.sub(r"(## 설명란\n)(.*?)(\n## )", lambda m: m.group(1) + description + "\n" + m.group(3), md, count=1, flags=re.S)
    lines = md.split("\n")
    lines = [ln for ln in lines if not ln.startswith("- 원본 출처:")
             and not (creator_known and ln.startswith("- 크리에이터 미기재"))]
    md = "\n".join(lines)
    if "### 기타\n" in md:
        return md.replace("### 기타\n", f"### 기타\n{line}\n", 1)
    return md.rstrip("\n") + f"\n\n### 기타\n{line}\n"


def apply_source(out_dir: Path, link: str, csv_creator: str, resolver: Optional[Resolver] = resolve_redirect) -> dict:
    """out_dir 의 script.json(과 script.md)에 출처를 반영하고 결과 요약을 돌려준다."""
    json_path, md_path = out_dir / "script.json", out_dir / "script.md"
    script = load_script(json_path)
    link = (link or script.get("video_link") or "").strip()
    csv_creator = (csv_creator or "").strip()
    info = parse_source_link(link, resolver=resolver)
    if info.status == "none" and not csv_creator:
        return {"status": "skipped", "message": "원본 링크와 크리에이터가 모두 없어 건너뜀"}

    creator = csv_creator or info.handle or script.get("creator", "")
    mismatch = ""
    if csv_creator and info.handle and csv_creator.lstrip("@").lower() != info.handle.lstrip("@").lower():
        mismatch = f"CSV의 크리에이터({csv_creator})와 링크의 계정({info.handle})이 다릅니다. 확인하세요."

    if info.status == "ok" and not mismatch:
        review_sentence, md_line = "", f"- 원본 출처: {info.platform} {info.handle}, {info.url} (링크에서 자동 추출, 사용 허락은 별도 확인)"
    else:
        reason = mismatch or info.note or "크리에이터를 확인하지 못했습니다."
        review_sentence, md_line = f"원본 출처를 직접 확인하세요. {reason}", f"- 원본 출처: 직접 확인 필요. {reason}"

    script["video_link"] = link or script.get("video_link", "")
    script["creator"] = creator
    script["source"] = {k: v for k, v in asdict(info).items() if k != "original"}
    if mismatch:
        script["source"]["note"] = mismatch
    script["description"] = build_description(script.get("description", ""), creator, info.url)
    review = script.setdefault("review", {})
    sources = [s for s in review.get("sources", []) if s.get("label") != SOURCE_LABEL]
    if info.url:
        used = f"설명란 출처 표기 ({creator or '크리에이터 확인 필요'})"
        sources.append({"label": SOURCE_LABEL, "url": info.url, "used_for": used})
    review["sources"] = sources
    review["notes"] = _clean_notes(review.get("notes", ""), bool(creator), review_sentence)
    if review_sentence:
        review["needs_review"] = True
    json_path.write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if md_path.is_file():
        md = _update_markdown(md_path.read_text(encoding="utf-8"), script["description"], md_line, bool(creator))
        md_path.write_text(md, encoding="utf-8")

    status = "ok" if (info.status == "ok" and not mismatch) else "manual"
    return {"status": status, "creator": creator, "platform": info.platform, "url": info.url,
            "message": (f"{creator} ({info.platform}) 를 설명란에 반영" if status == "ok"
                        else f"직접 확인 필요: {mismatch or info.note}")}


def build_description_many(description: str, creators: list[str], urls: list[str]) -> str:
    """영상이 여러 개일 때: 📷I 한 줄에 계정을 모두 적고, 🔗 원본 줄을 링크마다 붙인다."""
    kept = [ln for ln in description.split("\n") if not ln.startswith(("📷", "🔗 원본"))]
    text = "\n".join(kept).rstrip()
    extra = []
    if creators:
        extra.append("📷I " + ", ".join(creators))
    extra += [f"🔗 원본: {u}" for u in urls if u]
    return text + ("\n\n" + "\n".join(extra) if extra else "")


def apply_sources(out_dir: Path, links: list[str], resolver: Optional[Resolver] = resolve_redirect) -> dict:
    """제품 하나에 원본 영상이 여러 개인 경우 출처를 반영한다. 여러 번 실행해도 결과가 같다."""
    json_path, md_path = out_dir / "script.json", out_dir / "script.md"
    script = load_script(json_path)
    links = [l.strip() for l in links if l and l.strip()]
    if not links:
        return {"status": "skipped", "message": "원본 링크가 없어 건너뜀"}
    infos = [parse_source_link(l, resolver=resolver) for l in links]
    creators, seen = [], set()
    for i in infos:
        if i.handle and i.handle.lower() not in seen:
            seen.add(i.handle.lower())
            creators.append(i.handle)
    manual = [i for i in infos if i.status != "ok"]
    urls = [i.url or i.original for i in infos]

    script["video_link"] = links[0]
    script["video_links"] = links
    script["creator"] = ", ".join(creators)
    script["source"] = {k: v for k, v in asdict(infos[0]).items() if k != "original"}
    script["description"] = build_description_many(script.get("description", ""), creators, urls)
    review = script.setdefault("review", {})
    sources = [s for s in review.get("sources", []) if s.get("label") != SOURCE_LABEL]
    for n, i in enumerate(infos, 1):
        if i.url:
            sources.append({"label": SOURCE_LABEL, "url": i.url,
                            "used_for": f"설명란 출처 표기 (영상 {n}, {i.handle or '크리에이터 확인 필요'})"})
    review["sources"] = sources
    sentence = ""
    if manual:
        sentence = "원본 출처를 직접 확인하세요. " + " / ".join(
            f"영상 {infos.index(i) + 1}: {i.note or '계정을 확인하지 못했습니다.'}" for i in manual)
        review["needs_review"] = True
    review["notes"] = _clean_notes(review.get("notes", ""), bool(creators), sentence)
    json_path.write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if md_path.is_file():
        line = ("- 원본 출처: " + ", ".join(f"{i.platform} {i.handle or '직접 확인 필요'}" for i in infos)
                + f" ({len(infos)}개 영상, 링크에서 자동 추출, 사용 허락은 별도 확인)")
        md_path.write_text(_update_markdown(md_path.read_text(encoding="utf-8"), script["description"], line, bool(creators)),
                           encoding="utf-8")
    return {"status": "manual" if manual else "ok", "creators": creators,
            "message": (f"{', '.join(creators)} 를 설명란에 반영 (원본 {len(infos)}개)" if not manual
                        else f"직접 확인 필요 {len(manual)}건 (원본 {len(infos)}개)")}


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="원본 링크에서 출처(@핸들)를 뽑아 설명란에 반영")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_many = sub.add_parser("apply-many", help="원본 영상이 여러 개일 때 한 번에 출처를 반영한다")
    p_many.add_argument("id")
    p_many.add_argument("--date", default=today())
    p_many.add_argument("--workdir", default=".")
    p_many.add_argument("--links", nargs="+", required=True)
    p_many.add_argument("--no-resolve", action="store_true")
    p_parse = sub.add_parser("parse", help="링크만 해석해 보여준다(파일 변경 없음)")
    p_parse.add_argument("link")
    p_parse.add_argument("--no-resolve", action="store_true", help="단축 링크를 따라가지 않는다")
    p_apply = sub.add_parser("apply", help="script.json/script.md 에 출처를 반영한다")
    p_apply.add_argument("id")
    p_apply.add_argument("--date", default=today())
    p_apply.add_argument("--workdir", default=".")
    p_apply.add_argument("--link", default="", help="원본 링크 (기본: script.json 의 video_link)")
    p_apply.add_argument("--creator", default="", help="CSV 의 크리에이터 (있으면 우선)")
    p_apply.add_argument("--no-resolve", action="store_true", help="단축 링크를 따라가지 않는다")
    args = parser.parse_args()
    resolver = None if args.no_resolve else resolve_redirect

    if args.cmd == "parse":
        info = parse_source_link(args.link, resolver=resolver)
        print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "apply-many":
        try:
            out = item_dir(Path(args.workdir).resolve(), args.date, args.id)
            result = apply_sources(out, args.links, resolver=resolver)
        except ScriptError as exc:
            print(f"[{args.id}] 실패: {exc}")
            return 1
        print(f"[{args.id}] 출처: {result['message']}")
        return 0
    try:
        out = item_dir(Path(args.workdir).resolve(), args.date, args.id)
        result = apply_source(out, args.link, args.creator, resolver=resolver)
    except ScriptError as exc:
        print(f"[{args.id}] 실패: {exc}")
        return 1
    print(f"[{args.id}] 출처: {result['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
