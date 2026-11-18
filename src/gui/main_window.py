"""
GUI Application (PySide6).
Window: URL input, config, progress, log.
"""
import sys
import os
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QProgressBar,
    QFileDialog, QMessageBox, QGroupBox, QFormLayout, QSpinBox,
    QCheckBox, QComboBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings
from PySide6.QtGui import QFont, QIcon, QTextCursor, QColor

# Import core modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config import load_config, DEFAULT_CONFIG, find_config_file
from core.downloader import YTDLPDownloader, DownloadResult
from core.logger import DownloadLog
from core.naming import parse_urls_input, is_video_url


class WorkerThread(QThread):
    """Background download thread."""
    progress = Signal(str, str)  # msg, level
    progress_count = Signal(int, int)  # index, total
    finished_one = Signal(object)  # DownloadResult
    all_finished = Signal(list)  # List[DownloadResult]
    error = Signal(str)

    def __init__(self, urls: List[str], config: dict):
        super().__init__()
        self.urls = urls
        self.config = config
        self._stop = False

    def run(self):
        try:
            downloader = YTDLPDownloader(self.config, progress_cb=self._emit_progress)
            # 1. Expand channel/playlist -> video IDs
            ids, seen = [], set()
            for url in self.urls:
                if self._stop:
                    break
                for vid in downloader.expand_input(url):
                    if vid and vid not in seen:
                        seen.add(vid)
                        ids.append(vid)

            # 2. Download per video
            results = []
            total = len(ids)
            for i, vid in enumerate(ids, 1):
                if self._stop:
                    break
                self.progress_count.emit(i, total)
                res = downloader.download_single(f"https://www.youtube.com/watch?v={vid}")
                results.append(res)
                self.finished_one.emit(res)
            self.all_finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _emit_progress(self, msg: str, level: str):
        self.progress.emit(msg, level)

    def stop(self):
        self._stop = True


