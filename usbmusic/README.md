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

## PC workflow (dedicated stick)
1. One-time: format stick **FAT32** (Windows: right-click > Format > FAT32; >32GB: use `guiformat` or `diskpart`). Single partition only.
2. Copy docs/other files anywhere on the stick as usual. Keep them out of `Music/`.
3. Music: `python usbmusic\carusb.py "C:\Users\you\Music\MyFolder" --usb E:\`
   - Rebuilds only `E:\Music`; other files untouched
   - Warns if stick isn't FAT32; omit `--usb` if only one removable drive is plugged in
4. Safely eject, plug into car.
- Phase 2 DONE: Windows drive/FS detection, mac junk cleanup
