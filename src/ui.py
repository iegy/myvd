# -*- coding: utf-8 -*-
"""MYVD Windows UI (PySide6)."""
from __future__ import annotations

import os
import subprocess
import threading
import urllib.request
from typing import Optional

from PySide6.QtCore import Qt, QObject, Signal, QUrl
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QTabWidget, QScrollArea, QProgressBar, QDialog, QComboBox, QListWidget, QListWidgetItem,
    QMessageBox, QFileDialog, QSpinBox, QToolButton, QMenu,
)

import core

QSS = """
QWidget { font-family: "Segoe UI", "Tahoma"; font-size: 10pt; color: #2B2822; }
QMainWindow, QDialog, QWidget#root, QWidget#inner { background: #F8EEE2; }
QFrame#card { background: #FFFBF5; border-radius: 14px; }
QLineEdit { background: white; border: 1px solid #CDBFA9; border-radius: 10px; padding: 9px 12px; }
QLineEdit:focus { border: 1px solid #D86F12; }
QComboBox, QSpinBox { background: white; border: 1px solid #CDBFA9; border-radius: 8px; padding: 6px 10px; }
QPushButton { background: #EFE2CF; border: none; border-radius: 10px; padding: 8px 14px; }
QPushButton:hover { background: #E6D5BC; }
QPushButton:disabled { color: #A89E8C; background: #F1E8DA; }
QPushButton#primary { background: #D86F12; color: white; font-weight: bold; }
QPushButton#primary:hover { background: #BF620F; }
QPushButton#primary:disabled { background: #E9B98A; color: white; }
QPushButton#danger { color: #C8402F; }
QPushButton#link { background: transparent; color: #857A69; padding: 2px 8px; }
QPushButton#link:hover { color: #D86F12; }
QProgressBar { background: #EFE2CF; border: none; border-radius: 4px; }
QProgressBar::chunk { background: #D86F12; border-radius: 4px; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 9px 20px; background: transparent; color: #857A69; font-weight: bold; }
QTabBar::tab:selected { color: #D86F12; border-bottom: 3px solid #D86F12; }
QListWidget { background: white; border: 1px solid #E3D6C0; border-radius: 10px; }
QScrollArea { background: transparent; border: none; }
QToolButton { background: #EFE2CF; border: none; border-radius: 10px; padding: 8px 12px; font-weight: bold; }
QToolButton::menu-indicator { image: none; }
QStatusBar { background: transparent; }
"""


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def logo_pixmap(name: str = "robot_default.png", h: int = 64) -> QPixmap:
    pm = QPixmap(str(core.assets_dir() / name))
    return pm.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation) if not pm.isNull() else pm


def make_qr_pixmap(text: str, scale: int = 7, border: int = 3) -> QPixmap:
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(text)
    qr.make(fit=True)
    m = qr.get_matrix()
    size = (len(m) + 2 * border) * scale
    pm = QPixmap(size, size)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2B2822"))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect((x + border) * scale, (y + border) * scale, scale, scale)
    p.end()
    return pm


class Bridge(QObject):
    task_changed = Signal(str)
    analysis_done = Signal(object)
    analysis_failed = Signal(str)


class ThumbLoader(QObject):
    loaded = Signal(str, object)
    _fetched = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.cache = {}
        self.pending = set()
        self._fetched.connect(self._on_fetched)

    def request(self, url: Optional[str]) -> None:
        if not url:
            return
        if url in self.cache:
            self.loaded.emit(url, self.cache[url])
            return
        if url in self.pending:
            return
        self.pending.add(url)
        threading.Thread(target=self._work, args=(url,), daemon=True).start()

    def _work(self, url: str) -> None:
        data = b""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=12).read()
        except Exception:
            pass
        self._fetched.emit(url, data)

    def _on_fetched(self, url: str, data) -> None:
        self.pending.discard(url)
        if not data:
            return
        img = QImage()
        if img.loadFromData(data):
            pm = QPixmap.fromImage(img)
            self.cache[url] = pm
            self.loaded.emit(url, pm)


