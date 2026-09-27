# Korean OCR Subtitle Extractor

A desktop app that turns burned-in (hardsubbed) Korean captions into a timed
`.srt` file. Open a video, drag a box around the caption area, click Run.

![Korean OCR Subtitle Extractor: a caption region selected on a video frame, with the cropped preview below](docs/screenshot.png)

Uses `ffmpeg` for frame extraction and `PaddleOCR` for recognition, with a
Tkinter GUI (`app.py`) on top. Frames are only re-OCR'd when the caption
region changes, and consecutive identical lines are merged into one cue.

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

## Roadmap

- **Single-file `.exe`**: package Python, PaddleOCR and ffmpeg together with
  PyInstaller so there's nothing to install. PaddlePaddle's native extensions
  and large model files make this harder than usual.

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
  position moves around, you'll get worse results after that point.
- `Enhance light-colored text` is off by default — it actively hurts
  accuracy on dark-text-on-light-bubble caption styles (common on Korean
  variety shows). Only turn it on if your video's captions are light
  text on a dark/busy background and plain OCR is doing worse.