class ConfigDialog(QWidget):
    """Dialog edit config.yaml."""
    saved = Signal(dict)

    def __init__(self, config: dict, config_path: str, parent=None):
        super().__init__(parent)
        self.config = config
        self.config_path = config_path
        self.setWindowTitle("Pengaturan (config.yaml)")
        self.resize(600, 700)
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        v = QVBoxLayout(content)

        # Paths
        g = QGroupBox("Paths")
        f = QFormLayout(g)
        self.ed_main = QLineEdit()
        self.ed_main.setPlaceholderText("D:/adip/Video Anak")
        btn_main = QPushButton("Browse")
        btn_main.clicked.connect(lambda: self._browse(self.ed_main))
        h = QHBoxLayout()
        h.addWidget(self.ed_main)
        h.addWidget(btn_main)
        f.addRow("Main Folder *", h)

        self.ed_temp = QLineEdit()
        f.addRow("Temp Folder", self.ed_temp)

        self.ed_ytdlp = QLineEdit()
        f.addRow("yt-dlp Path", self.ed_ytdlp)

        self.ed_ffmpeg = QLineEdit()
        f.addRow("ffmpeg Path", self.ed_ffmpeg)
        v.addWidget(g)

        # Download
        g = QGroupBox("Download Specs")
        f = QFormLayout(g)
        self.sp_height = QSpinBox()
        self.sp_height.setRange(240, 1080)
        self.sp_height.setSingleStep(120)
        f.addRow("Max Height", self.sp_height)

        self.cb_codec = QComboBox()
        self.cb_codec.addItems(["h264", "hevc", "vp9", "av1"])
        f.addRow("Video Codec", self.cb_codec)

        self.cb_acodec = QComboBox()
        self.cb_acodec.addItems(["aac", "opus", "mp3"])
        f.addRow("Audio Codec", self.cb_acodec)

        self.ed_abit = QLineEdit()
        f.addRow("Audio Bitrate", self.ed_abit)

        self.sp_crf = QSpinBox()
        self.sp_crf.setRange(15, 30)
        f.addRow("CRF (quality)", self.sp_crf)

        self.cb_preset = QComboBox()
        self.cb_preset.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        f.addRow("Preset", self.cb_preset)

        self.sp_dur = QSpinBox()
        self.sp_dur.setRange(0, 7200)
        self.sp_dur.setSuffix(" detik")
        f.addRow("Max Duration", self.sp_dur)

        self.chk_skip = QCheckBox()
        f.addRow("Skip Existing (log)", self.chk_skip)

        self.chk_avatar = QCheckBox()
        f.addRow("Download Avatar", self.chk_avatar)
        v.addWidget(g)

        # Naming
        g = QGroupBox("Naming Rules")
        f = QFormLayout(g)
        self.sp_maxlen = QSpinBox()
        self.sp_maxlen.setRange(50, 255)
        f.addRow("Max Filename Len", self.sp_maxlen)
        v.addWidget(g)

        # Behavior
        g = QGroupBox("Behavior")
        f = QFormLayout(g)
        self.chk_verify = QCheckBox()
        f.addRow("Verify Before Swap", self.chk_verify)

        self.chk_del = QCheckBox()
        f.addRow("Delete Source After Reencode", self.chk_del)

        self.sp_parallel = QSpinBox()
        self.sp_parallel.setRange(1, 4)
        f.addRow("Parallel Downloads", self.sp_parallel)

        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(60, 3600)
        self.sp_timeout.setSuffix(" detik")
        f.addRow("Timeout", self.sp_timeout)

        self.chk_continue = QCheckBox()
        f.addRow("Continue on Error", self.chk_continue)
        v.addWidget(g)

        # Buttons
        btns = QHBoxLayout()
        btn_save = QPushButton("Simpan")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Batal")
        btn_cancel.clicked.connect(self.close)
        btns.addStretch()
        btns.addWidget(btn_save)
        btns.addWidget(btn_cancel)
        v.addLayout(btns)

        layout.addWidget(scroll)

    def _browse(self, line: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Pilih Folder")
        if d:
            line.setText(d)

    def _load_values(self):
        p = self.config["paths"]
        self.ed_main.setText(p.get("main_folder", ""))
        self.ed_temp.setText(p.get("temp_folder", ""))
        self.ed_ytdlp.setText(p.get("ytdlp_path", ""))
        self.ed_ffmpeg.setText(p.get("ffmpeg_path", ""))

        d = self.config["download"]
        self.sp_height.setValue(d.get("max_height", 720))
        self.cb_codec.setCurrentText(d.get("video_codec", "h264"))
        self.cb_acodec.setCurrentText(d.get("audio_codec", "aac"))
        self.ed_abit.setText(d.get("audio_bitrate", "128k"))
        self.sp_crf.setValue(d.get("crf", 21))
        self.cb_preset.setCurrentText(d.get("preset", "medium"))
        self.sp_dur.setValue(d.get("max_duration", 1800))
        self.chk_skip.setChecked(d.get("skip_existing", True))
        self.chk_avatar.setChecked(d.get("download_avatar", True))

        n = self.config["naming"]
        self.sp_maxlen.setValue(n.get("max_filename_len", 150))

        b = self.config["behavior"]
        self.chk_verify.setChecked(b.get("verify_before_swap", True))
        self.chk_del.setChecked(b.get("delete_source_after_reencode", True))
        self.sp_parallel.setValue(b.get("parallel_downloads", 1))
        self.sp_timeout.setValue(b.get("timeout", 600))
        self.chk_continue.setChecked(b.get("continue_on_error", True))

    def _save(self):
        # Build config dict
        cfg = self.config.copy()
        cfg["paths"]["main_folder"] = self.ed_main.text().strip()
        cfg["paths"]["temp_folder"] = self.ed_temp.text().strip()
        cfg["paths"]["ytdlp_path"] = self.ed_ytdlp.text().strip()
        cfg["paths"]["ffmpeg_path"] = self.ed_ffmpeg.text().strip()

        cfg["download"]["max_height"] = self.sp_height.value()
        cfg["download"]["video_codec"] = self.cb_codec.currentText()
        cfg["download"]["audio_codec"] = self.cb_acodec.currentText()
        cfg["download"]["audio_bitrate"] = self.ed_abit.text().strip() or "128k"
        cfg["download"]["crf"] = self.sp_crf.value()
        cfg["download"]["preset"] = self.cb_preset.currentText()
        cfg["download"]["max_duration"] = self.sp_dur.value()
        cfg["download"]["skip_existing"] = self.chk_skip.isChecked()
        cfg["download"]["download_avatar"] = self.chk_avatar.isChecked()

        cfg["naming"]["max_filename_len"] = self.sp_maxlen.value()

        cfg["behavior"]["verify_before_swap"] = self.chk_verify.isChecked()
        cfg["behavior"]["delete_source_after_reencode"] = self.chk_del.isChecked()
        cfg["behavior"]["parallel_downloads"] = self.sp_parallel.value()
        cfg["behavior"]["timeout"] = self.sp_timeout.value()
        cfg["behavior"]["continue_on_error"] = self.chk_continue.isChecked()

        # Validate
        if not cfg["paths"]["main_folder"]:
            QMessageBox.warning(self, "Error", "Main Folder wajib diisi!")
            return

        # Save to file
        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, sort_keys=False, indent=2)

        self.saved.emit(cfg)
        QMessageBox.information(self, "OK", "Config disimpan.")
        self.close()


