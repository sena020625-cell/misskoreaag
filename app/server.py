"""미쓰코리아 작업 화면(내 컴퓨터에서만 열리는 로컬 서버).

open-app.bat 을 더블클릭하면 브라우저에 화면이 열린다. 파일을 직접 열어 고칠 필요 없이
대본 검수, 영상 추가, 음성 생성, 캡컷 초안 만들기를 화면에서 한다.
대본을 새로 만드는 일(영상 분석, 글쓰기)은 Claude 앱에서 하고, 이 화면은 그 결과를 이어받는다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

APP_DIR = Path(__file__).resolve().parent
REPO = APP_DIR.parent
SCRIPTS = REPO / "scripts"
SAFE = re.compile(r"^[0-9A-Za-z가-힣_\-]{1,40}$")
DATE = re.compile(r"^\d{8}$")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
CHARS_PER_SEC = 7.5
TITLE_MAX = 13   # 상단 타이틀 한 줄 상한(권장 10자). 자막은 한 화면 10자씩 자동으로 나뉜다
DRAFTS = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"

WORK: Path = REPO
TOKEN = secrets.token_hex(16)
RUN_LOCK = threading.Lock()


class ApiError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


def item_dir(date: str, item_id: str) -> Path:
    if not DATE.match(date) or not SAFE.match(item_id):
        raise ApiError("잘못된 주소입니다")
    return WORK / "output" / date / item_id


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save_json(p: Path, data) -> None:
    if p.exists():
        shutil.copy2(p, p.with_suffix(".json.bak"))
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def video_dir(item_id: str) -> Path:
    return WORK / "input" / "videos" / item_id


def list_videos(item_id: str) -> list[Path]:
    out = []
    d = video_dir(item_id)
    if d.is_dir():
        out += sorted(p for p in d.iterdir() if p.suffix.lower() in VIDEO_EXT)
    legacy = WORK / "input" / "videos" / f"{item_id}.mp4"
    if legacy.exists():
        out.insert(0, legacy)
    return out


def est_seconds(lines: list[str]) -> float:
    return round(len("".join(lines)) / CHARS_PER_SEC, 1)


def capcut_running() -> bool:
    try:
        r = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace")
        return "capcut" in r.stdout.lower()
    except OSError:
        return False


def run_script(args: list[str], timeout: int = 600) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with RUN_LOCK:
        p = subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout, cwd=str(WORK))
    return p.returncode, (p.stdout + p.stderr).strip()


# ---- API ----------------------------------------------------------------

def api_jobs() -> dict:
    days = []
    out = WORK / "output"
    if out.is_dir():
        for dd in sorted((p for p in out.iterdir() if p.is_dir() and DATE.match(p.name)), reverse=True):
            items = []
            for ip in sorted(p for p in dd.iterdir() if p.is_dir() and (p / "script.json").exists()):
                try:
                    s = load_json(ip / "script.json")
                except (OSError, ValueError):
                    continue
                items.append({"id": ip.name, "product": s.get("product", ""), "brand": s.get("brand", ""),
                              "approved": s.get("approved") is True,
                              "uploaded": s.get("uploaded") is True,
                              "voice": (ip / "voice.mp3").exists(),
                              "videos": len(list_videos(ip.name)),
                              "capcut": bool(s.get("capcut_draft"))})
            days.append({"date": dd.name, "items": items})
    return {"days": days, "workdir": str(WORK), "repo": REPO.name}


def api_health() -> dict:
    """설치 상태 점검(값은 보여주지 않고 있는지만 알려준다)."""
    sys.path.insert(0, str(SCRIPTS))
    from common import load_env
    env = load_env(WORK)
    prov = (env.get("TTS_PROVIDER") or "").lower()
    keys = {"typecast": ("TYPECAST_API_KEY", "TYPECAST_VOICE_ID"), "elevenlabs": ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID")}.get(prov)
    tts_ok = bool(keys and env.get(keys[0]) and env.get(keys[1])) or prov in ("mock",)
    return {"ffmpeg": shutil.which("ffmpeg") is not None, "tts_provider": prov or "(없음)", "tts_ok": tts_ok,
            "capcut": DRAFTS.is_dir(), "templates": len(api_templates()["templates"])}


def api_job(date: str, item_id: str) -> dict:
    d = item_dir(date, item_id)
    sp = d / "script.json"
    if not sp.exists():
        raise ApiError("대본이 없습니다", 404)
    s = load_json(sp)
    for v in s.get("versions", []):
        v["est_seconds"] = est_seconds(v.get("lines", []))
    links = s.get("video_links") or ([s["video_link"]] if s.get("video_link") else [])
    return {"script": s, "links": links, "voice": (d / "voice.mp3").exists(),
            "videos": [p.name for p in list_videos(item_id)],
            "capcut_running": capcut_running(),
            "templates": api_templates()["templates"]}


def api_save(date: str, item_id: str, body: dict) -> dict:
    d = item_dir(date, item_id)
    sp = d / "script.json"
    s = load_json(sp)
    old_lines = [v.get("lines") for v in s.get("versions", [])]
    for nv in body.get("versions", []):
        for v in s.get("versions", []):
            if v.get("version") == nv.get("version"):
                lines = [str(x).strip() for x in nv.get("lines", []) if str(x).strip()]
                v["lines"] = lines
                v["est_seconds"] = est_seconds(lines)
    if body.get("selected_version") in (1, 2):
        s["selected_version"] = body["selected_version"]
    tt = body.get("top_title")
    if isinstance(tt, dict):
        s["top_title"] = {"line1": str(tt.get("line1", "")).strip(), "line2_green": str(tt.get("line2_green", "")).strip()}
    if isinstance(body.get("description"), str):
        s["description"] = body["description"]
    if isinstance(body.get("best_title"), str) and body["best_title"].strip():
        s["best_title"] = {"text": body["best_title"].strip(), "reason": s.get("best_title", {}).get("reason", "")}
    approved = body.get("approved") is True
    if approved:
        sel = next((v for v in s["versions"] if v["version"] == s["selected_version"]), None)
        if not sel or not 4 <= len(sel["lines"]) <= 7:
            raise ApiError("승인하려면 선택한 버전이 4~7줄이어야 합니다")
        if not 16 <= sel["est_seconds"] <= 30:
            raise ApiError(f"예상 길이가 {sel['est_seconds']}초입니다. 16~30초가 되도록 문구를 고쳐 주세요")
        if not s["top_title"]["line1"] or not s["top_title"]["line2_green"]:
            raise ApiError("상단 타이틀 2줄을 모두 채워 주세요")
        for t in (s["top_title"]["line1"], s["top_title"]["line2_green"]):
            if len(t) > TITLE_MAX:
                raise ApiError(f"상단 타이틀은 10자 안팎(최대 {TITLE_MAX}자)으로 써 주세요: '{t}' ({len(t)}자)")
    s["approved"] = approved
    # 문구가 바뀌면 이전 음성은 쓸 수 없다 (tts.py 가 해시로 다시 만들지만 표시를 위해)
    if [v.get("lines") for v in s.get("versions", [])] != old_lines:
        s.pop("capcut_draft", None)
    save_json(sp, s)
    return {"ok": True, "script": s}


def api_uploaded(date: str, item_id: str, uploaded: bool, youtube_url: str) -> dict:
    """유튜브 업로드를 마쳤다고 표시한다. 쓴 소스 링크는 이후 추천에서 제외된다."""
    sp = item_dir(date, item_id) / "script.json"
    s = load_json(sp)
    youtube_url = (youtube_url or "").strip()
    if youtube_url and not re.match(r"^https?://\S+$", youtube_url):
        raise ApiError("업로드한 영상 주소는 http로 시작해야 합니다")
    s["uploaded"] = bool(uploaded)
    s["uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S") if uploaded else ""
    s["youtube_url"] = youtube_url if uploaded else ""
    save_json(sp, s)
    return {"ok": True, "script": s}


def api_upload(date: str, item_id: str, name: str, data: bytes) -> dict:
    item_dir(date, item_id)
    name = Path(name).name
    if Path(name).suffix.lower() not in VIDEO_EXT:
        raise ApiError("영상 파일(mp4, mov, m4v, webm)만 넣을 수 있습니다")
    if not data:
        raise ApiError("빈 파일입니다")
    d = video_dir(item_id)
    d.mkdir(parents=True, exist_ok=True)
    target = d / name
    n = 2
    while target.exists():
        target = d / f"{Path(name).stem}_{n}{Path(name).suffix}"
        n += 1
    target.write_bytes(data)
    return {"ok": True, "name": target.name}


def api_delete_video(date: str, item_id: str, name: str) -> dict:
    item_dir(date, item_id)
    target = video_dir(item_id) / Path(name).name
    if target.exists():
        target.unlink()
    return {"ok": True}


def api_voice(date: str, item_id: str, force: bool) -> dict:
    d = item_dir(date, item_id)
    if load_json(d / "script.json").get("approved") is not True:
        raise ApiError("먼저 '검수 완료'를 눌러 주세요")
    args = [str(SCRIPTS / "tts.py"), item_id, "--date", date, "--workdir", str(WORK), "--skip-permission-check"]
    if force:
        args.append("--force")
    if os.environ.get("MISSKOREA_TTS_PROVIDER"):  # 시험용: mock 이면 크레딧을 쓰지 않는다
        args += ["--provider", os.environ["MISSKOREA_TTS_PROVIDER"]]
    code, out = run_script(args)
    if code != 0 or not (d / "voice.mp3").exists():
        raise ApiError("음성을 만들지 못했습니다:\n" + out[-800:], 500)
    return {"ok": True, "log": out[-400:]}


def api_templates() -> dict:
    """서식 견본으로 쓸 수 있는 기존 캡컷 프로젝트 이름들."""
    sys.path.insert(0, str(SCRIPTS))
    import capcut_draft
    names = []
    if DRAFTS.is_dir():
        for p in sorted(DRAFTS.iterdir()):
            f = p / "draft_content.json"
            if not f.exists() or p.name.startswith("미쓰코리아_"):
                continue
            try:
                if capcut_draft.check_template(json.loads(f.read_text(encoding="utf-8"))) is None:
                    names.append(p.name)
            except (OSError, ValueError):
                continue
    return {"templates": names}


def api_capcut(date: str, item_id: str, template: str) -> dict:
    d = item_dir(date, item_id)
    s = load_json(d / "script.json")
    if not (d / "voice.mp3").exists() or not (d / "timing.json").exists():
        raise ApiError("먼저 음성을 만들어 주세요")
    vids = list_videos(item_id)
    if not vids:
        raise ApiError("영상을 1개 이상 넣어 주세요")
    if template not in api_templates()["templates"]:
        raise ApiError("서식 견본 초안을 고르세요")
    if capcut_running():
        raise ApiError("캡컷이 켜져 있습니다. 캡컷을 완전히 종료한 뒤 다시 눌러 주세요")
    base = f"미쓰코리아_{s.get('product', item_id)}_{date}"
    name, n = base, 2
    while (DRAFTS / name).exists():
        name = f"{base}_{n}"
        n += 1
    args = [str(SCRIPTS / "capcut_draft.py"), item_id, "--date", date, "--workdir", str(WORK), "--template", template,
            "--videos", *[str(v) for v in vids], "--out-dir", "capcut_out", "--name", name, "--install"]
    out_dir = WORK / "capcut_out" / name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    code, out = run_script(args)
    if code != 0:
        raise ApiError("캡컷 초안을 만들지 못했습니다:\n" + out[-800:], 500)
    s["capcut_draft"] = name
    save_json(d / "script.json", s)
    return {"ok": True, "name": name, "log": out[-400:]}


def _jq():
    sys.path.insert(0, str(SCRIPTS))
    import jobqueue
    return jobqueue


def api_queue() -> dict:
    jq = _jq()
    jq.reap_stale(WORK)
    rows = sorted(jq.items(WORK), key=lambda r: r.get("created_at", ""), reverse=True)[:60]
    return {"items": rows}


def api_queue_add(text: str) -> dict:
    jq = _jq()
    added, errors = jq.add(WORK, text)
    return {"added": [{"qid": a["qid"], "product": a["product"], "links": len(a["links"])} for a in added],
            "errors": errors}


def _recs():
    sys.path.insert(0, str(SCRIPTS))
    import recs
    return recs


def api_recs() -> dict:
    rows = sorted(_recs().load(WORK), key=lambda r: r.get("created_at", ""), reverse=True)[:80]
    return {"items": rows}


def _find_rec(rid: str) -> tuple[list[dict], dict]:
    items = _recs().load(WORK)
    for it in items:
        if it.get("rid") == rid:
            return items, it
    raise ApiError("추천을 찾을 수 없습니다", 404)


def api_recs_request(rid: str) -> dict:
    """추천 한 건을 작업 요청(대기열)으로 넘긴다."""
    r = _recs()
    items, it = _find_rec(rid)
    if it.get("status") == "요청됨":
        raise ApiError("이미 요청한 추천입니다")
    text = "\n".join(it["links"]) + f"\n제품명: {it['product']}"
    added, errors = _jq().add(WORK, text)
    if errors or not added:
        raise ApiError("요청하지 못했습니다: " + " / ".join(errors))
    it["status"], it["qid"] = "요청됨", added[0]["qid"]
    r.save(WORK, items)
    return {"ok": True, "qid": it["qid"]}


def api_recs_pass(rid: str) -> dict:
    r = _recs()
    items, it = _find_rec(rid)
    it["status"] = "패스"
    r.save(WORK, items)
    return {"ok": True}


def _queue_item(qid: str) -> Path:
    if not re.fullmatch(r"q[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", qid):
        raise ApiError("잘못된 요청 번호입니다")
    p = WORK / "input" / "queue" / f"{qid}.json"
    if not p.exists():
        raise ApiError("요청을 찾을 수 없습니다", 404)
    return p


def api_queue_cancel(qid: str) -> dict:
    jq = _jq()
    p = _queue_item(qid)
    d = load_json(p)
    if d.get("status") != "대기":
        raise ApiError("대기 중인 요청만 취소할 수 있습니다")
    jq.finish(WORK, qid, "취소", "사용자가 취소했습니다")
    return {"ok": True}


def api_queue_retry(qid: str) -> dict:
    p = _queue_item(qid)
    d = load_json(p)
    if d.get("status") not in ("실패", "취소"):
        raise ApiError("실패하거나 취소된 요청만 다시 접수할 수 있습니다")
    d["status"], d["message"], d["id"] = "대기", "", ""
    save_json(p, d)
    return {"ok": True}


def api_open(date: str, item_id: str) -> dict:
    d = item_dir(date, item_id)
    if hasattr(os, "startfile"):
        os.startfile(str(d))  # type: ignore[attr-defined]
    return {"ok": True}


# ---- HTTP ---------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "Misskorea/1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _auth_ok(self) -> bool:
        return self.headers.get("X-Token") == TOKEN

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "허용되지 않은 주소"})
        u = urlparse(self.path)
        try:
            if u.path in ("/", "/index.html"):
                html = (APP_DIR / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if not self._auth_ok():
                return self._json(403, {"error": "인증 실패"})
            parts = [unquote(x) for x in u.path.strip("/").split("/")]
            if parts == ["api", "jobs"]:
                return self._json(200, api_jobs())
            if parts == ["api", "queue"]:
                return self._json(200, api_queue())
            if parts == ["api", "recs"]:
                return self._json(200, api_recs())
            if parts == ["api", "health"]:
                return self._json(200, api_health())
            if len(parts) == 4 and parts[:2] == ["api", "job"]:
                return self._json(200, api_job(parts[2], parts[3]))
            if len(parts) == 5 and parts[:2] == ["api", "job"] and parts[4] == "voice.mp3":
                f = item_dir(parts[2], parts[3]) / "voice.mp3"
                if not f.exists():
                    raise ApiError("음성이 없습니다", 404)
                return self._send(200, f.read_bytes(), "audio/mpeg")
            raise ApiError("없는 주소", 404)
        except ApiError as e:
            self._json(e.code, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self._host_ok() or not self._auth_ok():
            return self._json(403, {"error": "인증 실패"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        parts = [unquote(x) for x in u.path.strip("/").split("/")]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            if len(parts) == 3 and parts[:2] == ["api", "recs"]:
                body = json.loads(raw or b"{}")
                if parts[2] == "request":
                    return self._json(200, api_recs_request(str(body["rid"])))
                if parts[2] == "pass":
                    return self._json(200, api_recs_pass(str(body["rid"])))
            if len(parts) == 3 and parts[:2] == ["api", "queue"]:
                body = json.loads(raw or b"{}")
                if parts[2] == "add":
                    return self._json(200, api_queue_add(str(body.get("text", ""))))
                if parts[2] == "cancel":
                    return self._json(200, api_queue_cancel(str(body["qid"])))
                if parts[2] == "retry":
                    return self._json(200, api_queue_retry(str(body["qid"])))
            if len(parts) == 5 and parts[:2] == ["api", "job"]:
                date, item_id, action = parts[2], parts[3], parts[4]
                if action == "save":
                    return self._json(200, api_save(date, item_id, json.loads(raw or b"{}")))
                if action == "upload":
                    return self._json(200, api_upload(date, item_id, q.get("name", [""])[0], raw))
                if action == "uploaded":
                    b = json.loads(raw or b"{}")
                    return self._json(200, api_uploaded(date, item_id, b.get("uploaded") is True, str(b.get("youtube_url", ""))))
                if action == "delete-video":
                    return self._json(200, api_delete_video(date, item_id, json.loads(raw)["name"]))
                if action == "voice":
                    return self._json(200, api_voice(date, item_id, bool(json.loads(raw or b"{}").get("force"))))
                if action == "capcut":
                    return self._json(200, api_capcut(date, item_id, json.loads(raw)["template"]))
                if action == "open":
                    return self._json(200, api_open(date, item_id))
            raise ApiError("없는 주소", 404)
        except ApiError as e:
            self._json(e.code, {"error": str(e)})
        except subprocess.TimeoutExpired:
            self._json(500, {"error": "시간이 너무 오래 걸려 중단했습니다"})
        except (ValueError, KeyError):
            self._json(400, {"error": "잘못된 요청입니다"})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


def main() -> int:
    global WORK
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=os.environ.get("MISSKOREA_WORKDIR", str(REPO.parent)),
                    help="input/, output/, .env 가 있는 작업 폴더")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    WORK = Path(a.workdir).resolve()
    (WORK / "output").mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"미쓰코리아 작업 화면: {url}\n작업 폴더: {WORK}\n(이 창을 닫으면 화면도 종료됩니다)")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
