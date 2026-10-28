"""사용 허락 기록: script.json 에 원본 영상의 사용 허락 여부와 근거를 남기고 확인한다.

tts.py 와 render.py 는 허락이 근거와 함께 기록된 영상만 처리한다. 허락은 사람이 확인해서 적는다.

사용 예 (작업 폴더에서 실행):
    python permission.py set 001 --value "Y 2026-10-20 DM 승인"
    python permission.py check 001
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import (PERMISSION_FIX, ScriptError, configure_stdout, item_dir, load_script, parse_permission,
                    permission_status, today, write_script)


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="원본 영상 사용 허락 기록·확인")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("set", "check"):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--date", default=today(), help="출력 폴더 날짜 YYYYMMDD (기본: 오늘)")
        p.add_argument("--workdir", default=".", help="작업 폴더")
        if name == "set":
            p.add_argument("--value", required=True, help="허락 근거. 예: 'Y 2026-10-20 DM 승인'. N, 미확인, 대기는 허락 아님")
    args = parser.parse_args()

    try:
        path = item_dir(Path(args.workdir).resolve(), args.date, args.id) / "script.json"
        script = load_script(path)
        if args.cmd == "set":
            script["permission"] = parse_permission(args.value)
            write_script(path, script)
        ok, reason = permission_status(script)
    except ScriptError as exc:
        print(f"[{args.id}] 실패: {exc}")
        return 1
    if ok:
        print(f"[{args.id}] 사용 허락 확인됨 (근거: {script['permission']['note']})")
        return 0
    print(f"[{args.id}] 사용 허락 미확인: {reason}")
    if args.cmd == "check":
        print(PERMISSION_FIX)
    return 1 if args.cmd == "check" else 0


if __name__ == "__main__":
    sys.exit(main())
