"""타입캐스트 보이스 찾기: 이름으로 검색해 .env 의 TYPECAST_VOICE_ID 에 넣을 voice_id(tc_...)를 알려준다.

사용 예 (작업 폴더에서 실행, .env 에 TYPECAST_API_KEY 가 있어야 함):
    python typecast_voices.py 혜원
    python typecast_voices.py --gender female --limit 20
    python typecast_voices.py 혜원 --workdir C:\\misskorea-work

조회만 하며 크레딧을 쓰지 않는다(GET /v3/voices).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from common import configure_stdout, load_env
from tts_providers.base import TTSError
from tts_providers.typecast import explain_error

URL = "https://api.typecast.ai/v3/voices"


def search_voices(voices: list[dict], query: str) -> list[dict]:
    """한국어·영어 이름에 query 가 들어간 보이스(대소문자 무시). query 가 비면 전부."""
    q = query.strip().lower()
    if not q:
        return list(voices)
    out = []
    for v in voices:
        names = v.get("voice_name") or {}
        if any(q in str(names.get(lang, "")).lower() for lang in ("kor", "eng")):
            out.append(v)
    return out


def describe(v: dict) -> str:
    names = v.get("voice_name") or {}
    models = ", ".join(m.get("version", "?") for m in v.get("models", [])) or "-"
    uses = ", ".join(v.get("use_cases") or []) or "-"
    return (f"{v['voice_id']}  {names.get('kor') or '-'} ({names.get('eng') or '-'})  "
            f"{v.get('gender') or '-'}/{v.get('age') or '-'}  용도: {uses}  모델: {models}")


def fetch_voices(api_key: str, gender: str | None) -> list[dict]:
    params = {"gender": gender} if gender else None
    try:
        resp = requests.get(URL, params=params, headers={"X-API-KEY": api_key}, timeout=60)
    except requests.RequestException as exc:
        raise TTSError(f"타입캐스트에 연결하지 못했습니다: {exc.__class__.__name__}")
    if resp.status_code != 200:
        raise TTSError(explain_error(resp))
    return resp.json()


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="타입캐스트 보이스 이름 검색 → voice_id")
    parser.add_argument("query", nargs="?", default="", help="보이스 이름(한글 또는 영문 일부). 비우면 목록")
    parser.add_argument("--gender", choices=["male", "female"], help="성별 필터")
    parser.add_argument("--limit", type=int, default=30, help="최대 출력 개수 (기본 30)")
    parser.add_argument("--workdir", default=".", help="작업 폴더 (.env 가 있는 곳)")
    args = parser.parse_args()

    env = load_env(Path(args.workdir).resolve())
    key = (env.get("TYPECAST_API_KEY") or "").strip()
    if not key:
        print(".env에 TYPECAST_API_KEY 값이 없습니다. 타입캐스트 개발자 콘솔에서 발급한 키를 넣어주세요.")
        return 1
    try:
        voices = fetch_voices(key, args.gender)
    except TTSError as exc:
        print(f"실패: {exc}")
        return 1
    hits = search_voices(voices, args.query)
    label = f"'{args.query}' " if args.query else ""
    print(f"전체 보이스 {len(voices)}개 중 {label}검색 결과 {len(hits)}개")
    for v in hits[:args.limit]:
        print("  " + describe(v))
    if len(hits) > args.limit:
        print(f"  ... {len(hits) - args.limit}개 더 있습니다(--limit 로 늘리거나 이름으로 좁히세요)")
    if hits:
        print("\n.env 에는 위의 voice_id(tc_ 로 시작하는 값)를 TYPECAST_VOICE_ID= 뒤에 넣습니다.")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
