"""타입캐스트 공급자 시험 (API 키 불필요, 공식 문서의 응답 구조를 본뜬 가짜 응답 사용)."""
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tts_providers import get_provider  # noqa: E402
from tts_providers.base import TTSError, silent_wav  # noqa: E402
from tts_providers.typecast import TypecastProvider, TypecastSettings  # noqa: E402

LINES = ["안녕하세요?!", "두 번째 줄이에요."]
ENV = {"TYPECAST_API_KEY": "SECRET123", "TYPECAST_VOICE_ID": "tc_abc"}


def chars_response(lines, with_newline=True, step=0.1):
    """공식 응답 형태: characters = [{text, start, end}] (초 단위)."""
    text = "\n".join(lines)
    out = []
    for i, ch in enumerate(text):
        if ch == "\n" and not with_newline:
            continue
        out.append({"text": ch, "start": round(i * step, 3), "end": round((i + 1) * step, 3)})
    return {"audio": base64.b64encode(b"mp3bytes").decode(), "audio_format": "mp3",
            "audio_duration": round(len(text) * step, 3), "words": None, "characters": out}


def response(status=200, body=None, content=b""):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    r.content = content
    r.text = "x"
    return r


class SettingsTests(unittest.TestCase):
    def test_defaults_and_payload(self):
        s = TypecastSettings.from_env(ENV)
        body = s.payload("안녕", "mp3")
        self.assertEqual(body, {"text": "안녕", "voice_id": "tc_abc", "model": "ssfm-v30", "language": "kor",
                                "output": {"audio_format": "mp3"}})

    def test_options_land_in_payload(self):
        s = TypecastSettings.from_env({**ENV, "TYPECAST_EMOTION": "happy", "TYPECAST_EMOTION_INTENSITY": "1.5",
                                       "TYPECAST_TEMPO": "1.1", "TYPECAST_PITCH": "-2", "TYPECAST_VOLUME": "120"})
        body = s.payload("x", "mp3")
        self.assertEqual(body["prompt"], {"emotion_type": "preset", "emotion_preset": "happy", "emotion_intensity": 1.5})
        self.assertEqual(body["output"], {"audio_format": "mp3", "audio_tempo": 1.1, "audio_pitch": -2, "volume": 120})

    def test_smart_emotion_and_v21_prompt_shape(self):
        smart = TypecastSettings.from_env({**ENV, "TYPECAST_EMOTION": "smart"}).payload("x", "mp3")
        self.assertEqual(smart["prompt"], {"emotion_type": "smart"})
        v21 = TypecastSettings.from_env({**ENV, "TYPECAST_MODEL": "ssfm-v21", "TYPECAST_EMOTION": "sad"}).payload("x", "mp3")
        self.assertEqual(v21["prompt"], {"emotion_preset": "sad", "emotion_intensity": 1.0})

    def test_validation_errors(self):
        bad_envs = [
            {"TYPECAST_VOICE_ID": "tc_abc"},                                   # 키 없음
            {"TYPECAST_API_KEY": "k"},                                         # 보이스 없음
            {**ENV, "TYPECAST_VOICE_ID": "abc"},                               # 접두사 없음
            {**ENV, "TYPECAST_MODEL": "ssfm-v99"},
            {**ENV, "TYPECAST_EMOTION": "joy"},
            {**ENV, "TYPECAST_MODEL": "ssfm-v21", "TYPECAST_EMOTION": "smart"},
            {**ENV, "TYPECAST_TEMPO": "3"},
            {**ENV, "TYPECAST_PITCH": "1.5"},
            {**ENV, "TYPECAST_VOLUME": "100", "TYPECAST_TARGET_LUFS": "-14"},  # 동시 사용 불가
        ]
        for env in bad_envs:
            with self.assertRaises(TTSError, msg=str(env)):
                TypecastSettings.from_env(env)

    def test_text_limit(self):
        with self.assertRaises(TTSError):
            TypecastSettings.from_env(ENV).payload("가" * 2001, "mp3")


