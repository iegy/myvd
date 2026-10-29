# -*- coding: utf-8 -*-
"""MYVD core logic (no Qt imports): yt-dlp wrapper, download queue, settings, helpers."""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Callable, List, Optional

APP_NAME = "MYVD"
APP_VERSION = "1.0.0"
CREDIT = "iegy.net | Mohammed Hussein"
SITE_URL = "https://iegy.net"
ANDROID_URL = "https://github.com/iegy/YTD/releases/download/latest/MYVD.apk"
WINDOWS_URL = "https://github.com/iegy/myvd/releases/download/latest/MYVD-Windows-Portable.zip"

MISSING_YTDLP = "ملف yt-dlp.exe غير موجود داخل مجلد bin بجانب البرنامج"

QUEUED, DOWNLOADING, PAUSED, DONE, ERROR = "QUEUED", "DOWNLOADING", "PAUSED", "DONE", "ERROR"

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ---------------------------------------------------------------- paths

def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        return Path(mp) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def bin_dir() -> Path:
    return base_dir() / "bin"


def find_tool(name: str) -> Optional[str]:
    p = bin_dir() / name
    if p.exists():
        return str(p)
    return shutil.which(name)


def ytdlp_cmd() -> Optional[List[str]]:
    env = os.environ.get("MYVD_YTDLP_CMD")  # used by tests
    if env:
        try:
            return [str(x) for x in json.loads(env)]
        except Exception:
            pass
    p = find_tool("yt-dlp.exe") or find_tool("yt-dlp")
    return [p] if p else None


def ffmpeg_dir() -> Optional[str]:
    p = find_tool("ffmpeg.exe") or find_tool("ffmpeg")
    return str(Path(p).parent) if p else None


def mpv_path() -> Optional[str]:
    p = bin_dir() / "mpv" / "mpv.exe"
    if p.exists():
        return str(p)
    return shutil.which("mpv") or shutil.which("mpv.exe")


def data_dir() -> Path:
    d = base_dir() / "data"
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".w"
        t.write_text("1")
        t.unlink()
        return d
    except Exception:
        root = os.environ.get("APPDATA") or str(Path.home())
        d = Path(root) / APP_NAME
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------------------------------------------------------------- helpers

def fmt_dur(s: float) -> str:
    s = int(s or 0)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_bytes(b: float) -> str:
    b = float(b or 0)
    if b <= 0:
        return ""
    mb = b / 1048576.0
    return f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def fmt_speed(bps: float) -> str:
    if not bps or bps <= 0:
        return ""
    if bps >= 1048576:
        return f"{bps / 1048576:.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


def num(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None  # drop NaN
    except Exception:
        return None


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str, limit: int = 120) -> str:
    s = _BAD.sub("_", name or "video")
    s = re.sub(r"\s+", " ", s).strip()
    s = s[:limit].rstrip(". ")
    return s or "video"


