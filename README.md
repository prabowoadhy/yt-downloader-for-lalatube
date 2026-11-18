# YT Downloader App (Windows)

Aplikasi desktop Windows untuk download video YouTube dengan aturan ketat:
- **Video**: H.264 (avc1) maksimal 720p, audio AAC 128kbps
- **Thumbnail**: JPG, nama sama dengan video
- **Avatar Channel**: JPG, nama sama dengan folder channel
- **Folder Channel**: Nama = nama channel YouTube
- **Nama File Video**: Judul YouTube persis (hanya sanitasi karakter Windows)
- **Anti Double-Download**: Log JSONL, skip otomatis yang sudah ada

## Unduh Aplikasi (.exe)

**Siap pakai (tanpa install Python):**
https://github.com/prabowoadhy/yt-downloader-for-lalatube/releases/download/v1.0.0/YT-Downloader.exe

Langkah:
1. Unduh `YT-Downloader.exe` (55 MB) — taruh di folder tetap, mis. `D:\Tools\YT-Downloader\`
2. Buat file `config.yaml` di folder yang sama, isi minimal:
   ```yaml
   paths:
     main_folder: "D:/adip/Video Anak"
   ```
3. Pastikan `ffmpeg` tersedia di PATH (atau isi `paths.ffmpeg_path`)
4. Double-click `YT-Downloader.exe`, tempel daftar URL, klik **▶ Mulai Download**

## Struktur Folder Output
```
<Main Folder>/
├── Channel Name 1/
│   ├── Channel Name 1.jpg          ← Avatar
│   ├── Video Title 1.mp4
│   ├── Video Title 1.jpg           ← Thumbnail
│   ├── Video Title 2.mp4
│   └── Video Title 2.jpg
├── Channel Name 2/
│   ├── Channel Name 2.jpg
│   └── ...
└── download_log.jsonl              ← Log semua download
```

## Install & Run (Development)

```bash
# 1. Clone / buka folder
cd D:/Projects/2026/YT-Downloader-App

# 2. Buat virtual env
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -e .[build]

# 4. Install yt-dlp & ffmpeg (wajib)
#    - yt-dlp: pip install yt-dlp (sudah di dependencies)
#    - ffmpeg: download dari https://ffmpeg.org/download.html, extract, tambahkan ke PATH
#      ATAU set path di config.yaml (ffmpeg_path)

# 5. Copy config template
copy config\default_config.yaml config.yaml
# Edit config.yaml -> isi paths.main_folder

# 6. Run
python main.py
```

## Build Executable (.exe)

Cara paling mudah — jalankan `build.bat` (double-click), atau manual:

```bash
call .venv\Scripts\activate
pip install pyinstaller

.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed ^
    --name "YT-Downloader" ^
    --icon "assets\icon.ico" ^
    --add-data "config\default_config.yaml;config" ^
    --collect-submodules yt_dlp ^
    --exclude-module tkinter ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    main.py

# Output: dist/YT-Downloader.exe
```

Setelah jadi `.exe`: buat `config.yaml` di folder yang sama dengan `YT-Downloader.exe`
(isi `paths.main_folder`), lalu double-click exe.

## Config (config.yaml)

Field wajib:
```yaml
paths:
  main_folder: "D:/adip/Video Anak"    # Wajib diisi!
  # temp_folder: ""                    # Optional
  # ytdlp_path: ""                     # Optional (auto-detect from PATH)
  # ffmpeg_path: ""                    # Optional (auto-detect from PATH)
```

Field utama download:
```yaml
download:
  max_height: 720          # 240, 360, 480, 720, 1080
  video_codec: "h264"      # h264, hevc, vp9, av1
  audio_codec: "aac"
  audio_bitrate: "128k"
  crf: 21                  # 18-23 (semakin kecil = kualitas lebih bagus)
  preset: "medium"         # ultrafast .. veryslow
  max_duration: 1800       # Detik (0 = unlimited)
  skip_existing: true      # Cek log, skip yang sudah ada
  download_avatar: true    # Download avatar channel
```

## Cara Pakai

1. **Buka aplikasi** → klik **⚙ Pengaturan** → isi **Main Folder** → Simpan
2. **Paste URL** di kotak teks (satu per baris, atau koma/spasi):
   ```
   https://youtube.com/watch?v=abc123
   https://youtu.be/def456
   https://youtube.com/@ChannelName
   ```
3. Klik **▶ Mulai Download**
4. Progress muncul di panel bawah, log lengkap di tabel **Download Log**
5. File tersimpan di `Main Folder` sesuai struktur di atas

## Input URL Yang Didukung
- Video: `youtube.com/watch?v=ID`, `youtu.be/ID`
- Channel: `youtube.com/@ChannelName`, `youtube.com/channel/UC...`
- Playlist: `youtube.com/playlist?list=...` (download semua video)
- Video ID saja: `abc123def45`

## Log & Tracking
- `download_log.jsonl` — JSONL, satu baris per video
- `error_log.txt` — Error detail
- Tabel log di GUI bisa di-sort, filter

## Re-encode Otomatis
Jika video sumber **bukan H.264** atau **> 720p** (misal AV1 4K, VP9 1080p):
1. Download format terbaik yang tersedia
2. Probe codec/resolusi
3. Re-encode ke H.264 720p AAC via ffmpeg
4. Verifikasi hasil → ganti file lama
5. Log `status: "reencoded"` + simpan codec/resolusi asli

## Requirements
- Windows 10/11 (64-bit)
- Python 3.10+ (untuk development)
- ffmpeg di PATH (atau set di config)
- yt-dlp (auto-install via pip)

## License
MIT