"""허락받은 영상 파일 받기: 제작자가 준 파일 링크(드라이브, 드롭박스, 직접 링크)를 input/videos/<id>.mp4 로 저장한다.

- 사용 허락이 근거와 함께 기록된 영상만 받는다(permission.py, batch.csv 의 '사용허락').
- SNS 영상 링크(TikTok, Instagram, YouTube, X 등)와 다운로더 사이트는 받지 않는다. 제작자가 직접 준 파일 링크만 쓴다.
- https 만 허용하고, 내 컴퓨터나 사내망 주소로 가는 링크는 막는다(리다이렉트마다 다시 확인). 크기 한도와 영상 검증이 있다.

사용 예 (작업 폴더에서 실행):
    python fetch_source.py 001 --url "https://drive.google.com/file/d/<파일ID>/view" --date 20261026
    python fetch_source.py 001 --url "<링크>" --force      # 이미 있는 영상을 다시 받기
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import requests

from common import (PERMISSION_FIX, ScriptError, configure_stdout, item_dir, load_script, permission_status, today,
                    write_script)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MAX_HOPS = 5
BLOCKED_SUFFIXES = (
    "tiktok.com", "tiktokcdn.com", "instagram.com", "youtube.com", "youtu.be", "facebook.com", "fb.watch",
    "x.com", "twitter.com", "douyin.com", "snaptik.app", "ssstik.io", "musicaldown.com",
)
SNS_MESSAGE = ("SNS 영상 링크나 다운로더 사이트는 받지 않습니다. 영상 제작자가 직접 보낸 파일 링크(드라이브, 드롭박스 등)를 "
               "'영상링크' 칸에 넣거나, 받은 파일을 input/videos/<id>.mp4 로 직접 넣어주세요.")


class FetchError(ScriptError):
    """사용자에게 그대로 보여줄 수 있는 다운로드 오류."""


def _host_blocked(host: str) -> bool:
    return any(host == s or host.endswith("." + s) for s in BLOCKED_SUFFIXES)


def normalize_url(url: str) -> str:
    """공유 링크를 내려받기용 주소로 바꾼다(구글 드라이브, 드롭박스). SNS 주소는 거절한다."""
    raw = (url or "").strip()
    if not raw:
        raise FetchError("영상링크가 비어 있습니다.")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise FetchError("https 링크만 받을 수 있습니다.")
    if not host or "." not in host:
        raise FetchError("링크 형식이 올바르지 않습니다.")
    if _host_blocked(host):
        raise FetchError(SNS_MESSAGE)
    segs = [s for s in parts.path.split("/") if s]
    if host == "drive.google.com":
        file_id = ""
        if len(segs) >= 3 and segs[0] == "file" and segs[1] == "d":
            file_id = segs[2]
        else:
            file_id = parse_qs(parts.query).get("id", [""])[0]
        if not file_id:
            raise FetchError("구글 드라이브 파일 링크(drive.google.com/file/d/...)가 아닙니다. 폴더 링크는 받을 수 없습니다.")
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    if host in {"www.dropbox.com", "dropbox.com"}:
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        query["dl"] = "1"
        return urlunsplit(("https", host, parts.path, urlencode(query), ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def assert_public(url: str, resolver: Callable = socket.getaddrinfo) -> None:
    """https 이고 공개 인터넷 주소이며 SNS 가 아닌지 확인한다. 리다이렉트마다 호출한다."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise FetchError("https 링크만 받을 수 있습니다.")
    if _host_blocked(host):
        raise FetchError(SNS_MESSAGE)
    try:
        infos = resolver(host, parts.port or 443)
    except OSError:
        raise FetchError(f"주소를 찾을 수 없습니다: {host}")
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError("내 컴퓨터나 사내망 주소로 가는 링크는 받을 수 없습니다.")


