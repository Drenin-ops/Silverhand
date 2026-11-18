#!/usr/bin/env python3
"""carusb: prepare a music folder for a 2015 Toyota Avalon USB port.

Runs in Termux on Android (also Linux/Mac/Windows with ffmpeg).
  - keeps MP3/M4A/AAC/WMA as-is (car-native)
  - converts FLAC/OGG/OPUS/WAV/etc. to MP3 (ffmpeg)
  - flattens to Folder/track (max 2 levels), ASCII-safe short names
  - track-number prefixes so play order is stable
  - caps files per folder
  - copies to USB if one is writable, else leaves a ready folder to copy

Usage:
  python carusb.py SRC [-o OUT] [--usb PATH] [--bitrate 192] [--max-per-folder 250]
"""
import argparse, os, re, shutil, subprocess, sys, unicodedata
from pathlib import Path

NATIVE = {".mp3", ".m4a", ".aac", ".wma"}
CONVERT = {".flac", ".ogg", ".opus", ".wav", ".alac", ".aiff", ".ape", ".wv"}
MAXNAME = 40  # chars per file/folder name


def safe(s, n=MAXNAME):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9 ._()&'-]", "", s).strip(" .")
    s = re.sub(r"\s+", " ", s)
    return (s[:n].rstrip(" .") or "untitled")


def find_usb():
    """Return a writable removable-drive mount, or None."""
    cands = []
    for base in ("/storage", "/media", "/run/media", "/mnt", "/Volumes"):
        p = Path(base)
        if p.is_dir():
            for d in p.rglob("*") if base in ("/media", "/run/media") else p.iterdir():
                if d.is_dir() and d.name not in ("emulated", "self", "sdcard0"):
                    cands.append(d)
    for d in cands:
        if os.access(d, os.W_OK):
            return d
    return None


def plan(src: Path, max_per):
    """Group audio files by their top-level folder under src."""
    groups = {}
    for f in sorted(src.rglob("*")):
        if f.is_file() and f.suffix.lower() in NATIVE | CONVERT:
            rel = f.relative_to(src)
            key = rel.parts[0] if len(rel.parts) > 1 else "Music"
            groups.setdefault(key, []).append(f)
    out = []
    for key, files in groups.items():
        for i in range(0, len(files), max_per):
            chunk = files[i:i + max_per]
            name = safe(key) + (f" {i // max_per + 1}" if len(files) > max_per else "")
            out.append((name, chunk))
    return out


def convert(f: Path, dst: Path, bitrate):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(f), "-vn",
           "-map_metadata", "0", "-id3v2_version", "3",
           "-codec:a", "libmp3lame", "-b:a", f"{bitrate}k", str(dst)]
    return subprocess.run(cmd).returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", default=str(Path.home() / "CarMusic"))
    ap.add_argument("--usb", help="USB mount path (auto-detect if omitted)")
    ap.add_argument("--bitrate", type=int, default=192)
    ap.add_argument("--max-per-folder", type=int, default=250)
    ap.add_argument("--no-usb", action="store_true", help="only build OUT folder")
    a = ap.parse_args()

    src, out = Path(a.src).expanduser(), Path(a.out).expanduser()
    if not src.is_dir():
        sys.exit(f"source not found: {src}")
    if any(f.suffix.lower() in CONVERT for f in src.rglob("*")) and not shutil.which("ffmpeg"):
        sys.exit("ffmpeg missing. In Termux: pkg install ffmpeg")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    total = skipped = conv = 0
    for fname, files in plan(src, a.max_per_folder):
        d = out / fname
        d.mkdir(exist_ok=True)
        for n, f in enumerate(files, 1):
            ext = f.suffix.lower()
            stem = safe(re.sub(r"^\d+[\s._-]*", "", f.stem))
            if ext in NATIVE:
                dst = d / f"{n:03d} {stem}{ext}"
                shutil.copy2(f, dst)
            else:
                dst = d / f"{n:03d} {stem}.mp3"
                if not convert(f, dst, a.bitrate):
                    print(f"  skip (convert failed): {f.name}")
                    skipped += 1
                    continue
                conv += 1
            total += 1
        print(f"{fname}: {len(files)} files")
    print(f"done: {total} tracks ({conv} converted, {skipped} failed) -> {out}")

    if a.no_usb:
        return
    usb = Path(a.usb) if a.usb else find_usb()
    if usb and os.access(usb, os.W_OK):
        dest = usb / "Music"
        try:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(out, dest)
            os.sync() if hasattr(os, "sync") else None
            print(f"copied to USB: {dest}  (eject before unplugging)")
            return
        except OSError as e:
            print(f"USB write failed ({e})")
    print("No writable USB from this app (normal on Android).\n"
          f"Open Files app -> copy the '{out.name}' folder to the USB drive.")


if __name__ == "__main__":
    main()