def fit_thumb(pm: QPixmap, w: int, h: int) -> QPixmap:
    return pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


# ------------------------------------------------------------------ task card

class TaskCard(QFrame):
    def __init__(self, t: core.Task, win: "MainWindow"):
        super().__init__()
        self.setObjectName("card")
        self.win = win
        self.tid = t.id
        self.is_done = t.status == core.DONE
        self.thumb_url = t.thumb

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.thumb = QLabel()
        self.thumb.setFixedSize(120, 68)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background:#2B2822; border-radius:8px;")
        top.addWidget(self.thumb)
        info = QVBoxLayout()
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight:bold;")
        info.addWidget(self.title)
        row = QHBoxLayout()
        self.badge = QLabel()
        self.badge.setStyleSheet("background:#EFE2CF; border-radius:6px; padding:2px 8px; color:#5E6B52; font-weight:bold;")
        self.status = QLabel()
        self.status.setStyleSheet("color:#857A69;")
        row.addWidget(self.badge)
        row.addWidget(self.status, 1)
        info.addLayout(row)
        top.addLayout(info, 1)
        lay.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.b_pause = self._btn("إيقاف مؤقت", lambda: win.engine.pause(self.tid))
        self.b_resume = self._btn("استئناف", lambda: win.engine.resume(self.tid))
        self.b_cancel = self._btn("إلغاء", lambda: win.engine.cancel(self.tid), "danger")
        self.b_open = self._btn("تشغيل", self.open_file, "primary")
        self.b_folder = self._btn("إظهار في المجلد", self.show_folder)
        self.b_delete = self._btn("حذف", self.delete, "danger")
        for b in (self.b_open, self.b_folder, self.b_pause, self.b_resume, self.b_cancel, self.b_delete):
            btns.addWidget(b)
        lay.addLayout(btns)

        win.thumbs.loaded.connect(self._on_thumb)
        win.thumbs.request(t.thumb)
        self.refresh(t)

    def _btn(self, text, fn, name=None) -> QPushButton:
        b = QPushButton(text)
        if name:
            b.setObjectName(name)
        b.clicked.connect(lambda _=False: fn())
        return b

    def _on_thumb(self, url: str, pm) -> None:
        if url == self.thumb_url:
            self.thumb.setPixmap(fit_thumb(pm, 120, 68))

    def refresh(self, t: core.Task) -> None:
        self.is_done = t.status == core.DONE
        self.title.setText(t.title)
        self.badge.setText(t.q_label)
        pct = int(t.progress * 100)
        if t.status == core.QUEUED:
            txt = "في الانتظار"
        elif t.status == core.DOWNLOADING:
            if t.note == "processing":
                txt = "جارٍ المعالجة والدمج..."
            else:
                txt = " • ".join(x for x in (f"{pct}%", t.speed, f"متبقي {t.eta}" if t.eta else "") if x)
        elif t.status == core.PAUSED:
            txt = f"متوقف مؤقتاً • {pct}%"
        elif t.status == core.DONE:
            txt = "اكتمل" + (f" • {t.size}" if t.size else "")
        else:
            txt = "فشل: " + (t.error or "خطأ غير معروف")
        self.status.setText(txt)
        self.status.setStyleSheet("color:#C8402F;" if t.status == core.ERROR else "color:#857A69;")
        self.status.setWordWrap(True)

        busy = t.status == core.DOWNLOADING and t.note == "processing"
        self.bar.setVisible(t.status in (core.QUEUED, core.DOWNLOADING, core.PAUSED))
        if busy:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(t.progress * 1000))
        active = t.status in (core.QUEUED, core.DOWNLOADING)
        self.b_pause.setVisible(active)
        self.b_resume.setVisible(t.status in (core.PAUSED, core.ERROR))
        self.b_resume.setText("إعادة المحاولة" if t.status == core.ERROR else "استئناف")
        self.b_cancel.setVisible(t.status != core.DONE)
        for b in (self.b_open, self.b_folder):
            b.setVisible(t.status == core.DONE)
        self.b_delete.setVisible(t.status == core.DONE)

    def _task(self) -> Optional[core.Task]:
        return self.win.engine.get(self.tid)

    def open_file(self) -> None:
        t = self._task()
        if t and t.file_path and os.path.exists(t.file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(t.file_path))
        else:
            QMessageBox.warning(self, "MYVD", "الملف غير موجود (ربما اتنقل أو اتمسح).")

    def show_folder(self) -> None:
        t = self._task()
        if not t or not t.file_path:
            return
        if os.name == "nt" and os.path.exists(t.file_path):
            subprocess.Popen(["explorer", f"/select,{t.file_path}"])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(t.file_path)))

    def delete(self) -> None:
        t = self._task()
        if not t:
            return
        box = QMessageBox(self)
        box.setWindowTitle("حذف")
        box.setText(t.title)
        b1 = box.addButton("حذف الملف أيضاً", QMessageBox.ButtonRole.DestructiveRole)
        b2 = box.addButton("من القائمة فقط", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("إلغاء", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b1:
            self.win.engine.remove(self.tid, True)
        elif clicked is b2:
            self.win.engine.remove(self.tid, False)


# ------------------------------------------------------------------ dialogs

class AnalysisDialog(QDialog):
    preview_error = Signal(str)

    def __init__(self, a: core.Analysis, thumbs: ThumbLoader, parent=None):
        super().__init__(parent)
        self.a = a
        self.thumbs = thumbs
        self.setWindowTitle("نتيجة التحليل")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        self.thumb = QLabel()
        self.thumb.setFixedHeight(230)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background:#2B2822; border-radius:12px;")
        lay.addWidget(self.thumb)
        thumbs.loaded.connect(self.on_thumb)
        thumbs.request(a.thumb)

        title = QLabel(a.title)
        title.setWordWrap(True)
        title.setStyleSheet("font-size:12pt; font-weight:bold;")
        lay.addWidget(title)
        meta = " • ".join(x for x in (
            a.uploader or "",
            core.fmt_dur(a.duration) if a.duration else "",
            f"{len(a.entries)} فيديو" if a.is_playlist else "") if x)
        if meta:
            m = QLabel(meta)
            m.setStyleSheet("color:#857A69;")
            lay.addWidget(m)

        self.list: Optional[QListWidget] = None
        if a.is_playlist:
            self.list = QListWidget()
            self.list.setMinimumHeight(200)
            for i, e in enumerate(a.entries):
                it = QListWidgetItem(e.title)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked)
                it.setData(Qt.ItemDataRole.UserRole, i)
                self.list.addItem(it)
            self.list.itemChanged.connect(self.update_count)
            lay.addWidget(self.list)
            row = QHBoxLayout()
            b_all = QPushButton("تحديد الكل")
            b_none = QPushButton("إلغاء التحديد")
            b_all.clicked.connect(lambda _=False: self.set_all(True))
            b_none.clicked.connect(lambda _=False: self.set_all(False))
            row.addWidget(b_all)
            row.addWidget(b_none)
            row.addStretch(1)
            lay.addLayout(row)

        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("الجودة:"))
        self.combo = QComboBox()
        for q in a.qualities:
            self.combo.addItem(q.label, q)
        self.combo.setMinimumWidth(260)
        qrow.addWidget(self.combo, 1)
        lay.addLayout(qrow)

        brow = QHBoxLayout()
        self.b_preview = QPushButton("معاينة بدون إعلانات")
        self.b_preview.clicked.connect(self.on_preview)
        self.preview_error.connect(self.on_preview_error)
        self.b_ok = QPushButton("تحميل")
        self.b_ok.setObjectName("primary")
        self.b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("إلغاء")
        b_cancel.clicked.connect(self.reject)
        brow.addWidget(self.b_preview)
        brow.addStretch(1)
        brow.addWidget(b_cancel)
        brow.addWidget(self.b_ok)
        lay.addLayout(brow)
        self.update_count()

    def on_thumb(self, url: str, pm) -> None:
        if url == self.a.thumb:
            self.thumb.setPixmap(fit_thumb(pm, 520, 230))

    def set_all(self, on: bool) -> None:
        if self.list:
            for i in range(self.list.count()):
                self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def selected_entries(self):
        if not self.list:
            return list(self.a.entries)
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(self.a.entries[it.data(Qt.ItemDataRole.UserRole)])
        return out

    def quality(self) -> core.Quality:
        return self.combo.currentData()

    def update_count(self, *_):
        n = len(self.selected_entries())
        self.b_ok.setEnabled(n > 0)
        self.b_ok.setText(f"تحميل المحدد ({n})" if self.a.is_playlist else "تحميل")

    def on_preview(self) -> None:
        entries = self.selected_entries()
        if self.list and self.list.currentRow() >= 0:
            entries = [self.a.entries[self.list.item(self.list.currentRow()).data(Qt.ItemDataRole.UserRole)]]
        if not entries:
            return
        q = self.quality()
        url, h, audio = entries[0].url, q.height, q.audio is not None
        self.b_preview.setEnabled(False)
        self.b_preview.setText("جارٍ فتح المعاينة...")

        def work():
            try:
                core.preview(url, h, audio_only=audio)
                self.preview_error.emit("")
            except Exception as e:
                self.preview_error.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_preview_error(self, msg: str) -> None:
        self.b_preview.setEnabled(True)
        self.b_preview.setText("معاينة بدون إعلانات")
        if msg:
            QMessageBox.warning(self, "المعاينة", msg)


