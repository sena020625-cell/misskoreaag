"""TTS 공급자 공통 정의와 오디오 유틸.

새 공급자를 붙이려면 TTSProvider를 상속해 from_env / describe / synthesize를 구현하고
tts_providers/__init__.py 의 PROVIDERS 에 등록한다.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Mapping, Optional

SAMPLE_RATE = 44100


class TTSError(RuntimeError):
    """사용자에게 그대로 보여줄 수 있는 TTS 오류."""


@dataclass
class LineTiming:
    index: int
    text: str
    start: float
    end: float
    # 글자 단위 타이밍을 주는 공급자만 채운다: [[글자, 시작, 끝], ...]
    chars: Optional[list] = None


@dataclass
class SynthResult:
    audio: bytes  # mp3
    lines: list[LineTiming]
    duration: float
    meta: dict = field(default_factory=dict)


class TTSProvider(ABC):
    name: str = ""

    @classmethod
    @abstractmethod
    def from_env(cls, env: Mapping[str, str]) -> "TTSProvider":
        """환경 변수(.env)에서 설정을 읽어 공급자를 만든다. 누락되면 TTSError."""

    @abstractmethod
    def describe(self) -> dict:
        """캐시 키와 timing.json에 기록할 비밀 아닌 설정(공급자, 보이스, 모델 등)."""

    @abstractmethod
    def synthesize(self, lines: list[str]) -> SynthResult:
        """줄 목록을 합성해 mp3와 줄별 타이밍을 돌려준다."""

    def estimate_cost(self, lines: list[str]) -> str:
        return f"{sum(len(x) for x in lines)}자"


def require_env(env: Mapping[str, str], key: str, hint: str = "") -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise TTSError(f".env에 {key} 값이 없습니다. {hint}".strip())
    return value


# ---- ffmpeg 유틸 (줄별 합성형 공급자와 mock 이 사용) ----

def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise TTSError("ffmpeg를 찾을 수 없습니다. ffmpeg를 설치하고 PATH에 추가하세요.")
    return path


def mp3_to_wav(mp3: bytes) -> bytes:
    proc = subprocess.run(
        [find_ffmpeg(), "-v", "error", "-i", "pipe:0", "-f", "wav",
         "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"],
        input=mp3, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise TTSError("오디오 변환(mp3→wav)에 실패했습니다: " + proc.stderr.decode("utf-8", "replace")[:300])
    return proc.stdout


def wav_to_mp3(wav_bytes: bytes) -> bytes:
    proc = subprocess.run(
        [find_ffmpeg(), "-v", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"],
        input=wav_bytes, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise TTSError("오디오 변환(wav→mp3)에 실패했습니다: " + proc.stderr.decode("utf-8", "replace")[:300])
    return proc.stdout


def silent_wav(seconds: float) -> bytes:
    frames = int(round(seconds * SAMPLE_RATE))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


def assemble_clips(texts: list[str], wavs: list[bytes], gap: float) -> SynthResult:
    """줄별 wav 클립을 gap 초 간격으로 이어 붙이고, 샘플 수로 정확한 줄 타이밍을 계산한다."""
    pcm = bytearray()
    timings: list[LineTiming] = []
    gap_bytes = b"\x00\x00" * int(round(gap * SAMPLE_RATE))
    for i, (text, data) in enumerate(zip(texts, wavs)):
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != SAMPLE_RATE:
                raise TTSError("클립 형식이 44.1kHz 모노 16bit가 아닙니다.")
            frames = w.readframes(w.getnframes())
        start = len(pcm) / 2 / SAMPLE_RATE
        pcm += frames
        end = len(pcm) / 2 / SAMPLE_RATE
        timings.append(LineTiming(index=i, text=text, start=round(start, 3), end=round(end, 3)))
        if i < len(texts) - 1:
            pcm += gap_bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(pcm))
    duration = len(pcm) / 2 / SAMPLE_RATE
    return SynthResult(audio=wav_to_mp3(buf.getvalue()), lines=timings, duration=round(duration, 3))
