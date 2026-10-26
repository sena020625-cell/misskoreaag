"""자막: timing.json → subtitle.srt

한 화면(자막 한 개)은 최대 max_lines(기본 2)줄이고, 한 줄은 max_chars_per_line(기본 16)자 이하다.
긴 문장은 쉼표·띄어쓰기 같은 자연스러운 위치에서 나누고, 2줄을 넘으면 자막을 여러 개로 쪼갠다.
글자 타이밍(timing.json 의 chars)이 있으면 그 시간으로, 없으면 글자 수에 비례해 시간을 나눈다.

사용 예 (작업 폴더에서 실행):
    python subtitle.py 001 002
    python subtitle.py --approved
    python subtitle.py 001 --print      # 파일을 쓰지 않고 결과만 출력
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from common import ScriptError, configure_stdout, item_dir, list_ids, load_template, today

BREAK_PUNCT = ",.?!…"
PUNCT_BONUS = 30.0  # 문장부호 뒤에서 나누면 이만큼 유리하다(글자 수 편차 제곱 기준, 약 5자 불균형까지 감수)
EXTRA_LINE_PENALTY = 1000.0
MIN_GAP = 0.02  # 인접 자막 사이 최소 간격(초)


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]


@dataclass
class SubtitleConfig:
    max_chars: int = 16
    max_lines: int = 2
    strip_end_punct: str = ",."
    min_duration: float = 0.8
    hold: float = 0.2

    @classmethod
    def from_template(cls, template: dict, max_chars_override: int | None = None) -> "SubtitleConfig":
        raw = template.get("subtitle", {}) or {}
        cfg = cls(
            max_chars=int(raw.get("max_chars_per_line", cls.max_chars)),
            max_lines=int(raw.get("max_lines", cls.max_lines)),
            strip_end_punct=str(raw.get("strip_end_punct", cls.strip_end_punct)),
            min_duration=float(raw.get("min_duration", cls.min_duration)),
            hold=float(raw.get("hold", cls.hold)),
        )
        if max_chars_override:
            cfg.max_chars = max_chars_override
        if cfg.max_chars < 4:
            raise ScriptError("max_chars_per_line 은 4 이상이어야 합니다.")
        if cfg.max_lines < 1:
            raise ScriptError("max_lines 는 1 이상이어야 합니다.")
        return cfg


# ---- 줄바꿈 ----

def _tokens(text: str, max_chars: int) -> list[tuple[int, int]]:
    """공백으로 나눈 단어의 (시작, 끝) 위치. max_chars 보다 긴 단어는 글자 단위로 쪼갠다."""
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\S+", text):
        a, b = m.span()
        while b - a > max_chars:
            spans.append((a, a + max_chars))
            a += max_chars
        spans.append((a, b))
    return spans


def wrap_spans(text: str, max_chars: int) -> list[tuple[int, int]]:
    """text 를 max_chars 이하의 표시 줄로 나눈 (시작, 끝) 위치 목록.

    줄 수를 가장 적게 쓰면서 줄 길이를 고르게 맞추고, 문장부호 뒤에서 나누는 쪽을 선호한다.
    """
    toks = _tokens(text, max_chars)
    if not toks:
        return []
    n = len(toks)
    total = toks[-1][1] - toks[0][0]
    if total <= max_chars:
        return [(toks[0][0], toks[-1][1])]
    target = total / -(-total // max_chars)  # 줄 수 k 의 균등 길이

    INF = float("inf")
    best = [INF] * (n + 1)
    prev = [-1] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            length = toks[j - 1][1] - toks[i][0]
            if length > max_chars:
                break
            if best[i] == INF:
                continue
            cost = best[i] + EXTRA_LINE_PENALTY + (length - target) ** 2
            if j < n and text[toks[j - 1][1] - 1] in BREAK_PUNCT:
                cost -= PUNCT_BONUS
            if cost < best[j]:
                best[j], prev[j] = cost, i
    spans: list[tuple[int, int]] = []
    j = n
    while j > 0:
        i = prev[j]
        spans.append((toks[i][0], toks[j - 1][1]))
        j = i
    spans.reverse()
    return spans


# ---- 시간 배정 ----

def _span_times(line: dict, a: int, b: int) -> tuple[float, float]:
    """줄 text 의 [a, b) 구간에 해당하는 (시작, 끝) 시간."""
    text = line["text"]
    idxs = [k for k in range(a, b) if not text[k].isspace()]
    first, last = idxs[0], idxs[-1]
    chars = line.get("chars")
    if chars and len(chars) == len(text):
        return float(chars[first][1]), float(chars[last][2])
    # 글자 타이밍이 없으면 공백 아닌 글자 수에 비례
    nonspace = [k for k, ch in enumerate(text) if not ch.isspace()]
    total = len(nonspace)
    rank_first = nonspace.index(first)
    rank_last = nonspace.index(last) + 1
    start, end = float(line["start"]), float(line["end"])
    dur = end - start
    return start + dur * rank_first / total, start + dur * rank_last / total


def build_cues(timing: dict, cfg: SubtitleConfig) -> list[Cue]:
    cues: list[Cue] = []
    for line in timing["lines"]:
        text = line["text"]
        spans = wrap_spans(text, cfg.max_chars)
        for g in range(0, len(spans), cfg.max_lines):
            group = spans[g:g + cfg.max_lines]
            start, _ = _span_times(line, group[0][0], group[0][1])
            _, end = _span_times(line, group[-1][0], group[-1][1])
            shown = [text[a:b] for a, b in group]
            shown[-1] = shown[-1].rstrip(cfg.strip_end_punct) or shown[-1]
            cues.append(Cue(start=start, end=end, lines=shown))
    return _adjust(cues, cfg)


def _adjust(cues: list[Cue], cfg: SubtitleConfig) -> list[Cue]:
    """최소 표시 시간과 여운(hold)을 더하되 다음 자막과 겹치지 않게 한다."""
    for i, cue in enumerate(cues):
        limit = cues[i + 1].start - MIN_GAP if i + 1 < len(cues) else float("inf")
        end = max(cue.end + cfg.hold, cue.start + cfg.min_duration)
        cue.end = max(min(end, limit), cue.end)
        if i + 1 < len(cues) and cue.end > cues[i + 1].start - MIN_GAP:
            cue.end = max(cue.start + 0.05, cues[i + 1].start - MIN_GAP)
    return cues


# ---- SRT ----

def _stamp(t: float) -> str:
    ms = max(0, round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = []
    for n, cue in enumerate(cues, 1):
        blocks.append(f"{n}\n{_stamp(cue.start)} --> {_stamp(cue.end)}\n" + "\n".join(cue.lines))
    return "\n\n".join(blocks) + "\n"


# ---- CLI ----

def run_one(item_id: str, args, workdir: Path, cfg: SubtitleConfig) -> None:
    out = item_dir(workdir, args.date, item_id)
    timing_path = out / "timing.json"
    if not timing_path.is_file():
        raise ScriptError(f"timing.json이 없습니다. 먼저 tts.py를 실행하세요: {timing_path}")
    try:
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScriptError(f"timing.json이 올바른 JSON이 아닙니다: {exc}")
    cues = build_cues(timing, cfg)
    srt = to_srt(cues)
    if args.print:
        print(f"[{item_id}] 자막 {len(cues)}개\n{srt}")
        return
    (out / "subtitle.srt").write_text(srt, encoding="utf-8")
    print(f"[{item_id}] 완료: subtitle.srt {len(cues)}개 자막")


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="timing.json → subtitle.srt")
    parser.add_argument("ids", nargs="*", help="처리할 id")
    parser.add_argument("--approved", action="store_true", help="날짜 폴더에서 approved=true 인 id 전부")
    parser.add_argument("--date", default=today(), help="출력 폴더 날짜 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--workdir", default=".", help="작업 폴더")
    parser.add_argument("--max-chars", type=int, help="한 줄 최대 글자 수 (기본: template.yaml)")
    parser.add_argument("--print", action="store_true", help="파일을 쓰지 않고 결과만 출력")
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
        cfg = SubtitleConfig.from_template(load_template(workdir), args.max_chars)
    except (ScriptError, ValueError) as exc:
        print(f"설정 오류: {exc}")
        return 1

    failures = 0
    for item_id in ids:
        try:
            run_one(item_id, args, workdir, cfg)
        except ScriptError as exc:
            print(f"[{item_id}] 실패: {exc}")
            failures += 1
    print(f"끝: {len(ids) - failures}/{len(ids)}건 성공")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