class SettingsDialog(QDialog):
    ver_ready = Signal(str)
    upd_ready = Signal(str)

    def __init__(self, settings: core.Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("الإعدادات")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        lay.addWidget(QLabel("مجلد التحميل:"))
        row = QHBoxLayout()
        self.dir_edit = QLineEdit(settings.download_dir)
        b = QPushButton("تغيير...")
        b.clicked.connect(self.pick_dir)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(b)
        lay.addLayout(row)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("عدد التحميلات المتزامنة:"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 3)
        self.spin.setValue(settings.parallel)
        prow.addWidget(self.spin)
        prow.addStretch(1)
        lay.addLayout(prow)

        self.ver = QLabel("إصدار yt-dlp: ...")
        lay.addWidget(self.ver)
        self.b_upd = QPushButton("تحديث yt-dlp الآن")
        self.b_upd.clicked.connect(self.do_update)
        lay.addWidget(self.b_upd)
        hint = QLabel("لو فيديو معين رفض يتحمل، حدّث yt-dlp (المواقع بتغيّر طرقها باستمرار).")
        hint.setStyleSheet("color:#857A69;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        brow = QHBoxLayout()
        brow.addStretch(1)
        ok = QPushButton("حفظ")
        ok.setObjectName("primary")
        ok.clicked.connect(self.save)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        brow.addWidget(cancel)
        brow.addWidget(ok)
        lay.addLayout(brow)

        self.ver_ready.connect(self.on_ver)
        self.upd_ready.connect(self.on_upd)
        threading.Thread(target=lambda: self.ver_ready.emit(core.ytdlp_version()), daemon=True).start()

    def on_ver(self, v: str) -> None:
        self.ver.setText("إصدار yt-dlp: " + v)

    def do_update(self) -> None:
        self.b_upd.setEnabled(False)
        self.ver.setText("جارٍ التحديث...")

        def work():
            msg = core.update_ytdlp()
            self.upd_ready.emit(msg)
        threading.Thread(target=work, daemon=True).start()

    def on_upd(self, msg: str) -> None:
        self.b_upd.setEnabled(True)
        self.ver.setText(msg)
        threading.Thread(target=lambda: self.ver_ready.emit(core.ytdlp_version()), daemon=True).start()

    def pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "اختر مجلد التحميل", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def save(self) -> None:
        self.settings.download_dir = self.dir_edit.text().strip() or self.settings.download_dir
        self.settings.parallel = self.spin.value()
        self.settings.save()
        self.accept()


class AndroidDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("نسخة الأندرويد")
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel("حمّل MYVD على موبايلك")
        t.setStyleSheet("font-size:13pt; font-weight:bold;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = QLabel("امسح الكود بكاميرا الموبايل لتنزيل ملف التطبيق (APK)")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet("color:#857A69;")
        lay.addWidget(s)
        qr = QLabel()
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr.setPixmap(make_qr_pixmap(core.ANDROID_URL))
        lay.addWidget(qr)
        row = QHBoxLayout()
        b1 = QPushButton("فتح رابط التنزيل")
        b1.setObjectName("primary")
        b1.clicked.connect(lambda _=False: open_url(core.ANDROID_URL))
        b2 = QPushButton("نسخ الرابط")
        b2.clicked.connect(lambda _=False: QApplication.clipboard().setText(core.ANDROID_URL))
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("حول البرنامج")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img = QLabel()
        img.setPixmap(logo_pixmap("robot_coffee.png", 140))
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(img)
        n = QLabel(f"{core.APP_NAME} للويندوز")
        n.setStyleSheet("font-size:16pt; font-weight:bold; color:#D86F12;")
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(n)
        v = QLabel(f"الإصدار {core.APP_VERSION}")
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setStyleSheet("color:#857A69;")
        lay.addWidget(v)
        c = QPushButton(core.CREDIT)
        c.setObjectName("link")
        c.clicked.connect(lambda _=False: open_url(core.SITE_URL))
        lay.addWidget(c)
        b = QPushButton("نسخة الأندرويد")
        b.clicked.connect(lambda _=False: AndroidDialog(self).exec())
        lay.addWidget(b)


# ------------------------------------------------------------------ main window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MYVD")
        self.resize(940, 760)
        self.setAcceptDrops(True)
        ico = core.assets_dir() / "icon.ico"
        if ico.exists():
            self.setWindowIcon(QIcon(str(ico)))

        self.settings = core.Settings()
        self.bridge = Bridge()
        self.thumbs = ThumbLoader()
        self.cards: dict = {}
        self.analyzing = False
        self.engine = core.Engine(self.settings, lambda tid: self.bridge.task_changed.emit(tid))
        self.bridge.task_changed.connect(self.on_task_changed)
        self.bridge.analysis_done.connect(self.on_analysis_done)
        self.bridge.analysis_failed.connect(self.on_analysis_failed)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 14, 18, 8)
        lay.setSpacing(12)

        # header
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap("robot_default.png", 64))
        head.addWidget(logo)
        tbox = QVBoxLayout()
        tbox.setSpacing(0)
        t = QLabel("MYVD")
        t.setStyleSheet("font-size:20pt; font-weight:bold; color:#D86F12;")
        s = QLabel("حمّل من يوتيوب وتيك توك وأكثر من 1000 موقع")
        s.setStyleSheet("color:#857A69;")
        tbox.addWidget(t)
        tbox.addWidget(s)
        head.addLayout(tbox)
        head.addStretch(1)
        menu_btn = QToolButton()
        menu_btn.setText("القائمة  ☰")
        menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        for text, fn in (
            ("الإعدادات وتحديث yt-dlp", self.open_settings),
            ("فتح مجلد التحميلات", self.open_downloads),
            ("مسح المكتمل من القائمة", lambda: self.engine.clear_done()),
            (None, None),
            ("نسخة الأندرويد (QR)", lambda: AndroidDialog(self).exec()),
            ("حول البرنامج", lambda: AboutDialog(self).exec()),
        ):
            if text is None:
                menu.addSeparator()
            else:
                act = menu.addAction(text)
                act.triggered.connect(lambda _=False, f=fn: f())
        menu_btn.setMenu(menu)
        head.addWidget(menu_btn)
        lay.addLayout(head)

        # warnings about missing tools
        warn = []
        if not core.ytdlp_cmd():
            warn.append(core.MISSING_YTDLP)
        if not core.ffmpeg_dir():
            warn.append("ffmpeg غير موجود: دمج الجودات العالية وتحويل MP3 لن يعملوا")
        if warn:
            w = QLabel("⚠ " + " | ".join(warn))
            w.setWordWrap(True)
            w.setStyleSheet("background:#FBE3DE; color:#C8402F; border-radius:10px; padding:8px 12px;")
            lay.addWidget(w)

        # input card
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 14, 14, 14)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("الصق رابط الفيديو هنا (أو اسحبه وارميه على النافذة)")
        self.url_edit.returnPressed.connect(self.start_analyze)
        cl.addWidget(self.url_edit)
        brow = QHBoxLayout()
        self.b_paste = QPushButton("لصق وتحليل")
        self.b_paste.setObjectName("primary")
        self.b_paste.clicked.connect(self.paste_and_analyze)
        self.b_analyze = QPushButton("تحليل الرابط")
        self.b_analyze.clicked.connect(self.start_analyze)
        brow.addWidget(self.b_paste)
        brow.addWidget(self.b_analyze)
        brow.addStretch(1)
        cl.addLayout(brow)
        lay.addWidget(card)

        # tabs
        self.tabs = QTabWidget()
        self.active_lay, self.active_empty, active_page = self._make_list("لا توجد تحميلات حالياً.\nالصق رابطاً وابدأ.")
        self.done_lay, self.done_empty, done_page = self._make_list("لا توجد ملفات مكتملة بعد.")
        top = QHBoxLayout()
        pa = QPushButton("إيقاف الكل")
        pa.clicked.connect(lambda _=False: self.engine.pause_all())
        ra = QPushButton("استئناف الكل")
        ra.clicked.connect(lambda _=False: self.engine.resume_all())
        top.addWidget(pa)
        top.addWidget(ra)
        top.addStretch(1)
        active_wrap = QWidget()
        aw = QVBoxLayout(active_wrap)
        aw.setContentsMargins(0, 6, 0, 0)
        aw.addLayout(top)
        aw.addWidget(active_page, 1)
        self.tabs.addTab(active_wrap, "التحميلات")
        self.tabs.addTab(done_page, "المكتملة")
        lay.addWidget(self.tabs, 1)

        # status bar
        credit = QPushButton(core.CREDIT)
        credit.setObjectName("link")
        credit.clicked.connect(lambda _=False: open_url(core.SITE_URL))
        self.statusBar().addPermanentWidget(credit)
        self.statusBar().showMessage(f"مجلد التحميل: {self.settings.download_dir}")

        self.rebuild()

    # ---- helpers
    def _make_list(self, empty_text: str):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("inner")
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 6, 4, 6)
        empty = QLabel(empty_text)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color:#857A69; padding:40px;")
        outer.addWidget(empty)
        lst = QVBoxLayout()
        lst.setSpacing(10)
        outer.addLayout(lst)
        outer.addStretch(1)
        scroll.setWidget(inner)
        return lst, empty, scroll

    def rebuild(self) -> None:
        tasks = self.engine.snapshot()
        ids = {t.id for t in tasks}
        for tid in list(self.cards):
            if tid not in ids:
                self.cards.pop(tid).deleteLater()
        for t in tasks:
            if t.id not in self.cards:
                self.cards[t.id] = TaskCard(t, self)
            else:
                self.cards[t.id].refresh(t)
        for lay in (self.active_lay, self.done_lay):
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                if w:
                    w.setParent(None)
        active = [t for t in tasks if t.status != core.DONE]
        done = [t for t in tasks if t.status == core.DONE]
        for t in active:
            self.active_lay.addWidget(self.cards[t.id])
            self.cards[t.id].show()
        for t in done:
            self.done_lay.addWidget(self.cards[t.id])
            self.cards[t.id].show()
        self.active_empty.setVisible(not active)
        self.done_empty.setVisible(not done)
        self.tabs.setTabText(0, f"التحميلات ({len(active)})" if active else "التحميلات")
        self.tabs.setTabText(1, f"المكتملة ({len(done)})" if done else "المكتملة")

    def on_task_changed(self, tid: str) -> None:
        if tid == "*":
            self.rebuild()
            return
        t = self.engine.get(tid)
        card = self.cards.get(tid)
        if not t or not card:
            self.rebuild()
            return
        was_done = card.is_done
        card.refresh(t)
        if card.is_done != was_done:
            self.rebuild()
        else:
            n = sum(1 for x in self.engine.snapshot() if x.status != core.DONE)
            self.tabs.setTabText(0, f"التحميلات ({n})" if n else "التحميلات")

    # ---- analyze flow
    def paste_and_analyze(self) -> None:
        url = core.extract_url(QApplication.clipboard().text())
        if not url:
            self.statusBar().showMessage("مفيش رابط في الحافظة", 4000)
            return
        self.url_edit.setText(url)
        self.start_analyze()

    def start_analyze(self) -> None:
        url = core.extract_url(self.url_edit.text()) or self.url_edit.text().strip()
        if not url or self.analyzing:
            return
        self.analyzing = True
        self.b_paste.setEnabled(False)
        self.b_analyze.setEnabled(False)
        self.statusBar().showMessage("جارٍ تحليل الرابط...")

        def work():
            try:
                self.bridge.analysis_done.emit(core.analyze(url))
            except Exception as e:
                self.bridge.analysis_failed.emit(core.clean_error(str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _analysis_finished(self) -> None:
        self.analyzing = False
        self.b_paste.setEnabled(True)
        self.b_analyze.setEnabled(True)

    def on_analysis_failed(self, msg: str) -> None:
        self._analysis_finished()
        self.statusBar().showMessage("فشل التحليل", 5000)
        QMessageBox.warning(self, "فشل التحليل", msg)

    def on_analysis_done(self, a) -> None:
        self._analysis_finished()
        self.statusBar().showMessage(f"مجلد التحميل: {self.settings.download_dir}")
        if not a.entries:
            QMessageBox.information(self, "MYVD", "مفيش فيديوهات في الرابط ده.")
            return
        dlg = AnalysisDialog(a, self.thumbs, self)
        if dlg.exec():
            entries, q = dlg.selected_entries(), dlg.quality()
            self.engine.add_all(entries, q)
            self.url_edit.clear()
            self.tabs.setCurrentIndex(0)
            self.statusBar().showMessage(f"تمت إضافة {len(entries)} إلى التحميلات", 5000)

    # ---- menu actions
    def open_settings(self) -> None:
        old = self.settings.download_dir
        if SettingsDialog(self.settings, self).exec():
            self.statusBar().showMessage(f"مجلد التحميل: {self.settings.download_dir}")
            self.engine.schedule()
            if old != self.settings.download_dir:
                QMessageBox.information(self, "MYVD", "المجلد الجديد يُطبَّق على التحميلات الجديدة.")

    def open_downloads(self) -> None:
        os.makedirs(self.settings.download_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.download_dir))

    # ---- drag & drop
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        md = e.mimeData()
        text = md.text() if md.hasText() else (md.urls()[0].toString() if md.hasUrls() else "")
        url = core.extract_url(text)
        if url:
            self.url_edit.setText(url)
            self.start_analyze()
