"""
Core downloader menggunakan yt-dlp.
Mengimplementasikan semua aturan: H.264 720p, thumbnail, avatar, naming, log.
"""
import subprocess
import json
import threading
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

from .config import load_config
from .naming import sanitize_filename, sanitize_folder_name, extract_video_id
from .logger import DownloadLog, VideoRecord, ErrorLog


@dataclass
class DownloadResult:
    success: bool
    video_id: str
    url: str = ""
    title: str = ""
    channel: str = ""
    folder: str = ""
    video_file: str = ""
    thumb_file: str = ""
    avatar_file: str = ""
    error: str = ""
    was_reencoded: bool = False
    original_codec: str = ""
    original_height: int = 0
    original_size_mb: float = 0


class YTDLPDownloader:
    """
    Wrapper yt-dlp dengan aturan tetap:
    - Format: bestvideo[height<=720][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[height<=720]
    - Output: <main_folder>/<channel>/<title>.mp4
    - Thumbnail: <main_folder>/<channel>/<title>.jpg
    - Avatar: <main_folder>/<channel>/<channel>.jpg
    - Log: JSONL
    """

    def __init__(self, config: Dict[str, Any], progress_cb: Optional[Callable] = None):
        self.cfg = config
        self.progress_cb = progress_cb
        self.log = DownloadLog(Path(config["logging"]["log_file"]))
        self.err_log = ErrorLog(Path(config["logging"]["error_log"]))
        self._stop = False

        # Resolve executables
        self.ytdlp = self._find_exe("ytdlp_path", "yt-dlp")
        self.ffmpeg = self._find_exe("ffmpeg_path", "ffmpeg")
        # ffprobe: biasanya ada di folder yang sama dengan ffmpeg
        ffprobe_cfg = self.cfg["paths"].get("ffprobe_path", "")
        if ffprobe_cfg and Path(ffprobe_cfg).exists():
            self.ffprobe = ffprobe_cfg
        else:
            ffprobe_candidate = Path(self.ffmpeg).parent / "ffprobe.exe"
            if ffprobe_candidate.exists():
                self.ffprobe = str(ffprobe_candidate)
            else:
                self.ffprobe = self._find_exe("ffprobe_path", "ffprobe")

    def _find_exe(self, config_key: str, default_name: str) -> str:
        path = self.cfg["paths"].get(config_key, "")
        if path and Path(path).exists():
            return path
        # Cari di PATH
        import shutil
        found = shutil.which(default_name)
        if found:
            return found
        raise FileNotFoundError(f"{default_name} tidak ditemukan. Set {config_key} di config.yaml atau tambahkan ke PATH.")

    def _emit(self, msg: str, level: str = "INFO") -> None:
        if self.progress_cb:
            self.progress_cb(msg, level)
        print(f"[{level}] {msg}")

    def stop(self) -> None:
        self._stop = True

    def download_urls(self, urls: List[str]) -> List[DownloadResult]:
        """Download multiple URL (video / channel / playlist), expand dulu."""
        results = []
        # 1. Expand semua input -> daftar video ID
        all_ids: List[str] = []
        seen = set()
        for url in urls:
            if self._stop:
                break
            ids = self.expand_input(url)
            for vid in ids:
                if vid and vid not in seen:
                    seen.add(vid)
                    all_ids.append(vid)

        if not all_ids:
            return results

        # 2. Download satu per satu
        for vid in all_ids:
            if self._stop:
                break
            res = self.download_single(f"https://www.youtube.com/watch?v={vid}")
            results.append(res)
        return results

    def expand_input(self, url: str) -> List[str]:
        """
        Ubah input (video / channel / playlist) jadi daftar video ID.
        - Video: langsung return [id]
        - Channel/playlist: pakai --flat-playlist, filter durasi & jumlah.
        """
        is_channel = any(x in url for x in ("/@", "/channel/", "/c/", "/user/"))
        is_playlist = ("list=" in url) or ("/playlist" in url)
        if not is_channel and not is_playlist:
            vid = extract_video_id(url)
            return [vid] if vid else []

        # Channel / playlist -> flat playlist
        self._emit(f"Ambil daftar video dari: {url}")
        args = [
            self.ytdlp, "--flat-playlist", "--no-warnings",
            "--ignore-errors", "--no-playlist" if "/watch" in url else "--yes-playlist",
            "--print", "%(id)s\t%(duration)s\t%(title)s",
        ]
        if self.cfg["advanced"]["cookies_file"]:
            args.extend(["--cookies", self.cfg["advanced"]["cookies_file"]])
        if self.cfg["advanced"]["proxy"]:
            args.extend(["--proxy", self.cfg["advanced"]["proxy"]])
        args.append(url)

        try:
            r = subprocess.run(args, capture_output=True, text=True,
                               timeout=self.cfg["behavior"]["timeout"])
        except subprocess.TimeoutExpired:
            self.err_log.write("", url, "Timeout saat ambil daftar playlist", "expand_input")
            return []

        ids = []
        max_dur = self.cfg["download"]["max_duration"]
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if not parts or not parts[0].strip():
                continue
            item_id = parts[0].strip()
            try:
                dur = float(parts[1]) if len(parts) > 1 and parts[1].strip() not in ("", "NA", "None") else 0
            except ValueError:
                dur = 0
            if max_dur and dur > max_dur:
                continue
            ids.append(item_id)

        # Batasi jumlah (channel video biasanya urut terbaru dulu)
        limit_new = self.cfg["download"].get("newest_first", 0)
        limit_ch = self.cfg["download"].get("max_per_channel", 0)
        limit = limit_new or limit_ch
        if limit:
            ids = ids[:limit]

        self._emit(f"  {len(ids)} video ditemukan dari {url}")
        return ids

    def download_single(self, url: str) -> DownloadResult:
        """Download satu video + thumbnail + avatar."""
        vid = extract_video_id(url)
        if not vid:
            return DownloadResult(success=False, video_id="", error="Invalid URL/ID", url=url)

        # Cek log (skip existing)
        if self.cfg["download"]["skip_existing"] and self.log.exists(vid):
            rec = self.log.get(vid)
            return DownloadResult(
                success=True, video_id=vid, title=rec.title, channel=rec.channel_name,
                folder=rec.folder_name, video_file=rec.video_filename,
                thumb_file=rec.thumbnail_filename, avatar_file=rec.avatar_filename,
                error="SKIPPED (already in log)"
            )

        self._emit(f"Mulai: {url}")

        try:
            # 1. Info video (judul, channel, durasi)
            info = self._get_video_info(url, vid)
            if not info:
                self._emit("  Gagal ambil info video (yt-dlp gagal atau video tidak tersedia)", "ERROR")
                return DownloadResult(success=False, video_id=vid, error="Gagal ambil info video", url=url)

            title = info["title"]
            channel = info["channel"]
            duration = info.get("duration", 0)
            channel_url = info.get("channel_url", "")

            # Validasi durasi
            max_dur = self.cfg["download"]["max_duration"]
            if max_dur and duration > max_dur:
                return DownloadResult(
                    success=False, video_id=vid, title=title, channel=channel,
                    error=f"Durasi {duration}s > max {max_dur}s"
                )

            # 2. Siapkan folder & nama file
            folder_name = sanitize_folder_name(channel, self.cfg["naming"]["max_filename_len"])
            video_name = sanitize_filename(title, self.cfg["naming"]["max_filename_len"])
            main_folder = Path(self.cfg["paths"]["main_folder"])
            channel_folder = main_folder / folder_name
            channel_folder.mkdir(parents=True, exist_ok=True)

            video_file = channel_folder / f"{video_name}.mp4"
            thumb_file = channel_folder / f"{video_name}.jpg"
            avatar_file = channel_folder / f"{folder_name}.jpg"

            # Unique name jika bentrok
            video_file = self._make_unique(video_file)
            thumb_file = thumb_file.with_stem(video_file.stem)
            # avatar tidak di-unique (satu per folder)

            # 3. Download video + thumbnail
            self._emit(f"  Download video: {video_name[:50]}...")
            ytdlp_args = self._build_ytdlp_args(url, video_file, thumb_file)
            result = subprocess.run(ytdlp_args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.cfg["behavior"]["timeout"])

            if result.returncode != 0:
                # Coba fallback format
                self._emit(f"  Format utama gagal, coba fallback...", "WARNING")
                ytdlp_args = self._build_ytdlp_args(url, video_file, thumb_file, fallback=True)
                result = subprocess.run(ytdlp_args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.cfg["behavior"]["timeout"])

            if result.returncode != 0 or not video_file.exists():
                err = result.stderr[-500:] if result.stderr else "Unknown error"
                self.err_log.write(vid, url, err, "yt-dlp download")
                return DownloadResult(success=False, video_id=vid, title=title, channel=channel, error=f"Download gagal: {err}")

            # 4. Verify & re-encode jika perlu
            was_reencoded = False
            orig_codec = orig_height = ""
            orig_size = 0
            if self.cfg["behavior"]["verify_before_swap"]:
                probe = self._probe_video(video_file)
                if probe and (probe["codec"] != "h264" or probe["height"] > 720):
                    self._emit(f"  Re-encode: {probe['codec']} {probe['height']}p -> h264 720p")
                    orig_codec = probe["codec"]
                    orig_height = probe["height"]
                    orig_size = probe["size_mb"]
                    if self._reencode_video(video_file):
                        was_reencoded = True
                        # Re-probe
                        probe = self._probe_video(video_file)
                    else:
                        self.err_log.write(vid, url, "Re-encode gagal", "reencode")

            # 5. Download avatar channel (jika belum ada)
            if self.cfg["download"]["download_avatar"] and not avatar_file.exists() and channel_url:
                self._emit(f"  Download avatar: {folder_name}")
                self._download_avatar(channel_url, avatar_file)

            # 6. Pastikan thumbnail ada & ber-ekstensi .jpg (nama = nama video)
            thumb_file = self._ensure_thumbnail(video_file) or thumb_file

            # 7. Log success
            final_probe = self._probe_video(video_file) or {}
            rec = VideoRecord(
                video_id=vid,
                url=url,
                title=title,
                channel_name=channel,
                folder_name=folder_name,
                video_filename=video_file.name,
                thumbnail_filename=thumb_file.name if thumb_file.exists() else "",
                avatar_filename=avatar_file.name if avatar_file.exists() else "",
                codec=final_probe.get("codec", "h264"),
                height=final_probe.get("height", 720),
                audio_codec=final_probe.get("audio_codec", "aac"),
                duration=duration,
                size_mb=final_probe.get("size_mb", video_file.stat().st_size / 1048576),
                ytdlp_version=self._get_version("yt-dlp"),
                ffmpeg_version=self._get_version("ffmpeg"),
                status="reencoded" if was_reencoded else "completed",
                original_codec=orig_codec,
                original_height=orig_height,
                original_size_mb=orig_size,
            )
            self.log.add(rec)

            self._emit(f"  SELESAI: {video_name[:50]} ({rec.size_mb:.1f} MB)")
            return DownloadResult(
                success=True, video_id=vid, title=title, channel=channel,
                folder=folder_name, video_file=video_file.name,
                thumb_file=thumb_file.name if thumb_file.exists() else "",
                avatar_file=avatar_file.name if avatar_file.exists() else "",
                was_reencoded=was_reencoded,
                original_codec=orig_codec, original_height=orig_height, original_size_mb=orig_size,
            )

        except subprocess.TimeoutExpired:
            err = f"Timeout ({self.cfg['behavior']['timeout']}s)"
            self.err_log.write(vid, url, err, "timeout")
            return DownloadResult(success=False, video_id=vid, error=err)
        except Exception as e:
            self.err_log.write(vid, url, str(e), "exception")
            return DownloadResult(success=False, video_id=vid, error=str(e))

    def _get_video_info(self, url: str) -> Optional[Dict]:
        """Ambil metadata video via yt-dlp --dump-json."""
        args = [
            self.ytdlp, "--no-warnings", "--dump-json",
            "--no-playlist", url
        ]
        # Add cookies if configured
        if self.cfg["advanced"]["cookies_file"]:
            args.extend(["--cookies", self.cfg["advanced"]["cookies_file"]])
        if self.cfg["advanced"]["proxy"]:
            args.extend(["--proxy", self.cfg["advanced"]["proxy"]])

        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if result.returncode != 0:
            err = result.stderr[-300:] if result.stderr else "Unknown error"
            self._emit(f"  yt-dlp error: {err}", "ERROR")
            self.err_log.write(vid if hasattr(self, '_current_vid') else "unknown", url, err, "yt-dlp info")
            return None
        try:
            data = json.loads(result.stdout)
            return {
                "title": data.get("title", "Unknown"),
                "channel": data.get("channel", data.get("uploader", "Unknown Channel")),
                "channel_url": data.get("channel_url", ""),
                "duration": data.get("duration", 0),
            }
        except json.JSONDecodeError:
            return None

    def _build_ytdlp_args(self, url: str, video_out: Path, thumb_out: Path, fallback: bool = False) -> List[str]:
        """Bangun argumen yt-dlp."""
        # Format selection
        if fallback:
            # Fallback: best available <= 720p, any codec (akan di-reencode nanti)
            fmt = f"bestvideo[height<={self.cfg['download']['max_height']}]+bestaudio/best[height<={self.cfg['download']['max_height']}]"
        else:
            # Utama: H.264 + AAC <= 720p
            max_h = self.cfg["download"]["max_height"]
            fmt = f"bestvideo[height<={max_h}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[height<={max_h}][vcodec^=avc1]/bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]"

        args = [
            self.ytdlp,
            "--no-warnings",
            "--no-playlist",
            "-f", fmt,
            "--merge-output-format", "mp4",
            "-o", str(video_out),
            "--write-thumbnail",
            "--convert-thumbnails", self.cfg["download"]["thumbnail_format"],
            "--embed-metadata" if self.cfg["advanced"]["embed_metadata"] else "--no-embed-metadata",
            "--embed-thumbnail" if self.cfg["advanced"]["embed_thumbnail"] else "--no-embed-thumbnail",
            "--embed-chapters" if self.cfg["advanced"]["embed_chapters"] else "--no-embed-chapters",
            "--ffmpeg-location", str(Path(self.ffmpeg).parent),
        ]

        if self.cfg["advanced"]["sponsorblock_remove"]:
            args.extend(["--sponsorblock-remove", "all"])

        if self.cfg["advanced"]["cookies_file"]:
            args.extend(["--cookies", self.cfg["advanced"]["cookies_file"]])
        if self.cfg["advanced"]["proxy"]:
            args.extend(["--proxy", self.cfg["advanced"]["proxy"]])

        # User agent
        args.extend(["--user-agent", self.cfg["advanced"]["user_agent"]])

        args.append(url)
        return args

    def _probe_video(self, path: Path) -> Optional[Dict]:
        """Probe video via ffprobe."""
        args = [
            self.ffprobe, "-v", "error",
            "-print_format", "json",
            "-show_streams", "-show_format",
            str(path)
        ]
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
            a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
            if not v:
                return None
            return {
                "codec": v.get("codec_name", ""),
                "height": v.get("height", 0),
                "width": v.get("width", 0),
                "audio_codec": a.get("codec_name", "") if a else "",
                "size_mb": int(data["format"]["size"]) / 1048576,
            }
        except Exception:
            return None

    def _reencode_video(self, path: Path) -> bool:
        """Re-encode ke H.264 720p AAC."""
        tmp = path.with_suffix(".tmp.mp4")
        args = [
            self.ffmpeg, "-y",
            "-i", str(path),
            "-vf", f"scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:v", "libx264",
            "-preset", self.cfg["download"]["preset"],
            "-crf", str(self.cfg["download"]["crf"]),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.cfg["download"]["audio_bitrate"],
            "-movflags", "+faststart",
            str(tmp)
        ]
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.cfg["behavior"]["timeout"])
        if result.returncode != 0 or not tmp.exists():
            if tmp.exists():
                tmp.unlink()
            return False
        # Atomic replace
        path.unlink()
        tmp.rename(path)
        return True

    def _ensure_thumbnail(self, video: Path) -> Optional[Path]:
        """
        Pastikan thumbnail ada dengan nama = nama video + .jpg.
        yt-dlp kadang menulis thumbnail tanpa ekstensi / ekstensi aneh
        (mis. judul berakhiran titik) -> konversi ke .jpg.
        """
        target = video.with_suffix(".jpg")
        if target.exists() and target.stat().st_size > 1000:
            return target

        # Kandidat: file lain dengan stem sama (bukan video)
        cands = [p for p in video.parent.iterdir()
                 if p.is_file() and p.stem == video.stem and p.suffix.lower() != ".mp4"]

        # 1) Sudah berupa gambar valid
        for c in cands:
            suf = c.suffix.lower()
            if suf in (".jpg", ".jpeg") and c.stat().st_size > 1000:
                if c != target:
                    c.replace(target)
                return target
            if suf in (".png", ".webp") and c.stat().st_size > 1000:
                r = subprocess.run([self.ffmpeg, "-y", "-i", str(c), "-q:v", "2", str(target)],
                                   capture_output=True, timeout=60)
                if r.returncode == 0 and target.exists() and target.stat().st_size > 1000:
                    c.unlink(missing_ok=True)
                    return target

        # 2) Tanpa ekstensi / ekstensi tak dikenal -> konversi via ffmpeg
        for c in cands:
            r = subprocess.run([self.ffmpeg, "-y", "-i", str(c), "-q:v", "2", str(target)],
                               capture_output=True, timeout=60)
            if r.returncode == 0 and target.exists() and target.stat().st_size > 1000:
                c.unlink(missing_ok=True)
                return target

        # 3) Fallback: ambil frame dari video
        if self._extract_thumbnail_ffmpeg(video, target):
            return target
        return None

    def _download_avatar(self, channel_url: str, out_path: Path) -> bool:
        """Download avatar dari halaman channel."""
        import urllib.request
        try:
            # Ambil HTML channel
            req = urllib.request.Request(
                channel_url,
                headers={"User-Agent": self.cfg["advanced"]["user_agent"],
                         "Accept-Language": "en-US,en;q=0.9"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Ekstrak avatar URL
            m = re.search(r'"avatar":\{"thumbnails":\[\{"url":"([^"]+)"', html)
            if not m:
                return False
            avatar_url = m.group(1).replace("\\u0026", "&")

            # Download
            req = urllib.request.Request(avatar_url, headers={"User-Agent": self.cfg["advanced"]["user_agent"]})
            with urllib.request.urlopen(req, timeout=30) as resp:
                out_path.write_bytes(resp.read())
            return out_path.stat().st_size > 1000
        except Exception:
            return False

    def _extract_thumbnail_ffmpeg(self, video: Path, thumb: Path) -> bool:
        """Extract thumbnail dari video via ffmpeg (frame pertama)."""
        args = [
            self.ffmpeg, "-y",
            "-i", str(video),
            "-ss", "00:00:01",
            "-vframes", "1",
            "-q:v", "2",
            str(thumb)
        ]
        result = subprocess.run(args, capture_output=True, timeout=30)
        return result.returncode == 0 and thumb.exists()

    def _make_unique(self, path: Path) -> Path:
        """Jika file ada, tambah (1), (2), dst."""
        if not path.exists():
            return path
        stem, suffix, parent = path.stem, path.suffix, path.parent
        for i in range(1, 1000):
            cand = parent / f"{stem} ({i}){suffix}"
            if not cand.exists():
                return cand
        raise RuntimeError(f"Tidak bisa buat nama unik: {path}")

    def _get_version(self, tool: str) -> str:
        exe = self.ytdlp if tool == "yt-dlp" else self.ffmpeg
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""


if __name__ == "__main__":
    # Test config load
    cfg = load_config()
    print(f"Config: {cfg['paths']['main_folder']}")