class LogTableWidget(QTableWidget):
    """Table untuk menampilkan download log."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels(["Video ID", "Title", "Channel", "Size (MB)", "Codec", "Status", "Date"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

    def load_log(self, log: DownloadLog):
        records = log.all()
        self.setRowCount(len(records))
        for row, r in enumerate(records):
            self.setItem(row, 0, QTableWidgetItem(r.video_id))
            self.setItem(row, 1, QTableWidgetItem(r.title[:60]))
            self.setItem(row, 2, QTableWidgetItem(r.channel_name))
            self.setItem(row, 3, QTableWidgetItem(f"{r.size_mb:.1f}"))
            self.setItem(row, 4, QTableWidgetItem(f"{r.codec} {r.height}p"))
            status_item = QTableWidgetItem(r.status)
            if r.status == "reencoded":
                status_item.setBackground(QColor(255, 255, 200))
            elif r.status == "failed":
                status_item.setBackground(QColor(255, 200, 200))
            self.setItem(row, 5, status_item)
            self.setItem(row, 6, QTableWidgetItem(r.download_date[:19].replace("T", " ")))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YT Downloader - Windows")
        self.resize(1000, 700)

        # Ikon jendela (jika ada)
        try:
            from PySide6.QtGui import QIcon
            ico = Path(__file__).parent.parent.parent / "assets" / "icon.ico"
            if not ico.exists():
                ico = Path(__file__).parent.parent.parent / "assets" / "icon.png"
            if ico.exists():
                self.setWindowIcon(QIcon(str(ico)))
        except Exception:
            pass

        # Load config
        self.config_path = str(find_config_file() or Path(__file__).parent.parent.parent / "config.yaml")
        self.config = load_config()

        # State
        self.worker: Optional[WorkerThread] = None
        self.results: List[DownloadResult] = []

        self._build_ui()
        self._refresh_log_table()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top: Config status
        top = QHBoxLayout()
        self.lbl_config = QLabel(f"Config: {self.config_path}")
        self.lbl_config.setStyleSheet("color: gray; font-size: 11px;")
        btn_cfg = QPushButton("⚙ Pengaturan")
        btn_cfg.clicked.connect(self._open_config)
        btn_refresh = QPushButton("🔄 Refresh Log")
        btn_refresh.clicked.connect(self._refresh_log_table)
        top.addWidget(self.lbl_config)
        top.addStretch()
        top.addWidget(btn_cfg)
        top.addWidget(btn_refresh)
        main_layout.addLayout(top)

        # Splitter: Input + Progress | Log Table
        splitter = QSplitter(Qt.Vertical)

        # --- Input Panel ---
        input_widget = QWidget()
        iv = QVBoxLayout(input_widget)

        # URL Input
        g = QGroupBox("URL Video / Channel (satu per baris, atau koma/spasi)")
        gl = QVBoxLayout(g)
        self.txt_urls = QTextEdit()
        self.txt_urls.setPlaceholderText("https://youtube.com/watch?v=...\nhttps://youtu.be/...\nAtau paste list URL di sini...")
        self.txt_urls.setMaximumHeight(120)
        gl.addWidget(self.txt_urls)

        # Buttons
        hb = QHBoxLayout()
        self.btn_start = QPushButton("▶ Mulai Download")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.clicked.connect(self._start_download)
        self.btn_stop = QPushButton("■ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_download)
        self.btn_clear = QPushButton("Clear Input")
        self.btn_clear.clicked.connect(lambda: self.txt_urls.clear())
        hb.addWidget(self.btn_start)
        hb.addWidget(self.btn_stop)
        hb.addWidget(self.btn_clear)
        hb.addStretch()
        gl.addLayout(hb)
        iv.addWidget(g)

        # Progress
        g = QGroupBox("Progress")
        gl = QVBoxLayout(g)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        gl.addWidget(self.progress_bar)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(150)
        self.txt_log.setFont(QFont("Consolas", 9))
        gl.addWidget(self.txt_log)
        iv.addWidget(g)

        splitter.addWidget(input_widget)

        # --- Log Table Panel ---
        log_widget = QWidget()
        lv = QVBoxLayout(log_widget)
        g = QGroupBox("Download Log (dari download_log.jsonl)")
        gl = QVBoxLayout(g)
        self.log_table = LogTableWidget()
        gl.addWidget(self.log_table)

        # Stats
        self.lbl_stats = QLabel("Total: 0 video | 0 MB | 0 channel")
        self.lbl_stats.setStyleSheet("font-weight: bold; padding: 5px;")
        gl.addWidget(self.lbl_stats)
        lv.addWidget(g)
        splitter.addWidget(log_widget)

        splitter.setSizes([400, 300])
        main_layout.addWidget(splitter)

        # Status bar
        self.statusBar().showMessage("Siap. Isi URL dan klik Mulai.")

    def _open_config(self):
        dlg = ConfigDialog(self.config, self.config_path, self)
        dlg.saved.connect(self._on_config_saved)
        dlg.show()

    def _on_config_saved(self, new_config: dict):
        self.config = new_config
        self.lbl_config.setText(f"Config: {self.config_path}")
        self.statusBar().showMessage("Config diperbarui.")

    def _start_download(self):
        text = self.txt_urls.toPlainText()
        urls, invalid = parse_urls_input(text)
        if not urls:
            if invalid:
                QMessageBox.warning(
                    self, "Input Tidak Valid",
                    "Tidak ada URL video YouTube yang valid.\n\n"
                    "Hanya gunakan URL video tunggal, contoh:\n"
                    "  https://youtube.com/watch?v=abc123\n"
                    "  https://youtu.be/abc123\n"
                    "  abc123def45 (video ID saja)\n\n"
                    "URL channel, playlist, dan yang bukan YouTube diabaikan."
                )
            else:
                QMessageBox.warning(self, "Error", "Tidak ada URL valid di input.")
            return

        # Validasi config
        if not self.config["paths"]["main_folder"]:
            QMessageBox.warning(self, "Error", "Main Folder belum diset. Buka Pengaturan.")
            return

        # Tampilkan daftar yang diabaikan (jika ada)
        if invalid:
            skipped = "\n".join(f"• {x}" for x in invalid[:10])
            if len(invalid) > 10:
                skipped += f"\n... dan {len(invalid) - 10} lainnya"
            self._log(f"Diabaikan (bukan video tunggal): {len(invalid)} item", "WARNING")
            self.txt_log.append(f'<span style="color:orange">[SKIP] {skipped}</span>')

        # UI state
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.txt_urls.setReadOnly(True)
        self.progress_bar.setValue(0)
        self.txt_log.clear()
        self.results = []

        # Start worker
        self.worker = WorkerThread(urls, self.config)
        self.worker.progress.connect(self._on_progress)
        self.worker.progress_count.connect(self._on_progress_count)
        self.worker.finished_one.connect(self._on_finished_one)
        self.worker.all_finished.connect(self._on_all_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

        self.statusBar().showMessage(f"Download dimulai: {len(urls)} URL")

    def _stop_download(self):
        if self.worker:
            self.worker.stop()
            self.btn_stop.setEnabled(False)
            self._log("Stop requested...", "WARNING")

    def _on_progress(self, msg: str, level: str):
        self._log(msg, level)

    def _on_progress_count(self, index: int, total: int):
        if total > 0:
            self.progress_bar.setValue(int(index * 100 / total))

    def _on_finished_one(self, res: DownloadResult):
        self.results.append(res)
        # Log ke panel jika gagal atau skip
        if not res.success:
            self._log(f"GAGAL: {res.video_id or res.url} — {res.error}", "ERROR")
        elif "SKIPPED" in (res.error or ""):
            self._log(f"SKIP: {res.video_id} — {res.title[:50]}", "WARNING")
        else:
            self._log(f"OK: {res.video_id} — {res.title[:50]}", "INFO")

    def _on_all_finished(self, results: List[DownloadResult]):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.txt_urls.setReadOnly(False)
        self.progress_bar.setValue(100)

        ok = sum(1 for r in results if r.success and "SKIPPED" not in r.error)
        skipped = sum(1 for r in results if "SKIPPED" in r.error)
        fail = sum(1 for r in results if not r.success)

        self._log(f"SELESAI: {ok} baru, {skipped} skip, {fail} gagal", "INFO")
        self.statusBar().showMessage(f"Selesai: {ok} baru, {skipped} skip, {fail} gagal")
        self._refresh_log_table()

    def _on_error(self, err: str):
        self._log(f"ERROR: {err}", "ERROR")
        QMessageBox.critical(self, "Error", err)

    def _log(self, msg: str, level: str = "INFO"):
        color = {"INFO": "black", "WARNING": "orange", "ERROR": "red"}.get(level, "black")
        self.txt_log.append(f'<span style="color:{color}">[{level}] {msg}</span>')
        self.txt_log.moveCursor(QTextCursor.End)

    def _refresh_log_table(self):
        try:
            log = DownloadLog(Path(self.config["logging"]["log_file"]))
            self.log_table.load_log(log)
            stats = log.stats()
            self.lbl_stats.setText(
                f"Total: {stats['total_videos']} video | "
                f"{stats['total_size_mb']:.1f} MB | "
                f"{len(stats['by_channel'])} channel"
            )
        except Exception as e:
            self.lbl_stats.setText(f"Log error: {e}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("YT Downloader")
    app.setOrganizationName("LalaTubeTools")

    # Style
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()