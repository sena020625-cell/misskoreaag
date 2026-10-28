"""Typecast (타입캐스트) 공급자.

공식 문서(https://typecast.ai/docs/api-reference/text-to-speech/text-to-speech-with-timestamps)의
타임스탬프 TTS API 를 쓴다. 글자 단위 타이밍(granularity=char)으로 줄별 시작·끝을 계산한다.

- POST https://api.typecast.ai/v1/text-to-speech/with-timestamps   (헤더 X-API-KEY)
- 응답: audio(base64), audio_format, audio_duration(초), characters[{text, start, end}] (초 단위)
- 글자 타이밍을 못 믿겠을 때를 위해, 줄별 합성형(per_line)에서 쓰는 일반 TTS 백엔드(synth_plain)도 제공한다.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Mapping, Optional

import requests

from .base import LineTiming, SynthResult, TTSError, TTSProvider, require_env

API_BASE = "https://api.typecast.ai/v1"
JOINER = "\n"  # 줄 사이 구분. 공백 문자는 아래 정렬에서 건너뛴다
MAX_CHARS = 2000  # 문서의 text 최대 길이

MODELS = ("ssfm-v30", "ssfm-v21")
PRESETS = {
    "ssfm-v30": ("normal", "happy", "sad", "angry", "whisper", "toneup", "tonedown"),
    "ssfm-v21": ("normal", "happy", "sad", "angry"),
}


def _num(env: Mapping[str, str], key: str, lo: float, hi: float, integer: bool = False) -> Optional[float]:
    raw = (env.get(key) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        raise TTSError(f".env의 {key} 값 '{raw}'이 {'정수' if integer else '숫자'}가 아닙니다.")
    if not lo <= value <= hi:
        raise TTSError(f".env의 {key} 값 {raw}이 허용 범위({lo:g}~{hi:g})를 벗어났습니다.")
    return value


@dataclass
class TypecastSettings:
    api_key: str
    voice_id: str
    model: str = "ssfm-v30"
    language: str = "kor"
    emotion: Optional[str] = None  # None | "smart" | 프리셋 이름
    intensity: Optional[float] = None
    tempo: Optional[float] = None
    pitch: Optional[int] = None
    volume: Optional[int] = None
    target_lufs: Optional[float] = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "TypecastSettings":
        key = require_env(env, "TYPECAST_API_KEY", "타입캐스트 개발자 콘솔에서 발급한 API 키를 넣어주세요.")
        voice = require_env(env, "TYPECAST_VOICE_ID", "채널 고정 보이스 ID(tc_ 로 시작)를 넣어주세요.")
        if not voice.startswith(("tc_", "uc_")):
            raise TTSError(f".env의 TYPECAST_VOICE_ID '{voice}'는 보이스 ID가 아닌 것 같습니다. tc_(기본 보이스) 또는 uc_(커스텀 보이스)로 시작해야 합니다. "
                           f"보이스 이름으로 ID를 찾으려면: python typecast_voices.py {voice}")
        model = (env.get("TYPECAST_MODEL") or "ssfm-v30").strip()
        if model not in MODELS:
            raise TTSError(f".env의 TYPECAST_MODEL을 {', '.join(MODELS)} 중에서 골라주세요(현재: '{model}').")
        language = (env.get("TYPECAST_LANGUAGE") or "kor").strip().lower()
        emotion = (env.get("TYPECAST_EMOTION") or "").strip().lower() or None
        if emotion == "smart" and model != "ssfm-v30":
            raise TTSError("TYPECAST_EMOTION=smart 는 ssfm-v30 모델에서만 쓸 수 있습니다.")
        if emotion and emotion != "smart" and emotion not in PRESETS[model]:
            raise TTSError(f".env의 TYPECAST_EMOTION을 smart 또는 {', '.join(PRESETS[model])} 중에서 골라주세요(현재: '{emotion}').")
        volume = _num(env, "TYPECAST_VOLUME", 0, 200, integer=True)
        lufs = _num(env, "TYPECAST_TARGET_LUFS", -70, 0)
        if volume is not None and lufs is not None:
            raise TTSError("TYPECAST_VOLUME 과 TYPECAST_TARGET_LUFS 는 함께 쓸 수 없습니다. 하나만 남겨주세요.")
        return cls(
            api_key=key, voice_id=voice, model=model, language=language, emotion=emotion,
            intensity=_num(env, "TYPECAST_EMOTION_INTENSITY", 0, 2),
            tempo=_num(env, "TYPECAST_TEMPO", 0.5, 2),
            pitch=_num(env, "TYPECAST_PITCH", -12, 12, integer=True),
            volume=volume, target_lufs=lufs,
        )

    def describe(self) -> dict:
        return {
            "provider": "typecast", "voice_id": self.voice_id, "model": self.model,
            "language": self.language, "emotion": self.emotion, "emotion_intensity": self.intensity,
            "tempo": self.tempo, "pitch": self.pitch, "volume": self.volume, "target_lufs": self.target_lufs,
        }

    def payload(self, text: str, audio_format: str) -> dict:
        if len(text) > MAX_CHARS:
            raise TTSError(f"문구가 {len(text)}자로 타입캐스트 한도({MAX_CHARS}자)를 넘습니다.")
        body: dict = {"text": text, "voice_id": self.voice_id, "model": self.model, "language": self.language}
        if self.emotion == "smart":
            body["prompt"] = {"emotion_type": "smart"}
        elif self.emotion:
            prompt = {"emotion_preset": self.emotion,
                      "emotion_intensity": self.intensity if self.intensity is not None else 1.0}
            if self.model == "ssfm-v30":
                prompt = {"emotion_type": "preset", **prompt}
            body["prompt"] = prompt
        output: dict = {"audio_format": audio_format}
        if self.tempo is not None:
            output["audio_tempo"] = self.tempo
        if self.pitch is not None:
            output["audio_pitch"] = self.pitch
        if self.volume is not None:
            output["volume"] = self.volume
        if self.target_lufs is not None:
            output["target_lufs"] = self.target_lufs
        body["output"] = output
        return body

    def headers(self) -> dict:
        return {"X-API-KEY": self.api_key, "Content-Type": "application/json"}


def explain_error(resp: requests.Response) -> str:
    code = resp.status_code
    detail = ""
    try:
        data = resp.json()
        detail = str(data.get("message") or data.get("detail") or "")[:200]
        if data.get("error_code"):
            detail = f"{data['error_code']} {detail}".strip()
    except (ValueError, AttributeError):
        detail = resp.text[:200]
    hint = {
        400: "요청 값이 올바르지 않습니다. .env의 보이스 ID, 모델, 언어 값을 확인하세요.",
        401: "API 키가 올바르지 않습니다. .env의 TYPECAST_API_KEY를 확인하세요.",
        402: "크레딧이 부족합니다. 타입캐스트 요금제와 크레딧을 확인하세요.",
        404: "보이스 또는 모델을 찾을 수 없습니다. .env의 TYPECAST_VOICE_ID, TYPECAST_MODEL을 확인하세요.",
        422: "이 문구는 음성으로 합성할 수 없습니다. 이모지나 특수 기호를 빼고 다시 시도하세요.",
        429: "요청 한도를 넘었습니다. 잠시 뒤 다시 시도하세요.",
        500: "타입캐스트 서버에서 음성 생성이나 타이밍 정렬에 실패했습니다. 잠시 뒤 다시 시도하세요.",
    }.get(code, "타입캐스트 요청이 실패했습니다.")
    return f"타입캐스트 오류 {code}: {hint}" + (f" ({detail})" if detail else "")


def _post(url: str, settings: TypecastSettings, body: dict, params: Optional[dict] = None) -> requests.Response:
    try:
        resp = requests.post(url, params=params, headers=settings.headers(), json=body, timeout=120)
    except requests.RequestException as exc:
        raise TTSError(f"타입캐스트에 연결하지 못했습니다: {exc.__class__.__name__}")
    if resp.status_code != 200:
        raise TTSError(explain_error(resp))
    return resp


def synth_plain(settings: TypecastSettings, text: str) -> bytes:
    """일반 TTS API 로 한 줄을 합성해 wav 바이트를 돌려준다(줄별 합성형 공급자용)."""
    resp = _post(f"{API_BASE}/text-to-speech", settings, settings.payload(text, "wav"))
    return resp.content


class TypecastProvider(TTSProvider):
    name = "typecast"

    def __init__(self, settings: TypecastSettings):
        self.settings = settings

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "TypecastProvider":
        return cls(TypecastSettings.from_env(env))

    def describe(self) -> dict:
        return self.settings.describe()

    def estimate_cost(self, lines: list[str]) -> str:
        return f"약 {len(JOINER.join(lines))}자 (타입캐스트 크레딧 차감 방식은 요금제에서 확인)"

    def synthesize(self, lines: list[str]) -> SynthResult:
        text = JOINER.join(lines)
        resp = _post(f"{API_BASE}/text-to-speech/with-timestamps", self.settings,
                     self.settings.payload(text, "mp3"), params={"granularity": "char"})
        data = resp.json()
        if not data.get("audio"):
            raise TTSError("타입캐스트가 오디오를 돌려주지 않았습니다.")
        audio = base64.b64decode(data["audio"])
        characters = data.get("characters")
        if not characters:
            raise TTSError("타입캐스트가 글자 타이밍을 돌려주지 않았습니다. "
                           ".env에서 TTS_PROVIDER=per_line, PER_LINE_BACKEND=typecast 로 바꿔 시도하세요.")
        result = self._build(lines, audio, characters)
        if isinstance(data.get("audio_duration"), (int, float)):
            result.duration = round(float(data["audio_duration"]), 3)
        return result

    @staticmethod
    def _build(lines: list[str], audio: bytes, characters: list[dict]) -> SynthResult:
        # 응답의 글자 중 공백이 아닌 것만 시간 순서대로 모은다(여러 글자가 한 항목이면 시간을 균등 분할)
        returned: list[tuple[str, float, float]] = []
        for item in characters:
            text = str(item.get("text", ""))
            visible = [ch for ch in text if not ch.isspace()]
            if not visible:
                continue
            start, end = float(item["start"]), float(item["end"])
            step = (end - start) / len(visible)
            for k, ch in enumerate(visible):
                returned.append((ch, start + step * k, start + step * (k + 1)))
        expected = [(i, k, ch) for i, line in enumerate(lines) for k, ch in enumerate(line) if not ch.isspace()]
        if len(returned) != len(expected):
            raise TTSError(
                f"타입캐스트가 돌려준 글자 수({len(returned)})가 문구의 글자 수({len(expected)})와 달라 "
                "줄별 타이밍을 맞출 수 없습니다(숫자나 기호를 다르게 읽었을 수 있습니다). "
                ".env에서 TTS_PROVIDER=per_line, PER_LINE_BACKEND=typecast 로 바꿔 시도하세요.")
        differing = sum(1 for (_, _, want), (got, _, _) in zip(expected, returned) if want != got)
        by_pos = {(i, k): (s, e) for (i, k, _), (_, s, e) in zip(expected, returned)}

        timings: list[LineTiming] = []
        last_end = 0.0
        for i, line in enumerate(lines):
            if not any(not ch.isspace() for ch in line):
                raise TTSError(f"{i + 1}번째 줄이 비어 있습니다.")
            chars = []
            first = last = None
            for k, ch in enumerate(line):
                if ch.isspace():
                    chars.append([ch, round(last_end, 3), round(last_end, 3)])
                    continue
                s, e = by_pos[(i, k)]
                chars.append([ch, round(s, 3), round(e, 3)])
                last_end = e
                first = s if first is None else first
                last = e
            timings.append(LineTiming(index=i, text=line, start=round(first, 3), end=round(last, 3), chars=chars))
        meta = {"warnings": [f"응답 글자 {differing}개가 문구와 달라 순서대로 대응시켰습니다. 발음·자막 타이밍을 확인하세요."]} \
            if differing else {}
        return SynthResult(audio=audio, lines=timings, duration=round(max(t.end for t in timings), 3), meta=meta)
