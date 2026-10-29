import json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import core

FAKE = str(Path(__file__).resolve().parent / "fake_ytdlp.py")


def wait(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class Helpers(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(core.sanitize('a<b>:c"/d\\e|f?g*'), "a_b__c__d_e_f_g_")
        self.assertEqual(core.sanitize("  "), "video")
        self.assertEqual(core.sanitize("end. "), "end")
        self.assertEqual(len(core.sanitize("x" * 500)), 120)

    def test_fmt(self):
        self.assertEqual(core.fmt_dur(65), "1:05")
        self.assertEqual(core.fmt_dur(3725), "1:02:05")
        self.assertEqual(core.fmt_bytes(0), "")
        self.assertEqual(core.fmt_bytes(5 * 1048576), "5 MB")
        self.assertEqual(core.fmt_speed(2 * 1048576), "2.0 MB/s")
        self.assertIsNone(core.num("NA"))
        self.assertIsNone(core.num("nan"))
        self.assertEqual(core.num("12"), 12.0)

    def test_url_and_error(self):
        self.assertEqual(core.extract_url("شوف ده https://vm.tiktok.com/abc/ جامد"), "https://vm.tiktok.com/abc/")
        self.assertIsNone(core.extract_url("no link"))
        self.assertEqual(core.clean_error("x\nERROR: [youtube] a: Video unavailable\n"), "[youtube] a: Video unavailable")


class Parsing(unittest.TestCase):
    def test_video(self):
        j = json.loads(subprocess.run([sys.executable, FAKE, "-J", "http://x"], capture_output=True, text=True).stdout)
        a = core.parse_analysis("http://x", j)
        self.assertFalse(a.is_playlist)
        self.assertEqual([q.short for q in a.qualities], ["أفضل جودة", "1080p", "720p", "MP3", "M4A"])
        self.assertIn("~", a.qualities[1].label)
        self.assertEqual(a.entries[0].url, "http://x")

    def test_playlist(self):
        j = json.loads(subprocess.run([sys.executable, FAKE, "-J", "http://playlist"], capture_output=True, text=True).stdout)
        a = core.parse_analysis("http://playlist", j)
        self.assertTrue(a.is_playlist)
        self.assertEqual(len(a.entries), 2)
        self.assertEqual(a.entries[1].url, "https://www.youtube.com/watch?v=bbb")
        self.assertIn("ytimg", a.entries[1].thumb)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["MYVD_YTDLP_CMD"] = json.dumps([sys.executable, FAKE])
        os.environ["FAKE_DELAY"] = "0.02"
        s = core.Settings(self.tmp / "s.json")
        s.download_dir = str(self.tmp / "dl")
        s.parallel = 2
        self.events = []
        self.eng = core.Engine(s, self.events.append, data=self.tmp)

    def entry(self, url="http://x", title="Vid: 1/2"):
        return core.Entry(url, title, None, 65)

    def test_analyze(self):
        a = core.analyze("http://x")
        self.assertEqual(a.title, "Vid")
        with self.assertRaises(RuntimeError) as cm:
            core.analyze("http://fail")
        self.assertIn("unavailable", str(cm.exception))

    def test_download_ok(self):
        self.eng.add_all([self.entry()], core.Quality("720p", "720p", 720, None))
        tid = self.eng.snapshot()[0].id
        self.assertTrue(wait(lambda: self.eng.get(tid).status == core.DONE))
        t = self.eng.get(tid)
        self.assertTrue(Path(t.file_path).exists())
        self.assertTrue(t.file_path.endswith(".mp4"))
        self.assertNotIn(":", Path(t.file_path).name)
        self.assertEqual(t.progress, 1.0)
        # persisted
        saved = json.loads((self.tmp / "tasks.json").read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["status"], core.DONE)

    def test_audio(self):
        self.eng.add_all([self.entry()], core.Quality("MP3", "MP3", 0, "mp3"))
        tid = self.eng.snapshot()[0].id
        self.assertTrue(wait(lambda: self.eng.get(tid).status == core.DONE))
        self.assertTrue(self.eng.get(tid).file_path.endswith(".mp3"))

    def test_error(self):
        self.eng.add_all([self.entry("http://fail")], core.Quality("best", "best", 0, None))
        tid = self.eng.snapshot()[0].id
        self.assertTrue(wait(lambda: self.eng.get(tid).status == core.ERROR))
        self.assertIn("unavailable", self.eng.get(tid).error)

    def test_pause_resume(self):
        os.environ["FAKE_DELAY"] = "0.3"
        self.eng.add_all([self.entry()], core.Quality("best", "best", 0, None))
        tid = self.eng.snapshot()[0].id
        self.assertTrue(wait(lambda: self.eng.get(tid).progress > 0))
        self.eng.pause(tid)
        self.assertTrue(wait(lambda: self.eng.get(tid).status == core.PAUSED))
        os.environ["FAKE_DELAY"] = "0.01"
        self.eng.resume(tid)
        self.assertTrue(wait(lambda: self.eng.get(tid).status == core.DONE))

    def test_cancel_and_remove(self):
        os.environ["FAKE_DELAY"] = "0.3"
        self.eng.add_all([self.entry()], core.Quality("best", "best", 0, None))
        tid = self.eng.snapshot()[0].id
        self.assertTrue(wait(lambda: self.eng.get(tid).progress > 0))
        self.eng.cancel(tid)
        self.assertTrue(wait(lambda: not self.eng.snapshot()))
        time.sleep(0.5)
        self.assertEqual(list((self.tmp / "dl").glob("*.mp4")), [])
        os.environ["FAKE_DELAY"] = "0.01"
        self.eng.add_all([self.entry()], core.Quality("best", "best", 0, None))
        tid = self.eng.snapshot()[0].id
        self.assertTrue(wait(lambda: self.eng.get(tid).status == core.DONE))
        path = self.eng.get(tid).file_path
        self.eng.remove(tid, True)
        self.assertFalse(Path(path).exists())

    def test_parallel_limit(self):
        os.environ["FAKE_DELAY"] = "0.2"
        self.eng.add_all([self.entry(f"http://x{i}", f"V{i}") for i in range(4)], core.Quality("b", "b", 0, None))
        time.sleep(0.5)
        running = sum(1 for t in self.eng.snapshot() if t.status == core.DOWNLOADING)
        self.assertEqual(running, 2)
        self.assertTrue(wait(lambda: all(t.status == core.DONE for t in self.eng.snapshot()), 40))

    def test_restart_marks_paused(self):
        os.environ["FAKE_DELAY"] = "0.3"
        self.eng.add_all([self.entry()], core.Quality("b", "b", 0, None))
        self.assertTrue(wait(lambda: self.eng.snapshot()[0].progress > 0))
        eng2 = core.Engine(self.eng.settings, lambda x: None, data=self.tmp)
        self.assertEqual(eng2.snapshot()[0].status, core.PAUSED)
        self.eng.cancel(self.eng.snapshot()[0].id)


if __name__ == "__main__":
    unittest.main()