class SynthesizeTests(unittest.TestCase):
    def synth(self, body, lines=LINES):
        with mock.patch("requests.post", return_value=response(200, body)) as post:
            result = get_provider("typecast", ENV).synthesize(lines)
        return result, post

    def test_request_shape(self):
        _, post = self.synth(chars_response(LINES))
        self.assertTrue(post.call_args.args[0].endswith("/v1/text-to-speech/with-timestamps"))
        self.assertEqual(post.call_args.kwargs["params"], {"granularity": "char"})
        self.assertEqual(post.call_args.kwargs["headers"]["X-API-KEY"], "SECRET123")
        self.assertEqual(post.call_args.kwargs["json"]["text"], "\n".join(LINES))

    def test_line_timings_when_newline_is_included(self):
        result, _ = self.synth(chars_response(LINES, with_newline=True))
        first, second = result.lines
        self.assertEqual((first.start, first.end), (0.0, round(len(LINES[0]) * 0.1, 3)))
        offset = len(LINES[0]) + 1
        self.assertEqual(second.start, round(offset * 0.1, 3))
        self.assertEqual(second.end, round((offset + len(LINES[1])) * 0.1, 3))
        self.assertEqual(len(second.chars), len(LINES[1]))
        self.assertEqual(result.audio, b"mp3bytes")
        self.assertEqual(result.duration, round(len("\n".join(LINES)) * 0.1, 3))

    def test_line_timings_when_newline_is_dropped(self):
        result, _ = self.synth(chars_response(LINES, with_newline=False))
        self.assertEqual(len(result.lines), 2)
        self.assertLess(result.lines[0].end, result.lines[1].start + 1e-9)
        self.assertFalse(result.meta.get("warnings"))

    def test_multi_character_items_are_split_evenly(self):
        body = chars_response(["가나"])
        body["characters"] = [{"text": "가나", "start": 0.0, "end": 0.4}]
        result, _ = self.synth(body, lines=["가나"])
        self.assertEqual([c[1:] for c in result.lines[0].chars], [[0.0, 0.2], [0.2, 0.4]])

    def test_count_mismatch_suggests_per_line(self):
        body = chars_response(LINES)
        body["characters"] = body["characters"][:-3]
        with mock.patch("requests.post", return_value=response(200, body)):
            with self.assertRaises(TTSError) as ctx:
                get_provider("typecast", ENV).synthesize(LINES)
        self.assertIn("per_line", str(ctx.exception))

    def test_differing_text_warns_but_maps_by_position(self):
        body = chars_response(LINES)
        body["characters"][0]["text"] = "X"
        result, _ = self.synth(body)
        self.assertTrue(result.meta["warnings"])

    def test_missing_characters_is_error(self):
        body = chars_response(LINES)
        body["characters"] = None
        with mock.patch("requests.post", return_value=response(200, body)):
            with self.assertRaises(TTSError):
                get_provider("typecast", ENV).synthesize(LINES)

    def test_http_errors_have_hints_and_hide_key(self):
        for code, word in ((401, "API 키"), (402, "크레딧"), (404, "보이스"), (422, "합성할 수 없습니다"), (429, "한도")):
            r = response(code, {"message": "boom", "error_code": "X"})
            with mock.patch("requests.post", return_value=r):
                with self.assertRaises(TTSError) as ctx:
                    get_provider("typecast", ENV).synthesize(LINES)
            self.assertIn(word, str(ctx.exception))
            self.assertNotIn("SECRET123", str(ctx.exception))


class PerLineBackendTests(unittest.TestCase):
    def test_per_line_with_typecast_backend(self):
        env = {**ENV, "PER_LINE_BACKEND": "typecast"}
        with mock.patch("requests.post", return_value=response(200, content=silent_wav(0.5))) as post:
            result = get_provider("per_line", env).synthesize(LINES)
        self.assertEqual(post.call_count, 2)
        self.assertTrue(post.call_args.args[0].endswith("/v1/text-to-speech"))
        self.assertEqual(post.call_args.kwargs["json"]["output"]["audio_format"], "wav")
        self.assertEqual(len(result.lines), 2)
        self.assertLess(result.lines[0].end, result.lines[1].start)

    def test_per_line_typecast_needs_key(self):
        with self.assertRaises(TTSError):
            get_provider("per_line", {"PER_LINE_BACKEND": "typecast"})


if __name__ == "__main__":
    unittest.main()
