"""테스트 전용 공급자. API 없이 글자 수에 비례한 길이의 무음 오디오를 만든다.

자막·렌더링 단계를 키 없이 시험할 때만 쓴다. 실제 영상에는 쓰지 말 것.
"""
from __future__ import annotations

from typing import Mapping

from .base import SynthResult, TTSProvider, assemble_clips, silent_wav

SECONDS_PER_CHAR = 0.18
MIN_LINE_SECONDS = 0.6
GAP = 0.25


class MockProvider(TTSProvider):
    name = "mock"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "MockProvider":
        return cls()

    def describe(self) -> dict:
        return {"provider": self.name, "note": "테스트 전용 무음 오디오"}

    def estimate_cost(self, lines: list[str]) -> str:
        return "무료(무음 테스트 오디오)"

    def synthesize(self, lines: list[str]) -> SynthResult:
        wavs = [silent_wav(max(MIN_LINE_SECONDS, len("".join(line.split())) * SECONDS_PER_CHAR))
                for line in lines]
        return assemble_clips(lines, wavs, GAP)
