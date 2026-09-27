"""
Core OCR-subtitle pipeline, shared by the desktop app (app.py).

Same approach validated in dojo-prompts/scripts/ocr_srt.py: ffmpeg extracts
frames already cropped to the caption region, consecutive near-identical
frames are grouped so we don't re-OCR every frame, PaddleOCR (Korean model)
reads one representative frame per group, and the recognized text is cleaned
up (stray glyph removal, re-spacing via kiwipiepy if available, fuzzy
duplicate merge) before being written out as an SRT.

This module has no GUI code — app.py drives it and supplies progress/log
callbacks so the UI can stay responsive during a run.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image

DEFAULT_REGION = (0.05, 0.78, 0.90, 0.16)  # x,y,w,h fractions — bottom-center guess
DIFF_SIZE = (64, 24)
CHANGE_THRESHOLD = 12.0
MIN_STABLE_FRAMES = 2
MIN_CUE_DURATION = 0.5
MIN_REC_SCORE = 0.55
OCR_TARGET_HEIGHT = 110

STRAY_GLYPHS = re.compile(r"[|↓↑←→▶◀●■□]")

ProgressCB = Optional[Callable[[int, int, str], None]]  # (current, total, stage)
LogCB = Optional[Callable[[str], None]]


# ── binary resolution (bundled first, then PATH — see README for packaging) ──

def _find_binary(name: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    candidate = base / "bin" / f"{name}.exe"
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"Couldn't find {name}. Expected it bundled in a 'bin' folder next to "
        f"the app, or available on PATH."
    )


def ffmpeg_path() -> str:
    return _find_binary("ffmpeg")


def ffprobe_path() -> str:
    return _find_binary("ffprobe")


# ── ffprobe helpers ───────────────────────────────────────────────────────────

def probe_dims(video: str) -> tuple[int, int]:
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)


def probe_duration(video: str) -> float:
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def region_to_px(region, w, h) -> tuple[int, int, int, int]:
    x, y, rw, rh = region
    return (round(x * w), round(y * h), round(rw * w), round(rh * h))


def extract_preview_frame(video: str, timestamp: float, out_path: str):
    subprocess.run(
        [ffmpeg_path(), "-y", "-ss", str(timestamp), "-i", str(video),
         "-frames:v", "1", out_path],
        check=True, capture_output=True,
    )


# ── frame diffing / grouping ─────────────────────────────────────────────────

def _load_diff_array(path: Path) -> np.ndarray:
    img = Image.open(path).convert("L").resize(DIFF_SIZE)
    return np.asarray(img, dtype=np.float32)


def group_frames(frame_files: list[Path]) -> list[tuple[int, int]]:
    groups: list[list[int]] = []
    prev = None
    for i, f in enumerate(frame_files):
        arr = _load_diff_array(f)
        if prev is not None and float(np.abs(arr - prev).mean()) <= CHANGE_THRESHOLD:
            groups[-1][1] = i
        else:
            groups.append([i, i])
        prev = arr
    return [(g[0], g[1]) for g in groups]


# ── OCR ───────────────────────────────────────────────────────────────────────

def make_ocr(lang: str = "korean"):
    from paddleocr import PaddleOCR
    return PaddleOCR(
        lang=lang,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        text_det_limit_side_len=320,
        text_det_limit_type="max",
    )


def enhance_light_text(img: Image.Image, threshold: float = 0.68) -> Image.Image:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    lightness = (arr.max(axis=2) + arr.min(axis=2)) / 2.0 / 255.0
    out = np.where(lightness[..., None] > threshold, 0, 255).astype(np.uint8)
    return Image.fromarray(np.repeat(out[..., :1], 3, axis=2))


_kiwi = None


def respace(text: str) -> str:
    global _kiwi
    if _kiwi is False:
        return text
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        except ImportError:
            _kiwi = False
            return text
    try:
        return _kiwi.space(text)
    except Exception:
        return text


def ocr_frame(ocr, path: Path, enhance: bool) -> str:
    img = Image.open(path)
    if img.height < OCR_TARGET_HEIGHT:
        scale = OCR_TARGET_HEIGHT / img.height
        img = img.resize((round(img.width * scale), round(img.height * scale)))
    if enhance:
        img = enhance_light_text(img)

    tmp_path = path.with_suffix(".ocr_tmp.jpg")
    img.convert("RGB").save(tmp_path, quality=95)
    try:
        results = list(ocr.predict(str(tmp_path)))
    finally:
        tmp_path.unlink(missing_ok=True)

    pieces = []
    for res in results:
        texts = res.get("rec_texts") or []
        scores = res.get("rec_scores") or []
        boxes = res.get("rec_boxes")
        rows = list(zip(texts, scores, boxes if boxes is not None else [None] * len(texts)))
        rows = [r for r in rows if r[1] >= MIN_REC_SCORE and r[0].strip()]
        rows.sort(key=lambda r: (r[2][1], r[2][0]) if r[2] is not None else (0, 0))
        pieces.extend(r[0].strip() for r in rows)
    text = " ".join(pieces).strip()
    text = STRAY_GLYPHS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = respace(text)
    return text


# ── cues / SRT ────────────────────────────────────────────────────────────────

@dataclass
class Cue:
    start: float
    end: float
    text: str


def fmt_srt_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = round((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[Cue], out_path: str):
    lines = []
    for i, c in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{fmt_srt_time(c.start)} --> {fmt_srt_time(c.end)}")
        lines.append(c.text)
        lines.append("")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


# ── full pipeline ─────────────────────────────────────────────────────────────

class Cancelled(Exception):
    pass


def run_pipeline(
    video: str,
    region: tuple[float, float, float, float],
    fps: float = 3.0,
    lang: str = "korean",
    enhance: bool = False,
    progress_cb: ProgressCB = None,
    log_cb: LogCB = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    keep_frames: bool = False,
) -> list[Cue]:
    """Run the full extract -> group -> OCR -> merge pipeline. Returns cues.
    Does not write the SRT itself — call write_srt() with the result."""

    def log(msg: str):
        if log_cb:
            log_cb(msg)

    def check_cancel():
        if cancel_check and cancel_check():
            raise Cancelled()

    w, h = probe_dims(video)
    x, y, rw, rh = region_to_px(region, w, h)

    frames_dir = Path(tempfile.mkdtemp(prefix="ocr_app_frames_"))
    try:
        log(f"Extracting frames at {fps}fps, cropped to {rw}x{rh}+{x}+{y} ...")
        subprocess.run(
            [ffmpeg_path(), "-y", "-i", str(video),
             "-vf", f"crop={rw}:{rh}:{x}:{y},fps={fps}",
             "-q:v", "3", str(frames_dir / "%06d.jpg")],
            check=True, capture_output=True,
        )
        check_cancel()
        frame_files = sorted(frames_dir.glob("*.jpg"))
        if not frame_files:
            log("No frames extracted — check the video path and crop region.")
            return []
        log(f"{len(frame_files)} frames extracted. Grouping by visual change ...")

        groups = group_frames(frame_files)
        check_cancel()
        candidate_groups = [g for g in groups if (g[1] - g[0] + 1) >= MIN_STABLE_FRAMES]
        log(f"{len(groups)} runs found, {len(candidate_groups)} stable enough to OCR.")

        log("Loading PaddleOCR (Korean) ...")
        ocr = make_ocr(lang)
        check_cancel()

        raw_cues: list[Cue] = []
        total = len(candidate_groups)
        for n, (start_i, end_i) in enumerate(candidate_groups, 1):
            check_cancel()
            mid = frame_files[(start_i + end_i) // 2]
            text = ocr_frame(ocr, mid, enhance=enhance)
            start_t = start_i / fps
            end_t = (end_i + 1) / fps
            if text:
                raw_cues.append(Cue(start=start_t, end=end_t, text=text))
            if progress_cb:
                progress_cb(n, total, "ocr")

        def norm(t: str) -> str:
            return t.replace(" ", "")

        merged: list[Cue] = []
        for c in raw_cues:
            if merged and norm(merged[-1].text) == norm(c.text) and c.start - merged[-1].end < 1.0:
                merged[-1].end = c.end
            else:
                merged.append(c)

        for c in merged:
            if c.end - c.start < MIN_CUE_DURATION:
                c.end = c.start + MIN_CUE_DURATION

        log(f"Done — {len(merged)} caption lines captured.")
        return merged
    finally:
        if keep_frames:
            log(f"Kept extracted frames in {frames_dir}")
        else:
            shutil.rmtree(frames_dir, ignore_errors=True)