def clean_error(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    pick = next((l for l in lines if "ERROR" in l), lines[-1] if lines else "فشل غير معروف")
    pick = re.sub(r"^ERROR:\s*", "", pick)
    if "sign in" in pick.lower():
        pick += " (جرّب: القائمة ← الإعدادات ← تحديث yt-dlp)"
    return pick[:250]


def extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://\S+", text or "")
    return m.group(0) if m else None


# ---------------------------------------------------------------- models

@dataclass
class Quality:
    label: str
    short: str
    height: int
    audio: Optional[str]


@dataclass
class Entry:
    url: str
    title: str
    thumb: Optional[str]
    duration: int


@dataclass
class Analysis:
    title: str
    uploader: Optional[str]
    thumb: Optional[str]
    duration: int
    is_playlist: bool
    entries: List[Entry]
    qualities: List[Quality]


def _size(f: dict) -> int:
    return int(max(f.get("filesize") or 0, f.get("filesize_approx") or 0))


def parse_video(url: str, j: dict) -> Analysis:
    v_size: dict = {}
    a_size = 0
    for f in j.get("formats") or []:
        h = int(f.get("height") or 0)
        vc = f.get("vcodec") or "none"
        sz = _size(f)
        if vc != "none" and h > 0:
            v_size[h] = max(v_size.get(h, 0), sz)
        elif vc == "none":
            a_size = max(a_size, sz)
    qs = [Quality("أفضل جودة", "أفضل جودة", 0, None)]
    for h in sorted(v_size, reverse=True):
        total = v_size[h] + a_size
        txt = f" • ~{fmt_bytes(total)}" if total > 0 else ""
        qs.append(Quality(f"{h}p{txt}", f"{h}p", h, None))
    a_txt = f" • ~{fmt_bytes(a_size)}" if a_size > 0 else ""
    qs.append(Quality(f"MP3 صوت{a_txt}", "MP3", 0, "mp3"))
    qs.append(Quality(f"M4A صوت{a_txt}", "M4A", 0, "m4a"))
    page = j.get("webpage_url") or url
    title = j.get("title") or page
    thumb = j.get("thumbnail")
    dur = int(j.get("duration") or 0)
    return Analysis(title, j.get("uploader") or j.get("channel"), thumb, dur, False,
                    [Entry(page, title, thumb, dur)], qs)


def parse_playlist(j: dict) -> Analysis:
    entries: List[Entry] = []
    for i, e in enumerate(j.get("entries") or []):
        if not isinstance(e, dict):
            continue
        vid = e.get("id")
        u = e.get("url") or e.get("webpage_url")
        if (not u or not str(u).startswith("http")) and vid:
            u = f"https://www.youtube.com/watch?v={vid}"
        if not u:
            continue
        th = None
        ths = e.get("thumbnails") or []
        if ths and isinstance(ths[-1], dict):
            th = ths[-1].get("url")
        if not th and vid and "youtube" in str(u):
            th = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
        entries.append(Entry(u, e.get("title") or f"فيديو {i + 1}", th, int(e.get("duration") or 0)))
    qs = [
        Quality("أفضل جودة", "أفضل جودة", 0, None),
        Quality("1080p", "1080p", 1080, None),
        Quality("720p", "720p", 720, None),
        Quality("480p", "480p", 480, None),
        Quality("360p", "360p", 360, None),
        Quality("MP3 صوت", "MP3", 0, "mp3"),
        Quality("M4A صوت", "M4A", 0, "m4a"),
    ]
    return Analysis(j.get("title") or "قائمة تشغيل", j.get("uploader") or j.get("channel"),
                    entries[0].thumb if entries else None, 0, True, entries, qs)


def parse_analysis(url: str, j: dict) -> Analysis:
    if j.get("_type") == "playlist":
        return parse_playlist(j)
    return parse_video(url, j)


def analyze(url: str) -> Analysis:
    cmd = ytdlp_cmd()
    if not cmd:
        raise RuntimeError(MISSING_YTDLP)
    full = cmd + ["-J", "--flat-playlist", "--no-warnings", "--encoding", "utf-8", url]
    p = subprocess.run(full, capture_output=True, creationflags=NO_WINDOW, timeout=240)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0 or not out.strip():
        raise RuntimeError(clean_error(p.stderr.decode("utf-8", "replace")))
    return parse_analysis(url, json.loads(out))


def ytdlp_version() -> str:
    cmd = ytdlp_cmd()
    if not cmd:
        return "غير موجود"
    try:
        p = subprocess.run(cmd + ["--version"], capture_output=True, creationflags=NO_WINDOW, timeout=30)
        return p.stdout.decode("utf-8", "replace").strip() or "غير معروف"
    except Exception:
        return "غير معروف"


def update_ytdlp() -> str:
    cmd = ytdlp_cmd()
    if not cmd:
        return MISSING_YTDLP
    try:
        p = subprocess.run(cmd + ["-U"], capture_output=True, creationflags=NO_WINDOW, timeout=180)
        out = (p.stdout + p.stderr).decode("utf-8", "replace").strip().splitlines()
        return out[-1] if out else "تم"
    except Exception as e:  # pragma: no cover
        return f"فشل التحديث: {e}"


def preview(url: str, height: int = 0, audio_only: bool = False) -> None:
    """Play a link in mpv (through yt-dlp) with no ads. Raises RuntimeError if unavailable."""
    mpv = mpv_path()
    if not mpv:
        raise RuntimeError("مشغّل المعاينة (mpv) غير موجود داخل مجلد bin\\mpv")
    h = height if height > 0 else 720
    fmt = "ba/b" if audio_only else f"bv*[height<={h}]+ba/b[height<={h}]/b"
    args = [mpv, "--ytdl=yes", f"--ytdl-format={fmt}", "--autofit=70%x70%", "--keep-open=yes", url]
    env = os.environ.copy()
    env["PATH"] = str(bin_dir()) + os.pathsep + env.get("PATH", "")
    subprocess.Popen(args, env=env, creationflags=NO_WINDOW)


# ---------------------------------------------------------------- settings

class Settings:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else data_dir() / "settings.json"
        self.download_dir = str(Path.home() / "Downloads" / "MYVD")
        self.parallel = 2
        self.load()

    def load(self) -> None:
        try:
            j = json.loads(self.path.read_text(encoding="utf-8"))
            self.download_dir = j.get("download_dir") or self.download_dir
            self.parallel = max(1, min(3, int(j.get("parallel", self.parallel))))
        except Exception:
            pass

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(
                {"download_dir": self.download_dir, "parallel": self.parallel}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------- tasks / engine

@dataclass
class Task:
    id: str
    url: str
    title: str
    thumb: Optional[str]
    duration: int
    q_label: str
    height: int
    audio: Optional[str]
    prefix: str = ""
    status: str = QUEUED
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    error: Optional[str] = None
    file_path: Optional[str] = None
    note: str = ""
    created: float = field(default_factory=time.time)


def task_from_dict(d: dict) -> Task:
    names = {f.name for f in fields(Task)}
    return Task(**{k: v for k, v in d.items() if k in names})


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=NO_WINDOW)
        else:
            proc.terminate()
    except Exception:
        pass


PROGRESS_TEMPLATE = ("download:MYVDP|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                     "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s")


class Engine:
    def __init__(self, settings: Settings, notify: Callable[[str], None], data: Optional[Path] = None):
        self.settings = settings
        self.notify = notify
        self.lock = threading.RLock()
        self.procs: dict = {}
        self.stops: dict = {}
        self._last_emit: dict = {}
        self.file = (Path(data) if data else data_dir()) / "tasks.json"
        self.tasks: List[Task] = self._load()

    # ---- persistence
    def _load(self) -> List[Task]:
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            out = [task_from_dict(d) for d in raw]
        except Exception:
            return []
        for t in out:
            if t.status in (DOWNLOADING, QUEUED):
                t.status, t.speed, t.eta, t.note = PAUSED, "", "", ""
        return out

    def _save(self) -> None:
        with self.lock:
            data = [asdict(t) for t in self.tasks]
        try:
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.file)
        except Exception:
            pass

    def snapshot(self) -> List[Task]:
        with self.lock:
            return list(self.tasks)

    def get(self, tid: str) -> Optional[Task]:
        with self.lock:
            return next((t for t in self.tasks if t.id == tid), None)

    def _update(self, tid: str, save: bool = True, **kw) -> None:
        with self.lock:
            t = self.get(tid)
            if not t:
                return
            for k, v in kw.items():
                setattr(t, k, v)
        if save:
            self._save()
        self.notify(tid)

    # ---- queue control
    def add_all(self, entries: List[Entry], q: Quality) -> None:
        if not entries:
            return
        new = []
        for e in entries:
            tid = uuid.uuid4().hex
            new.append(Task(id=tid, url=e.url, title=e.title, thumb=e.thumb, duration=e.duration,
                            q_label=q.short, height=q.height, audio=q.audio,
                            prefix=f"{sanitize(e.title)} [{tid[:6]}]"))
        with self.lock:
            self.tasks = list(reversed(new)) + self.tasks
        self._save()
        self.notify("*")
        self.schedule()

    def schedule(self) -> None:
        start = []
        with self.lock:
            running = sum(1 for t in self.tasks if t.status == DOWNLOADING)
            for t in reversed(self.tasks):  # oldest first
                if running >= self.settings.parallel:
                    break
                if t.status == QUEUED:
                    t.status, t.note, t.error = DOWNLOADING, "", None
                    running += 1
                    start.append(t.id)
        for tid in start:
            self.notify(tid)
            threading.Thread(target=self._run, args=(tid,), daemon=True).start()

    def pause(self, tid: str) -> None:
        proc = None
        with self.lock:
            t = self.get(tid)
            if not t:
                return
            if t.status == QUEUED:
                t.status = PAUSED
            elif t.status == DOWNLOADING:
                self.stops[tid] = "pause"
                proc = self.procs.get(tid)
            else:
                return
        if proc:
            kill_tree(proc)
        self._save()
        self.notify(tid)

    def resume(self, tid: str) -> None:
        with self.lock:
            t = self.get(tid)
            if not t or t.status not in (PAUSED, ERROR):
                return
            t.status, t.error, t.note = QUEUED, None, ""
        self._save()
        self.notify(tid)
        self.schedule()

    def pause_all(self) -> None:
        for t in self.snapshot():
            self.pause(t.id)

    def resume_all(self) -> None:
        for t in self.snapshot():
            self.resume(t.id)

    def cancel(self, tid: str) -> None:
        proc = None
        with self.lock:
            t = self.get(tid)
            if not t:
                return
            if t.status == DOWNLOADING:
                self.stops[tid] = "cancel"
                proc = self.procs.get(tid)
            self.tasks = [x for x in self.tasks if x.id != tid]
        if proc:
            kill_tree(proc)
        else:
            self._cleanup(t)
        self._save()
        self.notify("*")
        self.schedule()

    def remove(self, tid: str, delete_file: bool) -> None:
        with self.lock:
            t = self.get(tid)
            if not t:
                return
            self.tasks = [x for x in self.tasks if x.id != tid]
        if delete_file and t.file_path:
            try:
                os.remove(t.file_path)
            except Exception:
                pass
        self._save()
        self.notify("*")

    def clear_done(self) -> None:
        with self.lock:
            self.tasks = [t for t in self.tasks if t.status != DONE]
        self._save()
        self.notify("*")

    # ---- worker
    def _cleanup(self, t: Task) -> None:
        try:
            for p in Path(self.settings.download_dir).glob(glob.escape(t.prefix) + ".*"):
                try:
                    p.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def build_cmd(self, t: Task) -> Optional[List[str]]:
        base = ytdlp_cmd()
        if not base:
            return None
        d = Path(self.settings.download_dir)
        d.mkdir(parents=True, exist_ok=True)
        out = str(d / (t.prefix.replace("%", "%%") + ".%(ext)s"))
        cmd = base + ["--no-warnings", "--no-playlist", "--newline", "--encoding", "utf-8",
                      "--windows-filenames", "-N", "4", "--progress-template", PROGRESS_TEMPLATE, "-o", out]
        ff = ffmpeg_dir()
        if ff:
            cmd += ["--ffmpeg-location", ff]
        if t.audio:
            cmd += ["-f", "bestaudio/best", "-x", "--audio-format", t.audio, "--audio-quality", "0"]
        elif t.height > 0:
            h = t.height
            cmd += ["-f", f"bv*[height<={h}]+ba/b[height<={h}]/b", "-S", "res,vcodec:h264,acodec:m4a",
                    "--merge-output-format", "mp4"]
        else:
            cmd += ["-f", "bv*+ba/b", "-S", "res,vcodec:h264,acodec:m4a", "--merge-output-format", "mp4"]
        cmd.append(t.url)
        return cmd

    def find_file(self, t: Task) -> Optional[Path]:
        cands = []
        for p in Path(self.settings.download_dir).glob(glob.escape(t.prefix) + ".*"):
            if p.stem != t.prefix or p.suffix.lower() in (".part", ".ytdl", ".temp", ".tmp"):
                continue
            cands.append(p)
        return max(cands, key=lambda p: p.stat().st_mtime) if cands else None

    def _progress(self, tid: str, line: str) -> None:
        parts = line.split("|")
        if len(parts) < 6:
            return
        done, tot, est, spd, eta = (num(x) for x in parts[1:6])
        total = tot or est
        frac = min(1.0, (done or 0) / total) if total else 0.0
        now = time.time()
        if now - self._last_emit.get(tid, 0) < 0.25 and frac < 1.0:
            return
        self._last_emit[tid] = now
        self._update(tid, save=False, progress=frac, speed=fmt_speed(spd or 0),
                     eta=fmt_dur(eta) if eta else "", note="")

    def _run(self, tid: str) -> None:
        t = self.get(tid)
        if not t:
            return
        cmd = self.build_cmd(t)
        if not cmd:
            self._update(tid, status=ERROR, error=MISSING_YTDLP)
            self.schedule()
            return
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW)
        except Exception as e:
            self._update(tid, status=ERROR, error=clean_error(str(e)))
            self.schedule()
            return
        with self.lock:
            self.procs[tid] = proc
            early_stop = tid in self.stops
        if early_stop:
            kill_tree(proc)
        last_err = ""
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if line.startswith("MYVDP|"):
                    self._progress(tid, line)
                elif line.startswith(("[Merger]", "[ExtractAudio]", "[VideoConvertor]", "[Fixup")):
                    self._update(tid, save=False, speed="", eta="", note="processing", progress=1.0)
                elif line.startswith("ERROR"):
                    last_err = line
        finally:
            rc = proc.wait()
        with self.lock:
            self.procs.pop(tid, None)
            reason = self.stops.pop(tid, None)
        if reason == "cancel":
            self._cleanup(t)
        elif reason == "pause":
            self._update(tid, status=PAUSED, speed="", eta="", note="")
        elif rc == 0:
            f = self.find_file(t)
            if f:
                self._update(tid, status=DONE, progress=1.0, speed="", eta="", note="",
                             file_path=str(f), size=fmt_bytes(f.stat().st_size))
            else:
                self._update(tid, status=ERROR, error="انتهى التحميل لكن الملف غير موجود", note="")
        else:
            self._update(tid, status=ERROR, error=clean_error(last_err), speed="", eta="", note="")
        self.schedule()
