"""TTS 더빙: script.json 의 선택 버전 캡션 → voice.mp3 + timing.json

사용 예 (작업 폴더에서 실행):
    python tts.py 001 002              # 지정한 id
    python tts.py --approved           # 날짜 폴더에서 approved 가 true 인 id 전부
    python tts.py 001 --dry-run        # API 호출 없이 보낼 내용과 글자 수만 확인
    python tts.py 001 --provider mock  # 키 없이 무음 오디오로 시험 (테스트 전용)

voice.mp3 와 timing.json 이 이미 있고 문구·보이스 설정이 그대로면 API를 다시 부르지 않는다(크레딧 절약).
--force 로 강제 재생성한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from common import ScriptError, configure_stdout, item_dir, list_ids, load_env, load_script, selected_lines, today
from tts_providers import PROVIDERS, get_provider
from tts_providers.base import TTSError


def text_hash(lines: list[str], described: dict) -> str:
    blob = json.dumps({"lines": lines, "provider": described}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def cached(out: Path, digest: str) -> bool:
    timing = out / "timing.json"
    if not ((out / "voice.mp3").is_file() and timing.is_file()):
        return False
    try:
        return json.loads(timing.read_text(encoding="utf-8")).get("text_hash") == digest
    except (json.JSONDecodeError, OSError):
        return False


def run_one(item_id: str, args, workdir: Path, env: dict) -> bool:
    out = item_dir(workdir, args.date, item_id)
    script = load_script(out / "script.json")
    if script.get("approved") is not True and not args.allow_unapproved:
        print(f"[{item_id}] 건너뜀: 승인되지 않았습니다. script.json의 approved를 true로 바꾸거나 --allow-unapproved를 쓰세요.")
        return False
    lines = selected_lines(script)
    provider_name = args.provider or env.get("TTS_PROVIDER") or "elevenlabs"
    provider = get_provider(provider_name, env)
    described = provider.describe()
    digest = text_hash(lines, described)

    if args.dry_run:
        print(f"[{item_id}] dry-run: 공급자={provider_name}, {len(lines)}줄, 예상 사용량 {provider.estimate_cost(lines)}")
        for i, line in enumerate(lines, 1):
            print(f"    {i}. {line}")
        return True

    if not args.force and cached(out, digest):
        print(f"[{item_id}] 건너뜀: voice.mp3가 이미 있고 문구·설정이 같습니다(--force로 재생성).")
        return True

    print(f"[{item_id}] 합성 중... 공급자={provider_name}, 예상 사용량 {provider.estimate_cost(lines)}")
    result = provider.synthesize(lines)

    (out / "voice.mp3").write_bytes(result.audio)
    timing = {
        "id": item_id,
        "selected_version": script.get("selected_version"),
        "text_hash": digest,
        **described,
        "duration": result.duration,
        "lines": [
            {"index": t.index, "text": t.text, "start": t.start, "end": t.end,
             **({"chars": t.chars} if t.chars else {})}
            for t in result.lines
        ],
    }
    (out / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{item_id}] 완료: voice.mp3 {result.duration:.1f}초, timing.json {len(result.lines)}줄")
    for warning in result.meta.get("warnings", []):
        print(f"[{item_id}] 주의: {warning}")
    if not 16 <= result.duration <= 30:
        print(f"[{item_id}] 주의: 길이가 16~30초 범위를 벗어났습니다. 문구를 줄이거나 늘려 보세요.")
    return True


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="script.json → voice.mp3 + timing.json")
    parser.add_argument("ids", nargs="*", help="처리할 id (생략하고 --approved 를 쓰면 승인된 id 전부)")
    parser.add_argument("--approved", action="store_true", help="날짜 폴더에서 approved=true 인 id 전부 처리")
    parser.add_argument("--date", default=today(), help="출력 폴더 날짜 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--workdir", default=".", help="작업 폴더 (input/, output/, .env 가 있는 곳)")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), help="공급자 (기본: .env 의 TTS_PROVIDER)")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 생성")
    parser.add_argument("--dry-run", action="store_true", help="API를 부르지 않고 내용만 확인")
    parser.add_argument("--allow-unapproved", action="store_true", help="approved 가 아니어도 처리(시험용)")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    env = load_env(workdir)
    ids = list(args.ids)
    if not ids:
        if not args.approved:
            parser.error("id를 지정하거나 --approved 를 사용하세요.")
        ids = list_ids(workdir, args.date, approved_only=True)
        if not ids:
            print(f"output/{args.date}/ 에 approved=true 인 대본이 없습니다.")
            return 1

    failures = 0
    for item_id in ids:
        try:
            if not run_one(item_id, args, workdir, env):
                failures += 1
        except (TTSError, ScriptError) as exc:
            print(f"[{item_id}] 실패: {exc}")
            failures += 1
    print(f"끝: {len(ids) - failures}/{len(ids)}건 성공")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
