"""출처 자동 표기 시험 (네트워크 불필요: 단축 링크 해석은 가짜 resolver 사용)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from source_credit import apply_source, build_description, parse_source_link  # noqa: E402

TT = "https://www.tiktok.com/@some.user_1/video/7300000000000000000"


def no_resolver(url):
    raise AssertionError("리졸버가 호출되면 안 되는 경우")


class ParseTests(unittest.TestCase):
    def test_tiktok_full_link_strips_tracking(self):
        info = parse_source_link(TT + "?_t=ZS-abc&_r=1&is_from_webapp=1", resolver=no_resolver)
        self.assertEqual((info.platform, info.handle, info.status), ("TikTok", "@some.user_1", "ok"))
        self.assertEqual(info.url, TT)

    def test_tiktok_without_scheme_and_mobile_host(self):
        self.assertEqual(parse_source_link("tiktok.com/@a/video/12345678", resolver=no_resolver).handle, "@a")
        self.assertEqual(parse_source_link("https://m.tiktok.com/@b/photo/12345678", resolver=no_resolver).url,
                         "https://www.tiktok.com/@b/photo/12345678")

    def test_short_link_uses_resolver(self):
        calls = []

        def fake(url):
            calls.append(url)
            return TT + "?lang=ko"

        info = parse_source_link("https://vm.tiktok.com/ZSabc123/?foo=1", resolver=fake)
        self.assertEqual((info.handle, info.status, info.url), ("@some.user_1", "ok", TT))
        self.assertEqual(calls, ["https://vm.tiktok.com/ZSabc123/"])
        self.assertTrue(info.original.startswith("https://vm.tiktok.com/"))
        self.assertEqual(parse_source_link("https://www.tiktok.com/t/ZTabc/", resolver=fake).handle, "@some.user_1")

    def test_short_link_failure_is_manual(self):
        info = parse_source_link("https://vt.tiktok.com/ZSxyz/", resolver=lambda u: None)
        self.assertEqual(info.status, "manual")
        self.assertEqual(info.handle, "")
        self.assertIn("직접 확인", info.note)

    def test_short_link_without_resolver_is_manual(self):
        self.assertEqual(parse_source_link("https://vm.tiktok.com/ZSxyz/", resolver=None).status, "manual")

    def test_tiktok_non_video_link_is_manual(self):
        self.assertEqual(parse_source_link("https://www.tiktok.com/@onlyprofile", resolver=no_resolver).status, "manual")

    def test_instagram(self):
        ok = parse_source_link("https://www.instagram.com/some_user/reel/Cxyz123/?igsh=abc")
        self.assertEqual((ok.platform, ok.handle, ok.url), ("Instagram", "@some_user", "https://www.instagram.com/some_user/reel/Cxyz123/"))
        manual = parse_source_link("https://www.instagram.com/reel/Cxyz123/?igsh=abc")
        self.assertEqual((manual.status, manual.handle), ("manual", ""))
        self.assertEqual(manual.url, "https://www.instagram.com/reel/Cxyz123/")

    def test_x_and_youtube(self):
        self.assertEqual(parse_source_link("https://twitter.com/abc/status/123456?s=20").handle, "@abc")
        self.assertEqual(parse_source_link("https://x.com/i/status/123456").status, "manual")
        self.assertEqual(parse_source_link("https://www.youtube.com/@channel/shorts").handle, "@channel")
        yt = parse_source_link("https://www.youtube.com/watch?v=abc123&t=5s")
        self.assertEqual((yt.status, yt.url), ("manual", "https://www.youtube.com/watch?v=abc123"))
        self.assertEqual(parse_source_link("https://www.youtube.com/shorts/abc123").status, "manual")

    def test_unknown_site_and_garbage(self):
        self.assertEqual(parse_source_link("https://example.com/video/1?x=1").platform, "기타")
        self.assertEqual(parse_source_link("https://example.com/video/1?x=1").url, "https://example.com/video/1")
        self.assertEqual(parse_source_link("그냥 글자").status, "manual")
        self.assertEqual(parse_source_link("").status, "none")


class DescriptionTests(unittest.TestCase):
    def test_idempotent_and_replaces_old_credit(self):
        base = "훅\n\n바로 A인데요!\n\n#태그"
        once = build_description(base, "@a", "https://x/1")
        self.assertTrue(once.endswith("\n\n📷I @a\n🔗 원본: https://x/1"))
        self.assertEqual(build_description(once, "@a", "https://x/1"), once)
        self.assertEqual(build_description(once, "@b", "").count("📷"), 1)
        self.assertTrue(build_description(once, "@b", "").endswith("📷I @b"))

    def test_no_credit_when_nothing_known(self):
        self.assertEqual(build_description("훅\n\n📷I @old", "", ""), "훅")


MD = """# 001 제품 (브랜드)

