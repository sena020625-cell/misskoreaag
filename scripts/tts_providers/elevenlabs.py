"""ElevenLabs (with-timestamps) 공급자. 글자 단위 타이밍으로 줄별 시작·끝을 계산한다."""
from __future__ import annotations

import base64
from typing import Mapping

import requests

from .base import LineTiming, SynthResult, TTSError, TTSProvider, require_env

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
OUTPUT_FORMAT = "mp3_44100_128"
JOINER = "\n"  # 줄 사이를 잠깐 쉬게 한다


class ElevenLabsProvider(TTSProvider):
    name = "elevenlabs"

    def __init__(self, api_key: str, voice_id: str, model_id: str, voice_settings: dict):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.voice_settings = voice_settings

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ElevenLabsProvider":
        key = require_env(env, "ELEVENLABS_API_KEY", "ElevenLabs 계정의 API 키를 넣어주세요.")
        voice = require_env(env, "ELEVENLABS_VOICE_ID", "채널 고정 보이스 ID를 넣어주세요.")
        model = (env.get("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2").strip()
        settings = {}
        for env_key, field in (("ELEVENLABS_STABILITY", "stability"),
                               ("ELEVENLABS_SIMILARITY", "similarity_boost"),
                               ("ELEVENLABS_STYLE", "style"),
                               ("ELEVENLABS_SPEED", "speed")):
            raw = (env.get(env_key) or "").strip()
            if raw:
                try:
                    settings[field] = float(raw)
                except ValueError:
                    raise TTSError(f".env의 {env_key} 값 '{raw}'이 숫자가 아닙니다.")
        return cls(key, voice, model, settings)

    def describe(self) -> dict:
        return {"provider": self.name, "voice_id": self.voice_id, "model": self.model_id,
                "voice_settings": self.voice_settings}

    def estimate_cost(self, lines: list[str]) -> str:
        chars = len(JOINER.join(lines))
        return f"약 {chars}자 (ElevenLabs 크레딧은 모델에 따라 글자당 0.5~1 차감)"

    def synthesize(self, lines: list[str]) -> SynthResult:
        text = JOINER.join(lines)
        payload = {"text": text, "model_id": self.model_id}
        if self.voice_settings:
            payload["voice_settings"] = self.voice_settings
        try:
            resp = requests.post(
                API.format(voice_id=self.voice_id),
                params={"output_format": OUTPUT_FORMAT},
                headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            raise TTSError(f"ElevenLabs에 연결하지 못했습니다: {exc.__class__.__name__}")
        if resp.status_code != 200:
            raise TTSError(self._explain(resp))
        data = resp.json()
        audio = base64.b64decode(data["audio_base64"])
        alignment = data.get("alignment")
        if not alignment or len(alignment.get("characters", [])) != len(text):
            alignment = data.get("normalized_alignment")
        if not alignment or len(alignment.get("characters", [])) != len(text):
            raise TTSError("ElevenLabs가 글자 타이밍을 돌려주지 않았거나 글자 수가 맞지 않습니다. "
                           "다른 모델이나 per_line 공급자를 써보세요.")
        return self._build(lines, audio, alignment)

    @staticmethod
    def _build(lines: list[str], audio: bytes, alignment: dict) -> SynthResult:
        starts = alignment["character_start_times_seconds"]
        ends = alignment["character_end_times_seconds"]
        chars = alignment["characters"]
        timings: list[LineTiming] = []
        pos = 0
        for i, line in enumerate(lines):
            idxs = [pos + k for k, ch in enumerate(line) if not ch.isspace()]
            if not idxs:
                raise TTSError(f"{i + 1}번째 줄이 비어 있습니다.")
            line_chars = [[chars[pos + k], round(starts[pos + k], 3), round(ends[pos + k], 3)]
                          for k in range(len(line))]
            timings.append(LineTiming(index=i, text=line,
                                      start=round(starts[idxs[0]], 3),
                                      end=round(ends[idxs[-1]], 3),
                                      chars=line_chars))
            pos += len(line) + len(JOINER)
        return SynthResult(audio=audio, lines=timings, duration=round(max(ends), 3))

    @staticmethod
    def _explain(resp: requests.Response) -> str:
        code = resp.status_code
        try:
            detail = resp.json().get("detail")
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("status")
            detail = str(detail)[:200] if detail else ""
        except ValueError:
            detail = resp.text[:200]
        hint = {
            401: "API 키가 올바르지 않거나 권한이 없습니다. .env의 ELEVENLABS_API_KEY를 확인하세요.",
            402: "플랜에서 허용하지 않는 요청입니다(유료 플랜 필요).",
            404: "보이스 ID를 찾을 수 없습니다. .env의 ELEVENLABS_VOICE_ID를 확인하세요.",
            422: "요청 값이 올바르지 않습니다(보이스 ID나 모델 ID를 확인하세요).",
            429: "요청이 너무 많거나 크레딧이 부족합니다. 잠시 후 다시 시도하거나 크레딧을 확인하세요.",
        }.get(code, "ElevenLabs 요청이 실패했습니다.")
        return f"ElevenLabs 오류 {code}: {hint}" + (f" ({detail})" if detail else "")
