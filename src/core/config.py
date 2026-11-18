"""
Configuration loader dengan validasi & default.
Mendukung config.yaml di folder config/ atau di samping exe.
"""
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
import copy


DEFAULT_CONFIG = {
    "paths": {
        "main_folder": "",
        "temp_folder": "",
        "ytdlp_path": "",
        "ffmpeg_path": "",
    },
    "download": {
        "max_height": 720,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_bitrate": "128k",
        "crf": 21,
        "preset": "medium",
        "thumbnail_format": "jpg",
        "thumbnail_quality": 90,
        "download_avatar": True,
        "avatar_format": "jpg",
        "max_duration": 1800,
        "skip_existing": True,
        "max_per_channel": 0,
        "newest_first": 0,
    },
    "naming": {
        "folder_equals_channel": True,
        "video_equals_title": True,
        "max_filename_len": 150,
        "thumbnail_same_name": True,
        "avatar_same_as_folder": True,
    },
    "logging": {
        "log_file": "download_log.jsonl",
        "error_log": "error_log.txt",
        "level": "INFO",
        "save_metadata": True,
    },
    "behavior": {
        "delete_source_after_reencode": True,
        "verify_before_swap": True,
        "parallel_downloads": 1,
        "parallel_reencode": 1,
        "timeout": 600,
        "continue_on_error": True,
    },
    "advanced": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "cookies_file": "",
        "proxy": "",
        "sponsorblock_remove": False,
        "embed_metadata": True,
        "embed_thumbnail": True,
        "embed_chapters": True,
    },
}


def deep_merge(base: Dict, override: Dict) -> Dict:
    """Merge override ke base secara rekursif."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def find_config_file(explicit_path: Optional[str] = None) -> Optional[Path]:
    """Cari file config.yaml di lokasi standar."""
    candidates = []

    if explicit_path:
        candidates.append(Path(explicit_path))

    # Di samping exe/script
    if hasattr(__import__('sys'), 'frozen'):
        # PyInstaller
        base = Path(__import__('sys').executable).parent
    else:
        base = Path(__file__).parent.parent.parent  # src/core/ -> root

    candidates.extend([
        base / "config.yaml",
        base / "config" / "config.yaml",
        base / "config" / "default_config.yaml",
        Path.cwd() / "config.yaml",
        Path.cwd() / "config" / "config.yaml",
    ])

    for c in candidates:
        if c.exists():
            return c
    return None


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load config dari file YAML, merge dengan default.
    Validasi field wajib.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    # Load dari file
    found = find_config_file(config_path)
    if found:
        with open(found, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = deep_merge(cfg, user_cfg)
        cfg["_config_file"] = str(found)
    else:
        cfg["_config_file"] = None

    # Resolve paths
    for key in ["main_folder", "temp_folder", "ytdlp_path", "ffmpeg_path"]:
        val = cfg["paths"][key]
        if val:
            cfg["paths"][key] = str(Path(val).expanduser().resolve())

    # Validasi wajib
    errors = []
    if not cfg["paths"]["main_folder"]:
        errors.append("paths.main_folder wajib diisi di config.yaml")

    if cfg["download"]["max_height"] not in [240, 360, 480, 720, 1080]:
        errors.append("download.max_height harus salah satu: 240,360,480,720,1080")

    if cfg["download"]["video_codec"] not in ["h264", "hevc", "vp9", "av1"]:
        errors.append("download.video_codec tidak valid")

    if errors:
        raise ValueError("Config error:\n  - " + "\n  - ".join(errors))

    return cfg


def save_config(cfg: Dict[str, Any], path: str) -> None:
    """Simpan config ke file YAML (hanya field non-default/_internal)."""
    # Hapus field internal
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(clean, f, allow_unicode=True, sort_keys=False, indent=2)


def get_config_template() -> str:
    """Template config.yaml untuk user."""
    return Path(__file__).parent.parent.parent.joinpath("config/default_config.yaml").read_text(encoding="utf-8")


if __name__ == "__main__":
    # Test load
    try:
        c = load_config()
        print("Config loaded OK")
        print(f"Main folder: {c['paths']['main_folder']}")
    except Exception as e:
        print(f"Config error (expected jika belum diisi): {e}")