"""허락받은 파일 링크 다운로드 시험 (실제 네트워크 사용 없음)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_source  # noqa: E402
from fetch_source import FetchError, assert_public, download, normalize_url, safe_url  # noqa: E402

PUBLIC = lambda host, port: [(2, 1, 6, "", ("93.184.216.34", port))]  # noqa: E731
PRIVATE = lambda host, port: [(2, 1, 6, "", ("192.168.0.10", port))]  # noqa: E731
LOOPBACK = lambda host, port: [(2, 1, 6, "", ("127.0.0.1", port))]  # noqa: E731


def fake_response(status=200, headers=None, chunks=(b"data",)):
    r = mock.Mock()
    r.status_code = status
    r.headers = headers or {}
    r.iter_content.return_value = iter(chunks)
    return r


class NormalizeTests(unittest.TestCase):
    def test_google_drive_forms(self):
        want = "https://drive.google.com/uc?export=download&id=ABC123"
        self.assertEqual(normalize_url("https://drive.google.com/file/d/ABC123/view?usp=sharing"), want)
        self.assertEqual(normalize_url("https://drive.google.com/open?id=ABC123"), want)
        self.assertEqual(normalize_url("https://drive.google.com/uc?id=ABC123&export=download"), want)
        with self.assertRaises(FetchError):
            normalize_url("https://drive.google.com/drive/folders/XYZ")

    def test_dropbox_forces_download_and_keeps_other_params(self):
        out = normalize_url("https://www.dropbox.com/s/abc/video.mp4?dl=0&rlkey=KEY")
        self.assertIn("dl=1", out)
        self.assertIn("rlkey=KEY", out)
        self.assertNotIn("dl=0", out)

    def test_direct_link_drops_fragment_and_adds_scheme(self):
        self.assertEqual(normalize_url("example.com/a/b.mp4?x=1#frag"), "https://example.com/a/b.mp4?x=1")

    def test_sns_and_downloader_sites_are_refused(self):
        for url in ("https://www.tiktok.com/@a/video/1234567", "https://vm.tiktok.com/ZS1/", "https://www.instagram.com/reel/C1/",
                    "https://youtu.be/abc", "https://www.youtube.com/shorts/abc", "https://x.com/a/status/1",
                    "https://snaptik.app/ko3", "https://sub.tiktok.com/x"):
            with self.assertRaises(FetchError, msg=url) as ctx:
                normalize_url(url)
            self.assertIn("받지 않습니다", str(ctx.exception))

    def test_http_empty_and_garbage_refused(self):
        for url in ("http://example.com/a.mp4", "", "그냥글자"):
            with self.assertRaises(FetchError, msg=url):
                normalize_url(url)

    def test_safe_url_hides_query(self):
        self.assertEqual(safe_url("https://x.com/a/b.mp4?token=SECRET#f"), "https://x.com/a/b.mp4")


class PublicHostTests(unittest.TestCase):
    def test_public_ok_private_and_loopback_refused(self):
        assert_public("https://example.com/a.mp4", PUBLIC)
        for resolver in (PRIVATE, LOOPBACK):
            with self.assertRaises(FetchError):
                assert_public("https://example.com/a.mp4", resolver)

    def test_unresolvable_and_http_refused(self):
        def boom(host, port):
            raise OSError("no such host")

        with self.assertRaises(FetchError):
            assert_public("https://nope.invalid/a.mp4", boom)
        with self.assertRaises(FetchError):
            assert_public("http://example.com/a.mp4", PUBLIC)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dest = self.tmp / "001.mp4"

    def run_download(self, responses, max_bytes=10_000_000, resolver=PUBLIC):
        calls = []
        queue = list(responses)

        def getter(url, **kwargs):
            calls.append((url, kwargs))
            return queue.pop(0)

        return download("https://example.com/a.mp4", self.dest, max_bytes, getter=getter, resolver=resolver), calls

    def test_success_writes_file_without_leftovers(self):
        size, calls = self.run_download([fake_response(headers={"Content-Type": "video/mp4"}, chunks=(b"ab", b"cde"))])
        self.assertEqual(size, 5)
        self.assertEqual(self.dest.read_bytes(), b"abcde")
        self.assertFalse(self.dest.with_name("001.mp4.part").exists())
        self.assertFalse(calls[0][1]["allow_redirects"])

    def test_follows_redirect_and_checks_each_hop(self):
        redirect = fake_response(302, {"Location": "https://cdn.example.com/f.mp4"})
        size, calls = self.run_download([redirect, fake_response(chunks=(b"xyz",))])
        self.assertEqual(size, 3)
        self.assertEqual(calls[1][0], "https://cdn.example.com/f.mp4")

    def test_redirect_to_sns_or_private_or_http_is_refused(self):
        for target in ("https://www.tiktok.com/@a/video/1234567", "http://example.com/a.mp4"):
            with self.assertRaises(FetchError, msg=target):
                self.run_download([fake_response(302, {"Location": target})])
        flip = iter([PUBLIC, PRIVATE])
        with self.assertRaises(FetchError):
            self.run_download([fake_response(302, {"Location": "https://internal.example.com/a"})],
                              resolver=lambda h, p: next(flip)(h, p))
        self.assertFalse(self.dest.exists())

    def test_too_many_redirects(self):
        loop = [fake_response(302, {"Location": "https://example.com/a.mp4"}) for _ in range(10)]
        with self.assertRaises(FetchError) as ctx:
            self.run_download(loop)
        self.assertIn("너무 많이", str(ctx.exception))

    def test_html_response_explains_share_permission(self):
        with self.assertRaises(FetchError) as ctx:
            self.run_download([fake_response(headers={"Content-Type": "text/html; charset=utf-8"})])
        self.assertIn("웹 페이지", str(ctx.exception))
        self.assertFalse(self.dest.exists())

    def test_http_errors_have_hints(self):
        for status, word in ((403, "공유 권한"), (404, "만료"), (429, "잠시")):
            with self.assertRaises(FetchError, msg=status) as ctx:
                self.run_download([fake_response(status)])
            self.assertIn(word, str(ctx.exception))

    def test_size_cap_by_header_and_by_stream(self):
        with self.assertRaises(FetchError):
            self.run_download([fake_response(headers={"Content-Length": "999999999"})], max_bytes=1000)
        with self.assertRaises(FetchError):
            self.run_download([fake_response(chunks=(b"x" * 600, b"y" * 600))], max_bytes=1000)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_name("001.mp4.part").exists())

    def test_empty_body_refused(self):
        with self.assertRaises(FetchError):
            self.run_download([fake_response(chunks=())])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "output" / "20260101" / "001"
        self.out.mkdir(parents=True)
        self.script = json.loads((ROOT / "templates" / "sample_script.json").read_text(encoding="utf-8"))

    def write_script(self, **extra):
        data = {**self.script, **extra}
        (self.out / "script.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def run_main(self, *args):
        argv = ["fetch_source.py", "001", "--date", "20260101", "--workdir", str(self.tmp), *args]
        with mock.patch.object(sys, "argv", argv):
            return fetch_source.main()

    def test_refuses_without_permission_and_does_not_touch_network(self):
        self.script.pop("permission")
        self.write_script()
        with mock.patch("fetch_source.download") as dl:
            self.assertEqual(self.run_main("--url", "https://example.com/a.mp4"), 1)
        dl.assert_not_called()

    def test_refuses_sns_link_even_with_permission(self):
        self.write_script()
        with mock.patch("fetch_source.download") as dl:
            self.assertEqual(self.run_main("--url", "https://www.tiktok.com/@a/video/1234567"), 1)
        dl.assert_not_called()

    def test_download_records_provenance(self):
        self.write_script()

        def fake_download(url, dest, max_bytes, **kw):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=1",
                            "-pix_fmt", "yuv420p", str(dest)], check=True)
            return dest.stat().st_size

        with mock.patch("fetch_source.download", side_effect=fake_download):
            code = self.run_main("--url", "https://www.dropbox.com/s/abc/v.mp4?dl=0&rlkey=SECRET")
        self.assertEqual(code, 0)
        rec = json.loads((self.out / "script.json").read_text(encoding="utf-8"))["video_file"]
        self.assertEqual(rec["path"], "input/videos/001.mp4")
        self.assertNotIn("SECRET", json.dumps(rec))
        self.assertEqual(rec["source"], "https://www.dropbox.com/s/abc/v.mp4")
        self.assertEqual(len(rec["sha256"]), 64)
        # 두 번째 실행은 건너뛴다
        with mock.patch("fetch_source.download") as dl:
            self.assertEqual(self.run_main("--url", "https://example.com/a.mp4"), 0)
        dl.assert_not_called()

    def test_non_video_download_is_removed(self):
        self.write_script()

        def fake_download(url, dest, max_bytes, **kw):
            dest.write_bytes(b"not a video at all")
            return 18

        with mock.patch("fetch_source.download", side_effect=fake_download):
            self.assertEqual(self.run_main("--url", "https://example.com/a.mp4"), 1)
        self.assertFalse((self.tmp / "input" / "videos" / "001.mp4").exists())
        self.assertNotIn("video_file", json.loads((self.out / "script.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
