"""
Sanitasi nama file untuk Windows/NTFS.
Aturan: nama = judul YouTube persis, hanya ganti karakter ilegal.
"""
import re
from pathlib import Path
from typing import Optional


# Karakter dilarang Windows: < > : " / \ | ? * dan control chars 0-31
ILLEGAL_CHARS = r'[<>:"\/|?*\x00-\x1f]'
# Karakter yang aman diganti spasi
REPLACEMENT = " "
# Maks panjang nama file (NTFS limit 255, tapi kita batasi)
DEFAULT_MAX_LEN = 150


def sanitize_filename(name: str, max_len: int = DEFAULT_MAX_LEN) -> str:
    """
    Sanitasi nama file untuk Windows.
    - Ganti karakter ilegal jadi spasi
    - Collapse multiple spaces
    - Strip leading/trailing spaces dan dots
    - Truncate ke max_len
    """
    if not name:
        return "Untitled"

    # Ganti karakter ilegal
    name = re.sub(ILLEGAL_CHARS, REPLACEMENT, name)

    # Collapse whitespace
    name = re.sub(r"\s+", " ", name)

    # Strip spaces dan dots di ujung
    name = name.strip(" .")

    # Truncate
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")

    return name or "Untitled"


def sanitize_folder_name(name: str, max_len: int = DEFAULT_MAX_LEN) -> str:
    """Sama seperti sanitize_filename tapi untuk nama folder."""
    return sanitize_filename(name, max_len)


def make_unique_path(path: Path, max_attempts: int = 1000) -> Path:
    """
    Jika path sudah ada, tambah suffix (1), (2), dst.
    Return path yang belum ada.
    """
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    for i in range(1, max_attempts + 1):
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Tidak bisa buat nama unik untuk {path} setelah {max_attempts} percobaan")


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Ekstrak video ID dari URL YouTube video saja (bukan channel/playlist)."""
    import re
    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",   # watch?v=ID
        r"youtu\.be/([A-Za-z0-9_-]{11})",  # youtu.be/ID
        r"^([A-Za-z0-9_-]{11})$",  # sudah ID murni
    ]
    for p in patterns:
        m = re.search(p, url_or_id)
        if m:
            return m.group(1)
    return None


def is_video_url(text: str) -> bool:
    """Cek apakah teks adalah URL video YouTube tunggal (bukan channel/playlist)."""
    text = text.strip()
    if not text:
        return False
    # Tidak boleh ada parameter playlist
    if "list=" in text:
        return False
    # Pola channel / user yang tidak boleh diterima
    channel_patterns = [
        r"/@[\w.-]+",           # youtube.com/@Channel
        r"/channel/[\w-]+",     # youtube.com/channel/UC...
        r"/c/[\w.-]+",          # youtube.com/c/Channel
        r"/user/[\w.-]+",       # youtube.com/user/Channel
    ]
    for p in channel_patterns:
        if re.search(p, text):
            return False
    # Harus cocok dengan pola video
    return extract_video_id(text) is not None


def parse_urls_input(text: str) -> tuple[list[str], list[str]]:
    """
    Parse input URL dari user (bisa multi-baris, koma, spasi).
    Return (list_url_video_valid, list_input_invalid).
    Hanya URL video tunggal yang diterima (channel/playlist ditolak).
    """
    parts = re.split(r"[\n,\s]+", text.strip())
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not is_video_url(p):
            invalid.append(p)
            continue
        # Normalisasi ke URL penuh jika hanya ID
        if re.match(r"^[A-Za-z0-9_-]{11}$", p):
            p = f"https://www.youtube.com/watch?v={p}"
        # Hindari duplikat
        vid = extract_video_id(p)
        if vid and vid not in seen:
            seen.add(vid)
            valid.append(p)

    return valid, invalid


if __name__ == "__main__":
    # Test
    tests = [
        "Kepala Pundak Lutut Kaki 🎵 Lagu Anak",
        "Test<>:File|Name?.mp4",
        "A" * 200,
        "  Spasi  Awal Akhir  ",
        "Titik...Di...Tengah...",
    ]
    for t in tests:
        print(f"'{t[:40]}' -> '{sanitize_filename(t)}'")