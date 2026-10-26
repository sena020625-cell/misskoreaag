"""렌더링 로직 시험(폰트·ffmpeg 불필요). 실행: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import ScriptError, load_template  # noqa: E402
from render import build_filter, parse_srt, resolve_font  # noqa: E402

CFG = load_template(Path("/nonexistent-workdir"))  # 플러그인 기본 template.yaml 만 사용


class SrtTests(unittest.TestCase):
    def test_parse_two_line_cues_and_bom_crlf(self):
        text = ("﻿1\r\n00:00:00,000 --> 00:00:02,540\r\n립을 바르고\r\n닦아낸다고요?!\r\n\r\n"
                "2\r\n00:01:01,500 --> 00:01:02,000\r\n안녕\r\n")
        cues = parse_srt(text)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].lines, ["립을 바르고", "닦아낸다고요?!"])
        self.assertAlmostEqual(cues[0].end, 2.54)
        self.assertAlmostEqual(cues[1].start, 61.5)

    def test_empty(self):
        self.assertEqual(parse_srt(""), [])


class FilterTests(unittest.TestCase):
    overlays = [(3, 0.0, 2.5, 1300), (4, 2.6, 6.0, 1300)]

    def test_cover_with_source_audio(self):
        f = build_filter(CFG, self.overlays, source_has_audio=True, with_audio=True)
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920", f)
        self.assertIn("[v0][2:v]overlay=0:0[t0]", f)
        self.assertIn("[t0][3:v]overlay=x=0:y=1300:enable='between(t,0.000,2.500)'[c0]", f)
        self.assertIn("[c0][4:v]overlay=x=0:y=1300:enable='between(t,2.600,6.000)'[c1]", f)
        self.assertIn("[c1]format=yuv420p[vout]", f)
        self.assertIn("[0:a]volume=0.12", f)
        self.assertIn("amix=inputs=2:duration=longest:normalize=0[aout]", f)

    def test_source_without_audio_uses_only_tts(self):
        f = build_filter(CFG, self.overlays, source_has_audio=False, with_audio=True)
        self.assertNotIn("[0:a]", f)
        self.assertIn("[1:a]volume=1.0,aresample=44100[aout]", f)

    def test_preview_has_no_audio_graph(self):
        f = build_filter(CFG, self.overlays, source_has_audio=True, with_audio=False)
        self.assertNotIn("aout", f)

    def test_contain_blur(self):
        cfg = {**CFG, "video": {**CFG["video"], "fit": "contain_blur"}}
        f = build_filter(cfg, [], True, False)
        self.assertIn("boxblur", f)
        self.assertIn("[bg][fg]overlay=(W-w)/2:(H-h)/2", f)

    def test_invalid_fit(self):
        cfg = {**CFG, "video": {**CFG["video"], "fit": "stretch"}}
        with self.assertRaises(ScriptError):
            build_filter(cfg, [], True, False)


class FontTests(unittest.TestCase):
    def test_missing_font_message(self):
        with self.assertRaises(ScriptError) as ctx:
            resolve_font("assets/fonts/NoSuchFont.ttf", Path("/nonexistent-workdir"))
        self.assertIn("assets/fonts", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
