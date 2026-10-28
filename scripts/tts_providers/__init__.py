from __future__ import annotations

from typing import Mapping

from .base import TTSError, TTSProvider
from .elevenlabs import ElevenLabsProvider
from .mock import MockProvider
from .per_line import PerLineProvider
from .typecast import TypecastProvider

PROVIDERS: dict[str, type[TTSProvider]] = {
    "elevenlabs": ElevenLabsProvider,
    "typecast": TypecastProvider,
    "per_line": PerLineProvider,
    "mock": MockProvider,
}


def get_provider(name: str, env: Mapping[str, str]) -> TTSProvider:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise TTSError(f"알 수 없는 TTS 공급자 '{name}'입니다. 사용 가능: {', '.join(PROVIDERS)}")
    return cls.from_env(env)
