"""TTS 공급자 로직 시험 (API 키 불필요). 실행: python -m unittest discover -s tests"""
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tts_providers import get_provider  # noqa: E402
from tts_providers.base import TTSError  # noqa: E402
from tts_providers.elevenlabs import ElevenLabsProvider  # noqa: E402

LINES = ["안녕하세요?!", "두 번째 줄이에요."]
TEXT = "\n".join(LINES)


def fake_alignment(text, step=0.1):
    return {
        "characters": list(text),
        "character_start_times_seconds": [round(i * step, 3) for i in range(len(text))],
        "character_end_times_seconds": [round((i + 1) * step, 3) for i in range(len(text))],
    }


def fake_response(status=200, body=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    resp.text = "x"
    return resp


ENV = {"ELEVENLABS_API_KEY": "k", "ELEVENLABS_VOICE_ID": "v"}


class ElevenLabsTests(unittest.TestCase):
    def test_line_timings_from_char_alignment(self):
        body = {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": fake_alignment(TEXT)}
        with mock.patch("requests.post", return_value=fake_response(200, body)) as post:
            result = ElevenLabsProvider.from_env(ENV).synthesize(LINES)
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["text"], TEXT)
        self.assertEqual(result.audio, b"mp3")
        first, second = result.lines
        self.assertEqual((first.start, first.end), (0.0, round(len(LINES[0]) * 0.1, 3)))
        offset = len(LINES[0]) + 1  # 줄바꿈 한 글자
        self.assertEqual(second.start, round(offset * 0.1, 3))
        self.assertEqual(second.end, round((offset + len(LINES[1])) * 0.1, 3))
        self.assertEqual(len(first.chars), len(LINES[0]))
        self.assertEqual(result.duration, round(len(TEXT) * 0.1, 3))

    def test_falls_back_to_normalized_alignment(self):
        bad = fake_alignment(TEXT[:-1])
        body = {"audio_base64": base64.b64encode(b"a").decode(), "alignment": bad,
                "normalized_alignment": fake_alignment(TEXT)}
        with mock.patch("requests.post", return_value=fake_response(200, body)):
            result = ElevenLabsProvider.from_env(ENV).synthesize(LINES)
        self.assertEqual(len(result.lines), 2)

    def test_missing_alignment_is_error(self):
        body = {"audio_base64": base64.b64encode(b"a").decode()}
        with mock.patch("requests.post", return_value=fake_response(200, body)):
            with self.assertRaises(TTSError):
                ElevenLabsProvider.from_env(ENV).synthesize(LINES)

    def test_http_errors_have_hints_and_hide_key(self):
        for code, word in ((401, "API 키"), (404, "보이스 ID"), (429, "크레딧")):
            resp = fake_response(code, {"detail": {"message": "boom"}})
            with mock.patch("requests.post", return_value=resp):
                with self.assertRaises(TTSError) as ctx:
                    ElevenLabsProvider.from_env({**ENV, "ELEVENLABS_API_KEY": "SECRET123"}).synthesize(LINES)
            self.assertIn(word, str(ctx.exception))
            self.assertNotIn("SECRET123", str(ctx.exception))

    def test_missing_env(self):
        with self.assertRaises(TTSError):
            ElevenLabsProvider.from_env({"ELEVENLABS_VOICE_ID": "v"})
        with self.assertRaises(TTSError):
            ElevenLabsProvider.from_env({"ELEVENLABS_API_KEY": "k"})

    def test_voice_settings_parsed_and_validated(self):
        p = ElevenLabsProvider.from_env({**ENV, "ELEVENLABS_STABILITY": "0.4", "ELEVENLABS_SPEED": "1.1"})
        self.assertEqual(p.voice_settings, {"stability": 0.4, "speed": 1.1})
        with self.assertRaises(TTSError):
            ElevenLabsProvider.from_env({**ENV, "ELEVENLABS_STABILITY": "abc"})


class OtherProviderTests(unittest.TestCase):
    def test_unknown_provider(self):
        with self.assertRaises(TTSError):
            get_provider("nope", {})

    def test_per_line_requires_backend(self):
        with self.assertRaises(TTSError):
            get_provider("per_line", {})

    def test_mock_timings_are_sequential(self):
        result = get_provider("mock", {}).synthesize(LINES)
        a, b = result.lines
        self.assertLess(a.end, b.start)
        self.assertGreater(len(result.audio), 100)


if __name__ == "__main__":
    unittest.main()
