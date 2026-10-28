"""tts.py / subtitle.py / render.py 공통 유틸."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path


class ScriptError(RuntimeError):
    """script.json 이 없거나 잘못된 경우. id 하나의 실패로 다루고 나머지는 계속 처리한다."""


def configure_stdout() -> None:
    """Windows 콘솔에서 한글·기호가 깨지거나 예외가 나지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def today() -> str:
    return date.today().strftime("%Y%m%d")


def load_env(workdir: Path) -> dict:
    """작업 폴더의 .env 를 읽고, 같은 이름의 실제 환경 변수가 있으면 그 값을 우선한다."""
    values: dict = {}
    env_file = workdir / ".env"
    if env_file.is_file():
        from dotenv import dotenv_values
        values.update({k: v for k, v in dotenv_values(env_file, encoding="utf-8-sig").items() if v is not None})
    for key, value in os.environ.items():
        if value:
            values[key] = value
    return values


PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_template(workdir: Path) -> dict:
    """플러그인 기본 template.yaml 위에 작업 폴더의 config/template.yaml 을 덮어쓴다."""
    import yaml

    def read(path: Path) -> dict:
        if not path.is_file():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        except yaml.YAMLError as exc:
            raise ScriptError(f"template.yaml을 읽을 수 없습니다({path}): {exc}")
        if not isinstance(data, dict):
            raise ScriptError(f"template.yaml 최상위는 항목 목록이어야 합니다: {path}")
        return data

    return _deep_merge(read(PLUGIN_ROOT / "config" / "template.yaml"),
                       read(workdir / "config" / "template.yaml"))


# ---- 사용 허락 기록 ----
# batch.csv 의 '사용허락' 칸이나 permission.py 로 script.json 에 남기고, tts.py·render.py 가 확인한다.

_NEGATIVE = {"", "n", "no", "x", "false", "0", "-", "아니오", "아니요", "없음", "미확인", "대기", "확인중",
             "확인 중", "보류", "불가", "거절"}

PERMISSION_FIX = ("고치는 방법: batch.csv 의 '사용허락' 칸에 'Y 날짜 방법'(예: Y 2026-10-20 DM 승인)을 적고 다시 실행하거나, "
                  "python permission.py set <id> --value \"Y 2026-10-20 DM 승인\" 을 실행하세요.")


def parse_permission(raw: str | None) -> dict:
    """'사용허락' 칸의 글을 {granted, note} 로 바꾼다. 비었거나 N, 아니오, 미확인, 대기 같은 값이면 허락 아님."""
    note = (raw or "").strip()
    first = re.split(r"[\s:,;()/]+", note.lower())[0] if note else ""
    granted = bool(note) and note.lower() not in _NEGATIVE and first not in _NEGATIVE
    return {"granted": granted, "note": note}


def permission_status(script: dict) -> tuple[bool, str]:
    """script.json 에 사용 허락이 근거와 함께 기록돼 있는지 확인한다. (통과 여부, 막힌 이유)"""
    perm = script.get("permission")
    if not isinstance(perm, dict):
        return False, "script.json 에 사용 허락 기록(permission)이 없습니다."
    if perm.get("granted") is not True:
        return False, "사용 허락이 확인되지 않았습니다(permission.granted 가 true 가 아님)."
    if not str(perm.get("note", "")).strip():
        return False, "사용 허락 근거(permission.note)가 비어 있습니다. 허락 날짜와 방법을 적어주세요."
    return True, ""


def write_script(path: Path, script: dict) -> None:
    path.write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item_dir(workdir: Path, day: str, item_id: str) -> Path:
    return workdir / "output" / day / item_id


def load_script(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ScriptError(f"script.json이 없습니다: {path}")
    except json.JSONDecodeError as exc:
        raise ScriptError(f"script.json이 올바른 JSON이 아닙니다({path}): {exc}")


def selected_lines(script: dict) -> list[str]:
    """selected_version에 해당하는 캡션 줄을 돌려준다. 문제가 있으면 한글 메시지로 종료한다."""
    version = script.get("selected_version")
    for entry in script.get("versions", []):
        if entry.get("version") == version:
            lines = [str(x).strip() for x in entry.get("lines", [])]
            if not lines or any(not x for x in lines):
                raise ScriptError(f"버전 {version}의 캡션 줄이 비어 있습니다.")
            return lines
    raise ScriptError(f"selected_version={version!r}에 해당하는 versions 항목이 없습니다(1 또는 2여야 합니다).")


def list_ids(workdir: Path, day: str, approved_only: bool) -> list[str]:
    base = workdir / "output" / day
    if not base.is_dir():
        return []
    ids = []
    for child in sorted(base.iterdir()):
        sj = child / "script.json"
        if not (child.is_dir() and sj.is_file()):
            continue
        if approved_only and load_script(sj).get("approved") is not True:
            continue
        ids.append(child.name)
    return ids
