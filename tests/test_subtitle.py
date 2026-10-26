"""자막 로직 시험. 실행: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from subtitle import SubtitleConfig, build_cues, to_srt, wrap_spans  # noqa: E402


def wrapped(text, n):
    return [text[a:b] for a, b in wrap_spans(text, n)]


def line(index, text, start, end, with_chars=False):
    d = {"index": index, "text": text, "start": start, "end": end}
    if with_chars:
        step = (end - start) / len(text)
        d["chars"] = [[ch, round(start + i * step, 3), round(start + (i + 1) * step, 3)]
                      for i, ch in enumerate(text)]
    return d


class WrapTests(unittest.TestCase):
    def test_short_text_stays_one_line(self):
        self.assertEqual(wrapped("립을 바르고 닦아낸다고요?!", 16), ["립을 바르고 닦아낸다고요?!"])

    def test_breaks_after_punctuation_and_balances(self):
        out = wrapped("10초에서 30초 뒤, 젖은 수건으로 부드럽게 닦아내요!", 16)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(len(x) <= 16 for x in out))
        self.assertTrue(abs(len(out[0]) - len(out[1])) <= 4)

    def test_prefers_comma_when_balanced_enough(self):
        out = wrapped("바르고 기다리고, 슥 닦아내면 끝이에요 정말로", 16)
        self.assertTrue(out[0].endswith(","), out)

    def test_never_exceeds_max_and_never_loses_text(self):
        text = "에이프릴스킨의 히어로 올데이 플럼핑 틴트인데요, 이 방식 괜히 궁금해지지 않나요?!"
        out = wrapped(text, 16)
        self.assertTrue(all(len(x) <= 16 for x in out))
        self.assertEqual("".join(out).replace(" ", ""), text.replace(" ", ""))

    def test_long_word_is_hard_split(self):
        out = wrapped("가나다라마바사아자차카타파하가나다라", 8)
        self.assertTrue(all(len(x) <= 8 for x in out))
        self.assertEqual("".join(out), "가나다라마바사아자차카타파하가나다라")

    def test_empty(self):
        self.assertEqual(wrap_spans("   ", 16), [])


class CueTests(unittest.TestCase):
    cfg = SubtitleConfig()

    def test_two_lines_in_one_cue(self):
        timing = {"lines": [line(0, "10초에서 30초 뒤, 젖은 수건으로 부드럽게 닦아내요!", 1.0, 5.0)]}
        cues = build_cues(timing, self.cfg)
        self.assertEqual(len(cues), 1)
        self.assertEqual(len(cues[0].lines), 2)
        self.assertAlmostEqual(cues[0].start, 1.0, places=2)

    def test_long_line_splits_into_multiple_cues_with_max_two_lines(self):
        text = "가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차 카타파 하가나 다라마 바사아"
        timing = {"lines": [line(0, text, 0.0, 8.0, with_chars=True)]}
        cues = build_cues(timing, self.cfg)
        self.assertGreater(len(cues), 1)
        self.assertTrue(all(len(c.lines) <= 2 for c in cues))
        for a, b in zip(cues, cues[1:]):
            self.assertLess(a.end, b.start)
            self.assertLess(a.start, b.start)

    def test_proportional_timing_without_chars(self):
        text = "가나다라마바사아 자차카타파하가나 다라마바사아자차 카타파하"
        timing = {"lines": [line(0, text, 0.0, 6.0)]}
        cues = build_cues(timing, SubtitleConfig(hold=0, min_duration=0))
        self.assertAlmostEqual(cues[0].start, 0.0, places=2)
        self.assertAlmostEqual(cues[-1].end, 6.0, places=2)

    def test_strip_end_comma_and_period_only(self):
        timing = {"lines": [line(0, "인데요,", 0, 1), line(1, "끝이에요.", 2, 3), line(2, "정말요?!", 4, 5),
                            line(3, "그럼…", 6, 7)]}
        shown = [c.lines[-1] for c in build_cues(timing, self.cfg)]
        self.assertEqual(shown, ["인데요", "끝이에요", "정말요?!", "그럼…"])

    def test_hold_and_min_duration_never_overlap_next_cue(self):
        timing = {"lines": [line(0, "짧아요", 0.0, 0.2), line(1, "다음이에요", 0.5, 1.5)]}
        a, b = build_cues(timing, self.cfg)
        self.assertGreaterEqual(a.end - a.start, 0.29)
        self.assertLess(a.end, b.start)

    def test_srt_format(self):
        timing = {"lines": [line(0, "안녕하세요", 3661.5, 3662.0)]}
        srt = to_srt(build_cues(timing, SubtitleConfig(hold=0, min_duration=0)))
        self.assertTrue(srt.startswith("1\n01:01:01,500 --> 01:01:02,000\n안녕하세요"))


if __name__ == "__main__":
    unittest.main()
