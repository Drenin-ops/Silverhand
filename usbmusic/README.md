# carusb: phone music -> 2015 Avalon USB

## One-time (Android)
1. Install Termux (F-Droid). In Termux:
   - `pkg install python ffmpeg`
   - `termux-setup-storage`
2. Copy `carusb.py` to the phone (e.g. Download/).
3. Format the USB stick as **FAT32** (<=32GB safest).

## Each run
- `python ~/storage/downloads/carusb.py ~/storage/music/MyFolder`
- Output: `~/CarMusic` (car-ready)
- Copy `CarMusic` to the USB with the Files app (Android blocks Termux from writing to USB root).
- Eject, plug into car.

## What it does
- Keeps MP3/M4A/AAC/WMA; converts FLAC/OGG/OPUS/WAV to MP3 192k
- Max 2 folder levels, ASCII names <=40 chars, `001 ` track prefixes
- Max 250 files per folder (`--max-per-folder`)

## Handoff block (update each phase)
- Phase 1 DONE: carusb.py built + tested on Linux (convert, flatten, rename)
- Open: test on real phone + Avalon; verify Toyota limits (folder/file caps)
- Next: optional Android shortcut (Termux:Widget) for one-tap run
