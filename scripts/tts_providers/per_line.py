"""줄별 합성형 공급자.

글자 타이밍을 주지 않는 TTS도 쓸 수 있게, 줄마다 따로 합성해 길이를 재고 이어 붙인다.
줄 사이에 PER_LINE_GAP 초(기본 0.25)의 쉼을 넣는다.

새 TTS를 붙이려면 아래 BACKENDS 에 `(text, env) -> mp3 bytes` 함수를 하나 추가하고
.env 의 PER_LINE_BACKEND 에 그 이름을 쓴다.
"""
from __future__ import annotations

from typing import Callable, Mapping

import requests

from .base import SynthResult, TTSError, TTSProvider, assemble_clips, mp3_to_wav, require_env


def _openai_backend(text: str, env: Mapping[str, str]) -> bytes:
    """OpenAI TTS 예시 백엔드(한국어 지원). 실제 계정으로는 아직 검증하지 않았다."""
    key = require_env(env, "OPENAI_API_KEY", "OpenAI API 키를 넣어주세요.")
    payload = {
        "model": (env.get("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts").strip(),
        "voice": (env.get("OPENAI_TTS_VOICE") or "alloy").strip(),
        "input": text,
        "response_format": "mp3",
    }
    instructions = (env.get("OPENAI_TTS_INSTRUCTIONS") or "").strip()
    if instructions:
        payload["instructions"] = instructions
    try:
        resp = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=120,
        )
    except requests.RequestException as exc:
        raise TTSError(f"OpenAI에 연결하지 못했습니다: {exc.__class__.__name__}")
    if resp.status_code != 200:
        raise TTSError(f"OpenAI TTS 오류 {resp.status_code}: {resp.text[:200]}")
    return resp.content


def _typecast_backend(text: str, env: Mapping[str, str]) -> bytes:
    """타입캐스트 일반 TTS 로 한 줄을 합성한다(글자 타이밍 정렬이 맞지 않을 때의 대안)."""
    from .typecast import TypecastSettings, synth_plain
    return synth_plain(TypecastSettings.from_env(env), text)


BACKENDS: dict[str, Callable[[str, Mapping[str, str]], bytes]] = {
    "openai": _openai_backend,
    "typecast": _typecast_backend,
}


class PerLineProvider(TTSProvider):
    name = "per_line"

    def __init__(self, backend: str, env: Mapping[str, str], gap: float):
        self.backend = backend
        self.env = dict(env)
        self.gap = gap

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "PerLineProvider":
        backend = (env.get("PER_LINE_BACKEND") or "").strip()
        if backend not in BACKENDS:
            raise TTSError(f".env의 PER_LINE_BACKEND를 {', '.join(BACKENDS)} 중에서 골라주세요(현재: '{backend}').")
        raw_gap = (env.get("PER_LINE_GAP") or "0.25").strip()
        try:
            gap = float(raw_gap)
        except ValueError:
            raise TTSError(f".env의 PER_LINE_GAP 값 '{raw_gap}'이 숫자가 아닙니다.")
        # 키 누락을 합성 전에 알 수 있도록 설정만 먼저 점검한다
        if backend == "openai":
            require_env(env, "OPENAI_API_KEY", "OpenAI API 키를 넣어주세요.")
        if backend == "typecast":
            from .typecast import TypecastSettings
            TypecastSettings.from_env(env)
        return cls(backend, env, gap)

    def describe(self) -> dict:
        info = {"provider": self.name, "backend": self.backend, "gap": self.gap}
        if self.backend == "openai":
            info["model"] = (self.env.get("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts").strip()
            info["voice"] = (self.env.get("OPENAI_TTS_VOICE") or "alloy").strip()
        if self.backend == "typecast":
            from .typecast import TypecastSettings
            info.update({k: v for k, v in TypecastSettings.from_env(self.env).describe().items() if k != "provider"})
        return info

    def estimate_cost(self, lines: list[str]) -> str:
        return f"{len(lines)}회 호출, 총 {sum(len(x) for x in lines)}자"

    def synthesize(self, lines: list[str]) -> SynthResult:
        backend = BACKENDS[self.backend]
        wavs = [mp3_to_wav(backend(line, self.env)) for line in lines]
        return assemble_clips(lines, wavs, self.gap)
