"""렌더링: 원본 영상 + voice.mp3 + subtitle.srt + 타이틀 → final.mp4 (1080x1920, ffmpeg)

타이틀과 자막은 Pillow 로 투명 PNG 를 그려 ffmpeg overlay 로 얹는다.
(폰트·외곽선을 한 방식으로 다루고, Windows 경로 이스케이프 문제를 피하기 위해서다.)

사용 예 (작업 폴더에서 실행):
    python render.py 001 002
    python render.py --approved
    python render.py 001 --preview 3     # 3초 지점 한 장(preview.png)만 만들어 레이아웃 확인
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from common import (PLUGIN_ROOT, ScriptError, configure_stdout, item_dir, list_ids, load_script,
                    load_template, today)


# ---- 설정 ----

def resolve_font(path_str: str, workdir: Path) -> Path:
    """절대 경로 → 작업 폴더 상대 → 플러그인 폴더 상대 순서로 폰트를 찾는다."""
    p = Path(path_str)
    candidates = [p] if p.is_absolute() else [workdir / p, PLUGIN_ROOT / p]
    for c in candidates:
        if c.is_file():
            return c
    raise ScriptError(f"폰트 파일을 찾을 수 없습니다: {path_str} "
                      f"(플러그인의 assets/fonts 에 넣거나 template.yaml 의 font 경로를 바꾸세요)")


def need(section: dict, key: str, where: str):
    if key not in section:
        raise ScriptError(f"template.yaml 에 {where}.{key} 가 없습니다.")
    return section[key]


# ---- 이미지 그리기 ----

def _fit_font(font_path: Path, text: str, size: int, max_width: int, stroke: int = 0, min_size: int = 28):
    from PIL import ImageFont
    while True:
        font = ImageFont.truetype(str(font_path), size)
        width = font.getlength(text) + stroke * 2
        if width <= max_width or size <= min_size:
            return font, size
        size -= 2


def draw_title(cfg: dict, workdir: Path, script: dict, out: Path) -> None:
    from PIL import Image, ImageDraw
    video, title = cfg["video"], cfg["title"]
    width, height = int(video["width"]), int(video["height"])
    font_path = resolve_font(str(need(title, "font", "title")), workdir)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, int(title["band_height"])], fill=title["band_color"])
    max_width = int(title["max_width"])
    top = script.get("top_title") or {}

    line1 = str(top.get("line1", "")).strip()
    if line1:
        s1 = title["line1"]
        font, _ = _fit_font(font_path, line1, int(s1["size"]), max_width)
        draw.text((width / 2, int(s1["center_y"])), line1, font=font, fill=s1["color"], anchor="mm")

    line2 = str(top.get("line2_green", "")).strip()
    if line2:
        s2 = title["line2"]
        pad_x, pad_y = int(s2["pad_x"]), int(s2["pad_y"])
        font, _ = _fit_font(font_path, line2, int(s2["size"]), max_width - pad_x * 2)
        ascent, descent = font.getmetrics()
        box_w = int(font.getlength(line2)) + pad_x * 2
        box_h = ascent + descent + pad_y * 2
        cx, cy = width / 2, int(s2["center_y"])
        draw.rounded_rectangle([cx - box_w / 2, cy - box_h / 2, cx + box_w / 2, cy + box_h / 2],
                               radius=int(s2["radius"]), fill=s2["box_color"])
        draw.text((cx, cy), line2, font=font, fill=s2["color"], anchor="mm")
    img.save(out)


def draw_cue(cfg: dict, workdir: Path, lines: list[str], out: Path) -> tuple[int, int]:
    """자막 한 개를 화면 폭 전체의 투명 PNG 로 그린다. 반환: (이미지 높이, 화면 위에서의 y 위치)."""
    from PIL import Image, ImageDraw
    sub = cfg["subtitle"]
    width, height = int(cfg["video"]["width"]), int(cfg["video"]["height"])
    font_path = resolve_font(str(need(sub, "font", "subtitle")), workdir)
    stroke = int(sub["outline_width"])
    # 가장 긴 줄이 max_width 안에 들어오도록 이 자막의 글씨 크기를 정한다
    longest = max(lines, key=len)
    font, size = _fit_font(font_path, longest, int(sub["size"]), int(sub["max_width"]), stroke)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    spacing = int(sub["line_spacing"])
    block_h = line_h * len(lines) + spacing * (len(lines) - 1)
    img_h = block_h + stroke * 2 + 4
    img = Image.new("RGBA", (width, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, text in enumerate(lines):
        y = stroke + 2 + i * (line_h + spacing)
        draw.text((width / 2, y), text, font=font, fill=sub["color"], anchor="mt",
                  stroke_width=stroke, stroke_fill=sub["outline_color"])
    img.save(out)
    y_pos = height - int(sub["bottom_margin"]) - img_h
    return img_h, max(0, y_pos)


# ---- SRT ----

@dataclass
class SrtCue:
    start: float
    end: float
    lines: list[str]


_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})")


def parse_srt(text: str) -> list[SrtCue]:
    cues: list[SrtCue] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip().lstrip("﻿")):
        rows = [r for r in block.split("\n") if r.strip() != ""]
        for k, row in enumerate(rows):
            m = _TS.search(row)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                body = [r.strip() for r in rows[k + 1:]]
                if body:
                    cues.append(SrtCue(start, end, body))
                break
    return cues


# ---- ffmpeg ----

def find_tool(name: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    if name == "ffprobe":
        ff = shutil.which("ffmpeg")
        if ff:
            sibling = Path(ff).with_name("ffprobe" + Path(ff).suffix)
            if sibling.is_file():
                return str(sibling)
    raise ScriptError(f"{name} 를 찾을 수 없습니다. ffmpeg 를 설치하고 PATH 에 추가하세요.")


def probe(path: Path) -> dict:
    proc = subprocess.run([find_tool("ffprobe"), "-v", "error", "-show_entries",
                           "format=duration:stream=codec_type", "-of", "json", str(path)],
                          capture_output=True)
    if proc.returncode != 0:
        raise ScriptError(f"파일을 읽을 수 없습니다({path.name}): "
                          + proc.stderr.decode("utf-8", "replace").strip()[:200])
    data = json.loads(proc.stdout.decode("utf-8", "replace"))
    types = {s.get("codec_type") for s in data.get("streams", [])}
    return {"duration": float(data.get("format", {}).get("duration") or 0),
            "has_video": "video" in types, "has_audio": "audio" in types}


def build_filter(cfg: dict, overlays: list[tuple[int, float, float, int]], source_has_audio: bool,
                 with_audio: bool) -> str:
    """overlays: (입력 번호, 시작, 끝, y) 목록. 입력 0=원본, 1=음성, 2=타이틀, 3~=자막."""
    video = cfg["video"]
    w, h, fps = int(video["width"]), int(video["height"]), int(video["fps"])
    fit = str(video.get("fit", "cover"))
    if fit == "cover":
        parts = [f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}[v0]"]
    elif fit == "contain_blur":
        parts = [
            f"[0:v]split=2[bgsrc][fgsrc]",
            f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:5[bg]",
            f"[fgsrc]scale={w}:{h}:force_original_aspect_ratio=decrease[fg]",
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps}[v0]",
        ]
    else:
        raise ScriptError(f"template.yaml 의 video.fit 은 cover 또는 contain_blur 여야 합니다(현재: {fit}).")
    parts.append("[v0][2:v]overlay=0:0[t0]")
    last = "t0"
    for n, (idx, start, end, y) in enumerate(overlays):
        nxt = f"c{n}"
        parts.append(f"[{last}][{idx}:v]overlay=x=0:y={y}:enable='between(t,{start:.3f},{end:.3f})'[{nxt}]")
        last = nxt
    parts.append(f"[{last}]format=yuv420p[vout]")
    if with_audio:
        sv, tv = float(video["source_volume"]), float(video["tts_volume"])
        if source_has_audio:
            parts.append(f"[0:a]volume={sv},aresample=44100[a0]")
            parts.append(f"[1:a]volume={tv},aresample=44100[a1]")
            parts.append("[a0][a1]amix=inputs=2:duration=longest:normalize=0[aout]")
        else:
            parts.append(f"[1:a]volume={tv},aresample=44100[aout]")
    return ";".join(parts)


def render_one(item_id: str, args, workdir: Path, cfg: dict) -> Path:
    out_dir = item_dir(workdir, args.date, item_id)
    script = load_script(out_dir / "script.json")
    if script.get("approved") is not True and not args.allow_unapproved:
        raise ScriptError("승인되지 않았습니다. script.json 의 approved 를 true 로 바꾸거나 --allow-unapproved 를 쓰세요.")
    src = workdir / "input" / "videos" / f"{item_id}.mp4"
    voice, srt_path = out_dir / "voice.mp3", out_dir / "subtitle.srt"
    for path, hint in ((src, "원본 영상을 input/videos/ 에 넣어주세요"),
                       (voice, "먼저 tts.py 를 실행하세요"),
                       (srt_path, "먼저 subtitle.py 를 실행하세요")):
        if not path.is_file():
            raise ScriptError(f"{path.relative_to(workdir) if path.is_relative_to(workdir) else path} 가 없습니다. {hint}.")

    src_info, voice_info = probe(src), probe(voice)
    if not src_info["has_video"]:
        raise ScriptError(f"{src.name} 에 영상 스트림이 없습니다.")
    if voice_info["duration"] <= 0:
        raise ScriptError("voice.mp3 의 길이를 읽을 수 없습니다.")
    total = voice_info["duration"] + float(cfg["video"]["tail_seconds"])
    cues = parse_srt(srt_path.read_text(encoding="utf-8-sig"))
    if not cues:
        raise ScriptError("subtitle.srt 에 자막이 없습니다.")

    preview = args.preview is not None
    final = out_dir / ("preview.png" if preview else "final.mp4")
    with tempfile.TemporaryDirectory(prefix="misskorea_") as tmp:
        tmpdir = Path(tmp)
        title_png = tmpdir / "title.png"
        draw_title(cfg, workdir, script, title_png)
        inputs = ["-stream_loop", "-1", "-i", str(src), "-i", str(voice), "-i", str(title_png)]
        overlays: list[tuple[int, float, float, int]] = []
        for n, cue in enumerate(cues):
            png = tmpdir / f"cue{n:03d}.png"
            _, y = draw_cue(cfg, workdir, cue.lines, png)
            inputs += ["-i", str(png)]
            overlays.append((3 + n, cue.start, min(cue.end, total), y))
        filt = build_filter(cfg, overlays, src_info["has_audio"], with_audio=not preview)
        cmd = [find_tool("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", *inputs,
               "-filter_complex", filt, "-map", "[vout]"]
        if preview:
            at = min(max(args.preview, 0.0), total)
            cmd += ["-ss", f"{at:.3f}", "-frames:v", "1", str(final)]
        else:
            video = cfg["video"]
            cmd += ["-map", "[aout]", "-t", f"{total:.3f}", "-r", str(int(video["fps"])),
                    "-c:v", "libx264", "-preset", str(video["preset"]), "-crf", str(int(video["crf"])),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", str(video["audio_bitrate"]),
                    "-movflags", "+faststart", str(final)]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not final.is_file():
            tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
            raise ScriptError("ffmpeg 렌더링에 실패했습니다:\n    " + "\n    ".join(tail))
    return final


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="원본 + 음성 + 자막 + 타이틀 → final.mp4")
    parser.add_argument("ids", nargs="*", help="처리할 id")
    parser.add_argument("--approved", action="store_true", help="날짜 폴더에서 approved=true 인 id 전부")
    parser.add_argument("--date", default=today(), help="출력 폴더 날짜 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--workdir", default=".", help="작업 폴더")
    parser.add_argument("--preview", type=float, metavar="SEC", help="SEC 초 지점 한 장을 preview.png 로 저장")
    parser.add_argument("--allow-unapproved", action="store_true", help="approved 가 아니어도 처리(시험용)")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    ids = list(args.ids)
    if not ids:
        if not args.approved:
            parser.error("id를 지정하거나 --approved 를 사용하세요.")
        ids = list_ids(workdir, args.date, approved_only=True)
        if not ids:
            print(f"output/{args.date}/ 에 approved=true 인 대본이 없습니다.")
            return 1
    try:
        cfg = load_template(workdir)
        for section in ("video", "title", "subtitle"):
            if not isinstance(cfg.get(section), dict):
                raise ScriptError(f"template.yaml 에 {section} 항목이 없습니다.")
    except ScriptError as exc:
        print(f"설정 오류: {exc}")
        return 1

    failures = 0
    for item_id in ids:
        try:
            final = render_one(item_id, args, workdir, cfg)
            size_mb = final.stat().st_size / 1_000_000
            print(f"[{item_id}] 완료: {final.name} ({size_mb:.1f}MB)")
        except (ScriptError, KeyError, OSError) as exc:
            print(f"[{item_id}] 실패: {exc if not isinstance(exc, KeyError) else 'template.yaml 에 ' + str(exc) + ' 항목이 없습니다.'}")
            failures += 1
    print(f"끝: {len(ids) - failures}/{len(ids)}건 성공")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