def safe_url(url: str) -> str:
    """기록용: 쿼리·조각(토큰이 들어 있을 수 있음)을 뺀 주소."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def download(url: str, dest: Path, max_bytes: int, getter: Callable = requests.get,
             resolver: Callable = socket.getaddrinfo) -> int:
    """url 을 dest 로 내려받는다. 반환: 받은 바이트 수. 실패하면 임시 파일을 지우고 FetchError."""
    current = url
    resp = None
    for _ in range(MAX_HOPS + 1):
        assert_public(current, resolver)
        try:
            resp = getter(current, stream=True, allow_redirects=False, timeout=(10, 60), headers={"User-Agent": UA})
        except requests.RequestException as exc:
            raise FetchError(f"링크에 연결하지 못했습니다: {exc.__class__.__name__}")
        location = resp.headers.get("Location")
        if resp.status_code in (301, 302, 303, 307, 308) and location:
            resp.close()
            current = urljoin(current, location)
            continue
        break
    else:
        raise FetchError("링크가 너무 많이 다른 주소로 넘어갑니다.")

    try:
        if resp.status_code != 200:
            hint = {403: "공유 권한을 확인하세요('링크가 있는 모든 사용자'로 공유).", 404: "링크가 만료됐거나 파일이 없습니다.",
                    429: "요청이 너무 많습니다. 잠시 뒤 다시 시도하세요."}.get(resp.status_code, "링크를 확인하세요.")
            raise FetchError(f"다운로드 실패({resp.status_code}): {hint}")
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype.startswith("text/html"):
            raise FetchError("영상 파일이 아니라 웹 페이지가 내려왔습니다. 공유 권한이 막혔거나, 용량이 커서 확인 화면이 뜬 경우입니다. "
                             "파일을 직접 내려받아 input/videos/<id>.mp4 로 넣어주세요.")
        declared = int(resp.headers.get("Content-Length") or 0)
        if declared > max_bytes:
            raise FetchError(f"파일이 너무 큽니다({declared // 1_000_000}MB, 한도 {max_bytes // 1_000_000}MB).")
        part = dest.with_name(dest.name + ".part")
        total = 0
        try:
            with part.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError(f"파일이 한도({max_bytes // 1_000_000}MB)를 넘어 받기를 멈췄습니다.")
                    fh.write(chunk)
            if total == 0:
                raise FetchError("빈 파일이 내려왔습니다.")
            part.replace(dest)
        finally:
            if part.exists():
                part.unlink()
        return total
    finally:
        resp.close()


def validate_video(path: Path) -> None:
    from render import probe
    try:
        info = probe(path)
    except ScriptError as exc:
        raise FetchError(f"받은 파일이 영상이 아닙니다: {exc}")
    if not info["has_video"]:
        raise FetchError("받은 파일에 영상 스트림이 없습니다.")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="허락받은 영상 파일 링크를 input/videos/<id>.mp4 로 받기")
    parser.add_argument("id")
    parser.add_argument("--url", required=True, help="제작자가 준 파일 링크(드라이브, 드롭박스, 직접 링크)")
    parser.add_argument("--date", default=today(), help="출력 폴더 날짜 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--workdir", default=".", help="작업 폴더")
    parser.add_argument("--force", action="store_true", help="이미 있는 영상을 다시 받기")
    parser.add_argument("--max-mb", type=int, default=500, help="최대 크기(MB), 기본 500")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    dest = workdir / "input" / "videos" / f"{args.id}.mp4"
    try:
        script_path = item_dir(workdir, args.date, args.id) / "script.json"
        script = load_script(script_path)
        ok, reason = permission_status(script)
        if not ok:
            print(f"[{args.id}] 받지 않음: {reason}\n{PERMISSION_FIX}")
            return 1
        if dest.exists() and not args.force:
            print(f"[{args.id}] 건너뜀: {dest.name} 가 이미 있습니다(--force 로 다시 받기).")
            return 0
        url = normalize_url(args.url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = download(url, dest, args.max_mb * 1_000_000)
        try:
            validate_video(dest)
        except FetchError:
            dest.unlink(missing_ok=True)
            raise
        script["video_file"] = {
            "path": f"input/videos/{args.id}.mp4", "source": safe_url(url), "size_bytes": size,
            "sha256": sha256_of(dest), "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        write_script(script_path, script)
    except ScriptError as exc:
        print(f"[{args.id}] 실패: {exc}")
        return 1
    print(f"[{args.id}] 완료: {dest.name} {size / 1_000_000:.1f}MB (사용 허락 근거: {script['permission']['note']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