## 설명란
훅

#태그

## 검수 메모
### 기타
- 공식몰 구매 버튼에 'SOLD OUT' 표기 확인
- 크리에이터 미기재: 원본 출처 표기 필요 (설명란 📷I 줄 생략함)
- 영문·긴 제품명 발음은 TTS 생성 후 확인 필요
"""


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copy(ROOT / "templates" / "sample_script.json", self.tmp / "script.json")
        (self.tmp / "script.md").write_text(MD, encoding="utf-8")

    def load(self):
        return json.loads((self.tmp / "script.json").read_text(encoding="utf-8"))

    def test_auto_fills_creator_from_link(self):
        result = apply_source(self.tmp, TT + "?_t=1", "", resolver=no_resolver)
        self.assertEqual(result["status"], "ok")
        s = self.load()
        self.assertEqual(s["creator"], "@some.user_1")
        self.assertEqual(s["source"]["handle"], "@some.user_1")
        self.assertTrue(s["description"].endswith(f"📷I @some.user_1\n🔗 원본: {TT}"))
        self.assertTrue(any(x["label"] == "원본 영상 출처" and x["url"] == TT for x in s["review"]["sources"]))
        self.assertNotIn("크리에이터 미기재", s["review"]["notes"])
        self.assertIn("SOLD OUT", s["review"]["notes"])
        md = (self.tmp / "script.md").read_text(encoding="utf-8")
        self.assertIn("📷I @some.user_1", md)
        self.assertIn("- 원본 출처: TikTok @some.user_1", md)
        self.assertNotIn("크리에이터 미기재", md)
        self.assertIn("- 영문·긴 제품명 발음", md)

    def test_running_twice_gives_same_files(self):
        apply_source(self.tmp, TT, "", resolver=no_resolver)
        first = ((self.tmp / "script.json").read_text(encoding="utf-8"), (self.tmp / "script.md").read_text(encoding="utf-8"))
        apply_source(self.tmp, TT, "", resolver=no_resolver)
        second = ((self.tmp / "script.json").read_text(encoding="utf-8"), (self.tmp / "script.md").read_text(encoding="utf-8"))
        self.assertEqual(first, second)

    def test_csv_creator_wins_and_mismatch_is_flagged(self):
        result = apply_source(self.tmp, TT, "@someone_else", resolver=no_resolver)
        self.assertEqual(result["status"], "manual")
        s = self.load()
        self.assertEqual(s["creator"], "@someone_else")
        self.assertTrue(s["review"]["needs_review"])
        self.assertIn("다릅니다", s["review"]["notes"])

    def test_same_creator_with_or_without_at_is_not_a_mismatch(self):
        self.assertEqual(apply_source(self.tmp, TT, "SOME.user_1", resolver=no_resolver)["status"], "ok")

    def test_manual_source_keeps_link_and_flags_review(self):
        result = apply_source(self.tmp, "https://www.youtube.com/shorts/abc123", "", resolver=no_resolver)
        self.assertEqual(result["status"], "manual")
        s = self.load()
        self.assertEqual(s["creator"], "")
        self.assertTrue(s["review"]["needs_review"])
        self.assertIn("🔗 원본: https://www.youtube.com/shorts/abc123", s["description"])
        self.assertNotIn("📷I", s["description"])
        self.assertIn("직접 확인", s["review"]["notes"])

    def test_nothing_to_do_without_link_or_creator(self):
        before = (self.tmp / "script.json").read_text(encoding="utf-8")
        self.assertEqual(apply_source(self.tmp, "", "", resolver=no_resolver)["status"], "skipped")
        self.assertEqual((self.tmp / "script.json").read_text(encoding="utf-8"), before)

    def test_uses_video_link_in_script_json_when_no_link_argument(self):
        s = self.load()
        s["video_link"] = TT
        (self.tmp / "script.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(apply_source(self.tmp, "", "", resolver=no_resolver)["creator"], "@some.user_1")

    def test_works_without_markdown_file(self):
        (self.tmp / "script.md").unlink()
        self.assertEqual(apply_source(self.tmp, TT, "", resolver=no_resolver)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
