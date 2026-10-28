"""타입캐스트 보이스 검색 시험 (API 불필요)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tts_providers.base import TTSError  # noqa: E402
from tts_providers.typecast import TypecastSettings  # noqa: E402
from typecast_voices import describe, fetch_voices, search_voices  # noqa: E402

VOICES = [
    {"voice_id": "tc_aaa", "voice_name": {"eng": "Hyewon", "kor": "혜원"}, "voice_type": "original",
     "models": [{"version": "ssfm-v30", "emotions": ["normal"]}], "gender": "female", "age": "middle_age",
     "use_cases": ["TikTok/Reels/Shorts"]},
    {"voice_id": "tc_bbb", "voice_name": {"eng": "Minho", "kor": "민호"}, "voice_type": "original",
     "models": [], "gender": "male", "age": None, "use_cases": []},
]


class VoiceSearchTests(unittest.TestCase):
    def test_search_by_korean_and_english_name(self):
        self.assertEqual([v["voice_id"] for v in search_voices(VOICES, "혜원")], ["tc_aaa"])
        self.assertEqual([v["voice_id"] for v in search_voices(VOICES, "MINHO")], ["tc_bbb"])
        self.assertEqual(len(search_voices(VOICES, "")), 2)
        self.assertEqual(search_voices(VOICES, "없는이름"), [])

    def test_describe_handles_missing_fields(self):
        self.assertIn("tc_aaa", describe(VOICES[0]))
        text = describe(VOICES[1])
        self.assertIn("male/-", text)
        self.assertTrue(text.endswith("모델: -"))

    def test_fetch_error_has_hint_and_hides_key(self):
        r = mock.Mock(status_code=401)
        r.json.return_value = {"detail": "Invalid API key"}
        with mock.patch("requests.get", return_value=r):
            with self.assertRaises(TTSError) as ctx:
                fetch_voices("SECRET123", None)
        self.assertIn("API 키", str(ctx.exception))
        self.assertNotIn("SECRET123", str(ctx.exception))

    def test_name_as_voice_id_points_to_the_search_tool(self):
        with self.assertRaises(TTSError) as ctx:
            TypecastSettings.from_env({"TYPECAST_API_KEY": "k", "TYPECAST_VOICE_ID": "혜원"})
        self.assertIn("typecast_voices.py 혜원", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
