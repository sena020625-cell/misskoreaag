"""대본(script.json) + 음성 타이밍(timing.json) + 원본 영상들로 캡컷 초안을 새로 만든다.

기존 캡컷 초안 하나를 '서식 견본'으로 삼아 그 구조(타이틀 2줄, 자막, 영상 크롭 위치, 글꼴)를 따라 만든다.
견본 초안과 다른 초안은 읽기만 하고 고치지 않는다. 새 초안 폴더만 만든다.

예)
  python scripts/capcut_draft.py 001 --date 20261026 --workdir . --template 에이프릴스킨 \
      --videos input/videos/a.mp4 input/videos/b.mp4 --out-dir capcut_out
  (확인 후) --install 을 붙이면 캡컷 초안 폴더로 복사하고 초안 목록에 등록한다. 캡컷은 꺼 둔다.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from subtitle import _span_times, wrap_spans  # 같은 scripts 폴더의 자막 줄바꿈 규칙을 그대로 쓴다

US = 1_000_000
CHUNK_CHARS = 10   # 한 화면에 나오는 자막 글자 수(공백 포함) 상한
TITLE_MAX = 13     # 상단 타이틀 한 줄의 글자 수 상한(권장은 10자)
DEFAULT_ROOT = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"


class DraftError(Exception):
    pass


def new_id() -> str:
    return str(uuid.uuid4()).upper()


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise DraftError(f"영상을 읽을 수 없습니다: {path}")
    j = json.loads(out.stdout)
    st = (j.get("streams") or [{}])[0]
    return {"width": st.get("width", 1080), "height": st.get("height", 1920),
            "duration": float(j["format"]["duration"])}


def probe_audio(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise DraftError(f"음성을 읽을 수 없습니다: {path}")
    return float(out.stdout.strip())


def posix(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


class Builder:
    def __init__(self, tpl: dict):
        self.tpl = tpl
        self.old = tpl["materials"]
        self.d = copy.deepcopy(tpl)
        self.m = self.d["materials"]
        for k, v in list(self.m.items()):
            if isinstance(v, list):
                self.m[k] = []
        self.d["keyframes"] = {k: [] for k in tpl.get("keyframes", {})} if isinstance(tpl.get("keyframes"), dict) else tpl.get("keyframes")
        self.d["relationships"] = []
        self.d["tracks"] = []

    def find_old(self, mid: str):
        for k, v in self.old.items():
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, dict) and x.get("id") == mid:
                        return k, x
        raise DraftError(f"견본에서 자료 {mid} 를 찾지 못했습니다")

    def add_refs(self, proto_seg: dict, seg: dict, skip=("transitions",)):
        refs = []
        for rid in proto_seg.get("extra_material_refs", []):
            k, obj = self.find_old(rid)
            if k in skip:
                continue
            o = copy.deepcopy(obj)
            o["id"] = new_id()
            self.m.setdefault(k, []).append(o)
            refs.append(o["id"])
        seg["extra_material_refs"] = refs

    def add_material(self, listname: str, proto: dict, **over) -> dict:
        o = copy.deepcopy(proto)
        o["id"] = new_id()
        o.update(over)
        self.m.setdefault(listname, []).append(o)
        return o

    def new_segment(self, proto_seg: dict, material_id: str, start: int, dur: int, src_start=None) -> dict:
        s = copy.deepcopy(proto_seg)
        s["id"] = new_id()
        s["material_id"] = material_id
        s["target_timerange"] = {"start": start, "duration": dur}
        if src_start is not None:
            s["source_timerange"] = {"start": src_start, "duration": dur}
        elif s.get("source_timerange"):
            s["source_timerange"] = {"start": 0, "duration": dur}
        s["keyframe_refs"] = []
        s["common_keyframes"] = []
        self.add_refs(proto_seg, s)
        return s

    def track(self, proto_track: dict, segments: list) -> None:
        t = copy.deepcopy(proto_track)
        t["id"] = new_id()
        t["segments"] = segments
        self.d["tracks"].append(t)


def set_text(mat: dict, text: str) -> None:
    content = json.loads(mat["content"])
    content["text"] = text
    styles = content.get("styles") or []
    if styles:
        styles = [styles[0]]
        styles[0]["range"] = [0, len(text)]
    content["styles"] = styles
    mat["content"] = json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def check_template(tpl: dict) -> str | None:
    """견본으로 쓸 수 있는 초안인지 확인한다. 쓸 수 있으면 None, 아니면 이유."""
    try:
        tracks = tpl["tracks"]
        mats = tpl["materials"]
        if not tracks or tracks[0].get("type") != "video" or not tracks[0].get("segments"):
            return "첫 트랙이 영상이 아닙니다"
        texts = [t for t in tracks[1:4] if t.get("type") == "text" and t.get("segments")]
        if len(texts) < 3:
            return "영상 바로 위 트랙 3개가 글자(타이틀 2줄, 자막)가 아닙니다"
        audio_ids = {a["id"] for a in mats.get("audios", []) if a.get("type") == "extract_music"}
        if not any(t.get("type") == "audio" and t.get("segments") and t["segments"][0]["material_id"] in audio_ids
                   for t in tracks):
            return "음성(오디오) 트랙이 없습니다"
    except (KeyError, TypeError):
        return "초안 구조를 읽을 수 없습니다"
    return None


def build_content(tpl: dict, script: dict, timing: dict, voice: Path, videos: list[Path], name: str) -> dict:
    why = check_template(tpl)
    if why:
        raise DraftError(f"이 초안은 서식 견본으로 쓸 수 없습니다: {why}")
    b = Builder(tpl)
    tr = tpl["tracks"]
    vt, t1, t2, t3 = tr[0], tr[1], tr[2], tr[3]
    at = next(t for t in tr if t["type"] == "audio" and t["segments"]
              and b.find_old(t["segments"][0]["material_id"])[1].get("type") == "extract_music")
    vproto = vt["segments"][0]
    vmat_proto = b.find_old(vproto["material_id"])[1]
    lines = timing["lines"]
    n = len(lines)
    voice_dur = probe_audio(voice)
    total = int(round(max(timing.get("duration", 0), voice_dur) * US))

    infos = [probe(v) for v in videos]
    offsets = [0.0] * len(videos)

    # 영상: 줄 경계마다 컷, 영상들을 돌려가며 사용
    segs = []
    bounds = [0] + [int(round(l["start"] * US)) for l in lines[1:]] + [total]
    for i in range(n):
        start, end = bounds[i], bounds[i + 1]
        dur = end - start
        vi = i % len(videos)
        info = infos[vi]
        off = offsets[vi]
        if off + dur / US > info["duration"]:
            off = 0.0
        if dur / US > info["duration"]:
            raise DraftError(f"영상이 너무 짧습니다({videos[vi].name}, {info['duration']:.1f}초): 줄 {i + 1} 이 {dur / US:.1f}초 필요")
        mat = b.add_material("videos", vmat_proto, path=posix(videos[vi]), material_name=videos[vi].name,
                             duration=int(info["duration"] * US), width=info["width"], height=info["height"],
                             local_material_id=new_id().lower(), unique_id=new_id().lower().replace("-", ""))
        segs.append(b.new_segment(vproto, mat["id"], start, dur, src_start=int(off * US)))
        offsets[vi] = off + dur / US
    b.track(vt, segs)

    # 상단 타이틀 2줄(전체 길이)
    top = script["top_title"]
    for text in (top["line1"], top["line2_green"]):
        if len(text) > TITLE_MAX:
            raise DraftError(f"상단 타이틀이 너무 깁니다({len(text)}자): '{text}'. 10자 안팎(최대 {TITLE_MAX}자)으로 줄여 주세요.")
    for tproto, text in ((t1, top["line1"]), (t2, top["line2_green"])):
        sp = tproto["segments"][0]
        mat = b.add_material("texts", b.find_old(sp["material_id"])[1])
        set_text(mat, text)
        b.track(tproto, [b.new_segment(sp, mat["id"], 0, total)])

    # 자막: 한 화면에 CHUNK_CHARS(10)자 이하만 나오도록 줄을 쪼개 차례로 보여준다(유튜브 화면 안쪽에 들어오게)
    sp = t3["segments"][0]
    sub_proto = b.find_old(sp["material_id"])[1]
    cues = []
    for l in lines:
        text = l["text"]
        for a, e in wrap_spans(text, CHUNK_CHARS):
            s0, e0 = _span_times(l, a, e)
            shown = text[a:e].rstrip(",.") or text[a:e]
            cues.append([s0, max(e0, s0 + 0.3), shown])
    subs = []
    for k, (s0, e0, shown) in enumerate(cues):
        start = int(round(s0 * US))
        end = int(round(e0 * US))
        if k + 1 < len(cues):
            end = min(end, int(round(cues[k + 1][0] * US)) - 10_000)
        end = min(max(end, start + 100_000), total)
        mat = b.add_material("texts", sub_proto)
        set_text(mat, shown)
        subs.append(b.new_segment(sp, mat["id"], start, end - start))
    b.track(t3, subs)

    # 음성
    asp = at["segments"][0]
    amat_proto = b.find_old(asp["material_id"])[1]
    amat = b.add_material("audios", amat_proto, path=posix(voice), name=voice.name,
                          duration=int(voice_dur * US), music_id=str(uuid.uuid4()))
    b.track(at, [b.new_segment(asp, amat["id"], 0, int(round(voice_dur * US)), src_start=0)])

    d = b.d
    d["id"] = new_id()
    d["name"] = name
    d["duration"] = total
    now = int(time.time() * US)
    d["create_time"] = now
    d["update_time"] = now
    return d


def validate(d: dict) -> list[str]:
    errs = []
    ids = {}
    for k, v in d["materials"].items():
        if isinstance(v, list):
            for x in v:
                if isinstance(x, dict) and "id" in x:
                    if x["id"] in ids:
                        errs.append(f"자료 id 중복: {x['id']}")
                    ids[x["id"]] = k
    for ti, t in enumerate(d["tracks"]):
        last = 0
        for s in t["segments"]:
            if s["material_id"] not in ids:
                errs.append(f"트랙{ti}: 없는 자료 참조 {s['material_id']}")
            for r in s.get("extra_material_refs", []):
                if r not in ids:
                    errs.append(f"트랙{ti}: 없는 부속 자료 참조 {r}")
            st = s["target_timerange"]["start"]
            if st < last:
                errs.append(f"트랙{ti}: 구간이 겹칩니다")
            last = st + s["target_timerange"]["duration"]
            if last > d["duration"] + 1:
                errs.append(f"트랙{ti}: 구간이 전체 길이를 넘습니다")
    return errs


def write_draft(out: Path, tpl_dir: Path, d: dict, name: str) -> dict:
    """새 초안 폴더를 쓴다. 반환: draft_meta_info 값."""
    if out.exists():
        raise DraftError(f"이미 있는 폴더입니다: {out}")
    out.mkdir(parents=True)
    text = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    (out / "draft_content.json").write_text(text, encoding="utf-8")

    # 견본의 가벼운 설정 파일만 복사
    for f in ("draft_settings", "draft_agency_config.json", "draft_biz_config.json",
              "performance_opt_info.json", "timeline_layout.json", "draft_virtual_store.json"):
        if (tpl_dir / f).exists():
            shutil.copy2(tpl_dir / f, out / f)
    for sub in ("Resources", "common_attachment", "adjust_mask", "matting", "smart_crop", "subdraft", "textReading", "qr_upload", "agent"):
        (out / sub).mkdir(exist_ok=True)

    # Timelines (캡컷 8.x 구조)
    old_proj = json.loads((tpl_dir / "Timelines/project.json").read_text(encoding="utf-8"))
    main_id = d["id"]
    now = int(time.time() * US)
    proj = copy.deepcopy(old_proj)
    proj["id"] = new_id()
    proj["main_timeline_id"] = main_id
    proj["create_time"] = proj["update_time"] = now
    proj["timelines"] = [{"create_time": now, "id": main_id, "is_marked_delete": False, "name": "타임라인 01", "update_time": now}]
    tl = out / "Timelines" / main_id
    tl.mkdir(parents=True)
    (out / "Timelines/project.json").write_text(json.dumps(proj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (tl / "draft_content.json").write_text(text, encoding="utf-8")
    (tl / "common_attachment").mkdir()

    meta = json.loads((tpl_dir / "draft_meta_info.json").read_text(encoding="utf-8"))
    meta["draft_id"] = new_id()
    meta["draft_name"] = name
    meta["draft_fold_path"] = posix(out)
    meta["draft_root_path"] = posix(out.parent)
    meta["tm_draft_create"] = meta["tm_draft_modified"] = now
    meta["tm_duration"] = d["duration"]
    meta["tm_draft_cloud_completed"] = ""
    meta["tm_draft_cloud_entry_id"] = 0
    meta["tm_draft_cloud_modified"] = 0
    meta["tm_draft_cloud_parent_entry_id"] = -1
    meta["cloud_package_completed_time"] = ""
    meta["draft_timeline_materials_size_"] = 0
    for m in meta.get("draft_materials", []):
        m["value"] = []
    (out / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return meta


def register(root: Path, tpl_name: str, meta: dict, backup_dir: Path) -> None:
    """초안 목록(root_meta_info.json)에 새 초안을 추가한다. 먼저 백업을 만든다."""
    rp = root / "root_meta_info.json"
    r = json.loads(rp.read_text(encoding="utf-8"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(rp, backup_dir / f"root_meta_info.{stamp}.json")
    tpl_entry = next(x for x in r["all_draft_store"] if x.get("draft_name") == tpl_name)
    e = copy.deepcopy(tpl_entry)
    fold = meta["draft_fold_path"]
    e["draft_id"] = meta["draft_id"]
    e["draft_name"] = meta["draft_name"]
    e["draft_fold_path"] = fold
    e["draft_root_path"] = meta["draft_root_path"]
    e["draft_cover"] = fold + "\\draft_cover.jpg"
    e["draft_json_file"] = fold + "\\draft_content.json"
    e["tm_draft_create"] = meta["tm_draft_create"]
    e["tm_draft_modified"] = meta["tm_draft_modified"]
    e["tm_duration"] = meta["tm_duration"]
    e["tm_draft_cloud_completed"] = ""
    e["tm_draft_cloud_entry_id"] = 0
    e["tm_draft_cloud_modified"] = 0
    e["draft_timeline_materials_size"] = 0
    r["all_draft_store"].insert(0, e)
    if isinstance(r.get("draft_ids"), int):
        r["draft_ids"] += 1
    rp.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id")
    ap.add_argument("--date", required=True)
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--template", required=True, help="서식 견본으로 쓸 기존 캡컷 초안 이름")
    ap.add_argument("--videos", nargs="+", required=True)
    ap.add_argument("--drafts-root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out-dir", default="capcut_out", help="먼저 이 폴더에 만들어 확인한다")
    ap.add_argument("--name")
    ap.add_argument("--install", action="store_true", help="확인한 초안을 캡컷 초안 폴더로 복사하고 목록에 등록한다")
    a = ap.parse_args(argv)

    try:
        work = Path(a.workdir).resolve()
        item = work / "output" / a.date / a.id
        script = json.loads((item / "script.json").read_text(encoding="utf-8-sig"))
        timing = json.loads((item / "timing.json").read_text(encoding="utf-8"))
        voice = item / "voice.mp3"
        if not voice.exists():
            raise DraftError("voice.mp3 가 없습니다. 먼저 음성을 만들어 주세요.")
        root = Path(a.drafts_root)
        tpl_dir = root / a.template
        if not (tpl_dir / "draft_content.json").exists():
            raise DraftError(f"견본 초안을 찾지 못했습니다: {tpl_dir}")
        tpl = json.loads((tpl_dir / "draft_content.json").read_text(encoding="utf-8"))
        videos = [Path(v) if Path(v).is_absolute() else work / v for v in a.videos]
        for v in videos:
            if not v.exists():
                raise DraftError(f"영상이 없습니다: {v}")
        name = a.name or f"미쓰코리아_{script.get('product', a.id)}_{a.date}"
        d = build_content(tpl, script, timing, voice, videos, name)
        errs = validate(d)
        if errs:
            raise DraftError("초안 검증 실패:\n  " + "\n  ".join(errs))
        out = work / a.out_dir / name
        meta = write_draft(out, tpl_dir, d, name)
        print(f"[{a.id}] 초안 생성(확인용): {out}")
        print(f"  길이 {d['duration'] / US:.1f}초, 영상 구간 {len(d['tracks'][0]['segments'])}개, 자막 {len(timing['lines'])}줄")
        if a.install:
            dest = root / name
            if dest.exists():
                raise DraftError(f"캡컷에 같은 이름 초안이 이미 있습니다: {dest}")
            shutil.copytree(out, dest)
            meta = json.loads((dest / "draft_meta_info.json").read_text(encoding="utf-8"))
            meta["draft_fold_path"] = posix(dest)
            meta["draft_root_path"] = posix(root)
            (dest / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            register(root, a.template, meta, work / "backup")
            print(f"  캡컷 초안 폴더에 설치하고 목록에 등록했습니다: {dest}")
            print("  캡컷을 (다시) 열어 프로젝트 목록에서 확인하세요.")
        return 0
    except DraftError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
