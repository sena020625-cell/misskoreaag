"""사용 허락 기록과 차단 시험. tts.py·render.py 차단은 실제 스크립트를 실행해 확인한다(mock 음성, ffmpeg 필요)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import parse_permission, permission_status  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_granted_values(self):
        for raw in ("Y", "y", "Y 2026-10-20 DM 승인", "허락함", "예: 2026-10-20 이메일", "OK 서면 동의"):
            p = parse_permission(raw)
            self.assertTrue(p["granted"], raw)
            self.assertEqual(p["note"], raw.strip())

    def test_not_granted_values(self):
        for raw in ("", "   ", None, "N", "no", "No reply", "아니오", "미확인", "미확인(요청 중)", "대기", "확인중 DM 보냄",
                    "확인 중", "X 거절", "-", "보류", "불가", "0", "false"):
            self.assertFalse(parse_permission(raw)["granted"], repr(raw))

    def test_status_requires_record_flag_and_note(self):
        self.assertFalse(permission_status({})[0])
        self.assertFalse(permission_status({"permission": "Y"})[0])
        self.assertFalse(permission_status({"permission": {"granted": False, "note": "N"}})[0])
        self.assertFalse(permission_status({"permission": {"granted": "yes", "note": "x"}})[0])
        self.assertIn("근거", permission_status({"permission": {"granted": True, "note": " "}})[1])
        self.assertEqual(permission_status({"permission": {"granted": True, "note": "Y 날짜"}}), (True, ""))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "output" / "20260101" / "001"
        self.out.mkdir(parents=True)
        script = json.loads((ROOT / "templates" / "sample_script.json").read_text(encoding="utf-8"))
        script.pop("permission", None)
        script["approved"] = True
        (self.out / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")

    def run_script(self, name, *args):
        proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args, "--date", "20260101", "--workdir", str(self.tmp)],
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout + proc.stderr

    def test_tts_is_blocked_until_permission_is_recorded(self):
        code, out = self.run_script("tts.py", "001", "--provider", "mock")
        self.assertEqual(code, 1)
        self.assertIn("permission", out)
        self.assertIn("permission.py set", out)
        self.assertFalse((self.out / "voice.mp3").exists())

        code, out = self.run_script("permission.py", "set", "001", "--value", "Y 2026-10-20 DM 승인")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads((self.out / "script.json").read_text(encoding="utf-8"))["permission"],
                         {"granted": True, "note": "Y 2026-10-20 DM 승인"})

        code, out = self.run_script("tts.py", "001", "--provider", "mock")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.out / "voice.mp3").exists())

    def test_negative_value_keeps_it_blocked(self):
        self.run_script("permission.py", "set", "001", "--value", "미확인")
        code, out = self.run_script("permission.py", "check", "001")
        self.assertEqual(code, 1)
        self.assertIn("미확인", out)
        code, out = self.run_script("tts.py", "001", "--provider", "mock")
        self.assertEqual(code, 1)

    def test_skip_flag_is_available_for_tests_only(self):
        code, out = self.run_script("tts.py", "001", "--provider", "mock", "--skip-permission-check")
        self.assertEqual(code, 0, out)

    def test_render_is_blocked_without_permission_but_preview_is_not(self):
        self.run_script("tts.py", "001", "--provider", "mock", "--skip-permission-check")
        self.run_script("subtitle.py", "001")
        videos = self.tmp / "input" / "videos"
        videos.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=2",
                        "-pix_fmt", "yuv420p", str(videos / "001.mp4")], check=True)
        code, out = self.run_script("render.py", "001")
        self.assertEqual(code, 1)
        self.assertIn("permission", out)
        self.assertFalse((self.out / "final.mp4").exists())
        code, out = self.run_script("render.py", "001", "--preview", "1")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.out / "preview.png").exists())


if __name__ == "__main__":
    unittest.main()
