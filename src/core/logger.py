"""
Download log & tracking (JSONL format).
Mencegah double-download, menyimpan metadata lengkap.
"""
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict, field


@dataclass
class VideoRecord:
    """Satu entri video di log."""
    # Identitas
    video_id: str
    url: str
    title: str

    # Lokasi
    channel_name: str
    folder_name: str

    # File
    video_filename: str
    thumbnail_filename: str
    avatar_filename: str = ""

    # Spec
    codec: str = "h264"
    height: int = 720
    audio_codec: str = "aac"
    duration: float = 0
    size_mb: float = 0

    # Metadata
    download_date: str = field(default_factory=lambda: datetime.now().isoformat())
    ytdlp_version: str = ""
    ffmpeg_version: str = ""

    # Status
    status: str = "completed"  # completed, failed, skipped, reencoded

    # Original (jika di-reencode)
    original_codec: str = ""
    original_height: int = 0
    original_size_mb: float = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "VideoRecord":
        return cls(**json.loads(s))

    @property
    def unique_key(self) -> str:
        """Key unik untuk deteksi duplikat: video_id."""
        return self.video_id


class DownloadLog:
    """
    Thread-safe JSONL log.
    - Satu baris per video
    - Index by video_id untuk lookup cepat
    """

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._index: Dict[str, VideoRecord] = {}
        self._load()

    def _load(self) -> None:
        """Load all entries ke memory index."""
        if not self.log_path.exists():
            return
        with self.log_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = VideoRecord.from_json(line)
                    self._index[rec.unique_key] = rec
                except Exception as e:
                    print(f"[Log] Warning: baris {line_num} corrupt: {e}")

    def exists(self, video_id: str) -> bool:
        """Cek apakah video_id sudah di-download."""
        with self._lock:
            return video_id in self._index

    def get(self, video_id: str) -> Optional[VideoRecord]:
        with self._lock:
            return self._index.get(video_id)

    def add(self, record: VideoRecord) -> None:
        """Tambah/replace record."""
        with self._lock:
            self._index[record.unique_key] = record
            self._write_record(record)

    def _write_record(self, record: VideoRecord) -> None:
        """Append satu record ke file (thread-safe via lock)."""
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")

    def update(self, video_id: str, **fields) -> bool:
        """Update field tertentu pada record existing."""
        with self._lock:
            if video_id not in self._index:
                return False
            rec = self._index[video_id]
            for k, v in fields.items():
                if hasattr(rec, k):
                    setattr(rec, k, v)
            # Rewrite file (simple approach - file tidak terlalu besar)
            self._rewrite_all()
            return True

    def _rewrite_all(self) -> None:
        """Tulis ulang seluruh file dari index."""
        with self.log_path.open("w", encoding="utf-8") as f:
            for rec in self._index.values():
                f.write(rec.to_json() + "\n")

    def all(self) -> List[VideoRecord]:
        with self._lock:
            return list(self._index.values())

    def by_channel(self, channel: str) -> List[VideoRecord]:
        with self._lock:
            return [r for r in self._index.values() if r.channel_name == channel]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._index)
            by_channel = {}
            total_size = 0
            for r in self._index.values():
                by_channel[r.channel_name] = by_channel.get(r.channel_name, 0) + 1
                total_size += r.size_mb
            return {
                "total_videos": total,
                "total_size_mb": round(total_size, 2),
                "by_channel": by_channel,
            }


class ErrorLog:
    """Simple error log (text)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, video_id: str, url: str, error: str, context: str = "") -> None:
        with self._lock:
            ts = datetime.now().isoformat()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {video_id} | {url}\n")
                if context:
                    f.write(f"  Context: {context}\n")
                f.write(f"  Error: {error}\n")
                f.write("-" * 60 + "\n")


if __name__ == "__main__":
    # Test
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        log = DownloadLog(Path(tmp) / "test.jsonl")
        rec = VideoRecord(
            video_id="abc123",
            url="https://youtube.com/watch?v=abc123",
            title="Test Video",
            channel_name="Test Channel",
            folder_name="Test Channel",
            video_filename="Test Video.mp4",
            thumbnail_filename="Test Video.jpg",
            size_mb=50.5,
        )
        log.add(rec)
        print(f"Exists: {log.exists('abc123')}")
        print(f"Stats: {log.stats()}")