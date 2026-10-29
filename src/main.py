# -*- coding: utf-8 -*-
"""MYVD for Windows - entry point."""
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402


def log_error(text: str) -> None:
    try:
        (core.data_dir() / "error.log").open("a", encoding="utf-8").write(
            time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + text + "\n\n")
    except Exception:
        pass


def selftest(app, ui) -> int:
    """Used by the CI build: construct every screen and check bundled tools."""
    out = core.base_dir() / "selftest.txt"
    lines = []
    ok = True
    try:
        win = ui.MainWindow()
        win.show()
        app.processEvents()

        single = core.parse_video("http://x", {"title": "T", "duration": 61, "formats": [
            {"vcodec": "avc1", "height": 720, "filesize": 1000000},
            {"vcodec": "none", "acodec": "mp4a", "filesize": 100000}]})
        play = core.parse_playlist({"title": "P", "entries": [{"id": "a", "title": "One"}, {"id": "b", "title": "Two"}]})
        for a in (single, play):
            d = ui.AnalysisDialog(a, win.thumbs, win)
            assert d.quality() is not None and len(d.selected_entries()) == len(a.entries)
            d.close()
        task = core.Task(id="t1", url="http://x", title="Test", thumb=None, duration=1, q_label="720p",
                         height=720, audio=None, prefix="Test [t1]")
        for st in (core.QUEUED, core.DOWNLOADING, core.PAUSED, core.DONE, core.ERROR):
            task.status = st
            card = ui.TaskCard(task, win)
            card.refresh(task)
            card.deleteLater()
        assert not ui.make_qr_pixmap(core.ANDROID_URL).isNull()
        for dlg in (ui.AndroidDialog(win), ui.AboutDialog(win), ui.SettingsDialog(win.settings, win)):
            dlg.show()
            app.processEvents()
            dlg.close()
        lines.append("UI constructed OK")

        yt = core.ytdlp_cmd()
        ff = core.ffmpeg_dir()
        mpv = core.mpv_path()
        lines.append(f"yt-dlp: {yt}")
        lines.append(f"ffmpeg dir: {ff}")
        lines.append(f"mpv: {mpv}")
        if getattr(sys, "frozen", False):
            if not yt or not ff:
                ok = False
                lines.append("MISSING required tool (yt-dlp or ffmpeg)")
            else:
                ver = core.ytdlp_version()
                lines.append(f"yt-dlp version: {ver}")
                if ver in ("غير موجود", "غير معروف"):
                    ok = False
        if mpv:
            try:
                r = subprocess.run([mpv, "--version"], capture_output=True, timeout=30, creationflags=core.NO_WINDOW)
                first = (r.stdout.decode("utf-8", "replace").splitlines() or [""])[0]
                lines.append(f"mpv --version exit code {r.returncode & 0xFFFFFFFF:#x}: {first}")
            except Exception as e:
                lines.append(f"mpv check error: {e}")
        win.close()
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("SELFTEST " + ("OK" if ok else "FAILED"))
    try:
        out.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass
    return 0 if ok else 1


def main() -> int:
    core.suppress_error_dialogs()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    import ui

    app = QApplication(sys.argv)
    app.setApplicationName(core.APP_NAME)
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(ui.QSS)

    if "--selftest" in sys.argv:
        return selftest(app, ui)

    def hook(et, ev, tb):
        text = "".join(traceback.format_exception(et, ev, tb))
        log_error(text)
        try:
            QMessageBox.critical(None, "MYVD", "حصل خطأ غير متوقع:\n" + str(ev))
        except Exception:
            pass

    sys.excepthook = hook
    win = ui.MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
