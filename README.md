# Korean OCR Subtitle Extractor (desktop app)

A real desktop app: open a video, drag a box around the burned-in Korean
caption area, click Run, get a timed `.srt` file. No browser, no chat, no
Claude Code needed to use it once it's set up.

Uses `ffmpeg` for frame extraction and `PaddleOCR` for recognition — the
same pipeline validated in this project's `/ocr-srt` skill, wrapped in a
Tkinter GUI (`app.py`) instead of being driven conversationally.

## Quick start (Windows)

1. Double-click **`setup.bat`** once. It installs the Python dependencies
   (this downloads a few hundred MB — PaddleOCR's underlying ML library is
   not small).
2. Double-click **`run.bat`** to launch the app.
3. In the app: **Open Video** → pick a video → **Grab Preview Frame** →
   drag a box around the captions → **Run** → **Save .srt As…**.

## Requirements

- **Python 3.10+** on your PATH. `setup.bat` checks for this and tells you
  where to get it if it's missing.
- **ffmpeg + ffprobe** on your PATH. If you don't have them, either install
  them (e.g. `winget install Gyan.FFmpeg`), or drop `ffmpeg.exe` and
  `ffprobe.exe` into the `bin/` folder here — `ocr_core.py` checks `bin/`
  first, system PATH second.
- Internet access on first real run, to download PaddleOCR's Korean model
  files (~50MB, one-time, cached after that). Everything else runs fully
  offline.

## Honest state of "download and use"

This is a real, working app today — I've run it and it launches, and the
underlying pipeline is validated end-to-end on real video. But it currently
still requires Python + a `pip install` step, which is a real (if small)
piece of friction for a fully non-technical recipient.

The next step to remove that entirely is packaging this into a single
`.exe` with **PyInstaller** that bundles Python, PaddleOCR, and ffmpeg
together — genuinely zero-install for the end user. I haven't done that yet
on purpose: PaddlePaddle specifically has a rockier-than-average track
record with PyInstaller (native extensions, large data files, C++ runtime
quirks), and getting it right can turn into real trial-and-error. Worth
doing if you want to actually hand this to someone else; happy to take a
run at it — just flagging it's a separate, less predictable chunk of work
from what's built so far.

## Project layout

```
app.py          Tkinter GUI — all the interactive/UI code
ocr_core.py     The OCR pipeline itself (no GUI code) — extraction,
                frame-diff grouping, PaddleOCR calls, text cleanup, SRT
                writing. Imported by app.py; also usable standalone/scripted.
bin/            Empty by default (dev machines use system ffmpeg via PATH).
                Only populate with ffmpeg.exe/ffprobe.exe when building a
                package for someone without ffmpeg installed.
requirements.txt
setup.bat       One-time dependency install (Windows)
run.bat         Launch the app (Windows)
```

## Known limitations (v1)

- Windows-focused (`setup.bat`/`run.bat`); the Python code itself is
  cross-platform, but a Mac/Linux user would run `pip install -r
  requirements.txt && python app.py` directly instead.
- Crop region is picked from one preview frame — if a video's caption
  position moves around, you'll get worse results after that point (same
  caveat as the browser extension and the `/ocr-srt` skill).
- `Enhance light-colored text` is off by default — it actively hurts
  accuracy on dark-text-on-light-bubble caption styles (common on Korean
  variety shows). Only turn it on if your video's captions are light
  text on a dark/busy background and plain OCR is doing worse.
