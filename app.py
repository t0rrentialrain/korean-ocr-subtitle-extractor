"""
Korean OCR Subtitle Extractor — desktop app.

Open a video, drag a box around the burned-in caption area on a preview
frame, click Run, get a timed .srt. No browser, no Python knowledge needed
to use it — see README.md for how to package this into a standalone .exe.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import ocr_core

BG = "#0e0e16"
PANEL = "#15151f"
BORDER = "#23232f"
FG = "#eee"
MUTED = "#a8a8bd"
ACCENT = "#3568d4"
ACCENT_HOVER = "#4477e6"
DANGER = "#c0392b"

CANVAS_MAX_W = 760
CANVAS_MAX_H = 420


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Korean OCR Subtitle Extractor")
        self.configure(bg=BG)
        self.geometry("820x760")
        self.minsize(760, 700)

        self._style()

        self.video_path: str | None = None
        self.duration: float = 0.0
        self.frame_w = 0
        self.frame_h = 0
        self.preview_full: Image.Image | None = None
        self.preview_photo = None
        self.crop_photo = None
        self.canvas_scale = 1.0
        self.region: tuple[float, float, float, float] | None = None
        self.drag_start = None
        self.rect_id = None

        self.msg_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.cues: list[ocr_core.Cue] = []

        self._build_ui()
        self.after(100, self._poll_queue)

    # ── styling ──────────────────────────────────────────────────────────────

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=PANEL, foreground=FG, font=("Segoe UI", 10))
        style.configure("Heading.TLabel", background=BG, foreground=FG, font=("Segoe UI", 15, "bold"))
        style.configure("TButton", background="#2b2b3d", foreground="#fff", borderwidth=0,
                         focusthickness=0, padding=8, font=("Segoe UI", 9))
        style.map("TButton", background=[("active", "#38384f"), ("disabled", "#1c1c28")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#fff", padding=10,
                         font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", "#26314f")])
        style.configure("Danger.TButton", background=DANGER, foreground="#fff", padding=8)
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.configure("TSpinbox", fieldbackground="#1c1c28", background="#1c1c28", foreground=FG)
        style.configure("Horizontal.TScale", background=BG)
        style.configure("TProgressbar", background=ACCENT, troughcolor="#1c1c28")

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 16, "pady": 8}

        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        ttk.Label(header, text="🇰🇷 Korean OCR Subtitle Extractor", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(header, text="Extract burned-in Korean captions from a video into a timed .srt file.",
                  style="Muted.TLabel").pack(anchor="w")

        # Step 1: open video
        step1 = ttk.Frame(self)
        step1.pack(fill="x", **pad)
        ttk.Button(step1, text="📂 Open Video…", command=self.open_video).pack(side="left")
        self.video_label = ttk.Label(step1, text="No video selected", style="Muted.TLabel")
        self.video_label.pack(side="left", padx=12)

        # Step 2: timestamp + grab preview
        step2 = ttk.Frame(self)
        step2.pack(fill="x", **pad)
        ttk.Label(step2, text="Preview timestamp:").pack(side="left")
        self.timestamp_var = tk.DoubleVar(value=30.0)
        self.timestamp_scale = ttk.Scale(step2, from_=0, to=100, variable=self.timestamp_var,
                                          orient="horizontal", length=300)
        self.timestamp_scale.pack(side="left", padx=8)
        self.timestamp_readout = ttk.Label(step2, text="0:30", style="Muted.TLabel")
        self.timestamp_readout.pack(side="left", padx=4)
        self.timestamp_var.trace_add("write", self._update_timestamp_readout)
        self.grab_btn = ttk.Button(step2, text="🖼 Grab Preview Frame", command=self.grab_preview, state="disabled")
        self.grab_btn.pack(side="left", padx=8)

        # Canvas for drag-select
        canvas_frame = ttk.Frame(self, style="Panel.TFrame")
        canvas_frame.pack(fill="x", padx=16, pady=8)
        ttk.Label(canvas_frame, text="  Drag a box tightly around the caption text:",
                  style="Panel.TLabel").pack(anchor="w", pady=(6, 0))
        self.canvas = tk.Canvas(canvas_frame, width=CANVAS_MAX_W, height=CANVAS_MAX_H,
                                 bg="#000", highlightthickness=0)
        self.canvas.pack(padx=8, pady=8)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas_placeholder = self.canvas.create_text(
            CANVAS_MAX_W // 2, CANVAS_MAX_H // 2,
            text="Open a video and grab a preview frame to begin",
            fill=MUTED, font=("Segoe UI", 11),
        )

        crop_row = ttk.Frame(self)
        crop_row.pack(fill="x", padx=16)
        ttk.Label(crop_row, text="Crop preview:", style="Muted.TLabel").pack(side="left")
        self.crop_preview_label = tk.Label(crop_row, bg=BG)
        self.crop_preview_label.pack(side="left", padx=8)
        self.region_label = ttk.Label(crop_row, text="Region: not set", style="Muted.TLabel")
        self.region_label.pack(side="left", padx=12)

        # Options
        opts = ttk.Frame(self)
        opts.pack(fill="x", **pad)
        self.enhance_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Enhance light-colored text (white/yellow captions on a dark background)",
                         variable=self.enhance_var).pack(side="left")
        ttk.Label(opts, text="   FPS:").pack(side="left")
        self.fps_var = tk.StringVar(value="3")
        ttk.Spinbox(opts, from_=1, to=10, textvariable=self.fps_var, width=4).pack(side="left")

        # Run row
        run_row = ttk.Frame(self)
        run_row.pack(fill="x", **pad)
        self.run_btn = ttk.Button(run_row, text="▶ Run", style="Accent.TButton",
                                   command=self.run_clicked, state="disabled")
        self.run_btn.pack(side="left")
        self.cancel_btn = ttk.Button(run_row, text="✕ Cancel", style="Danger.TButton",
                                      command=self.cancel_clicked, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.save_btn = ttk.Button(run_row, text="💾 Save .srt As…", command=self.save_as, state="disabled")
        self.save_btn.pack(side="left", padx=8)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=16, pady=(0, 8))

        # Log
        log_frame = ttk.Frame(self, style="Panel.TFrame")
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.log_text = tk.Text(log_frame, bg=PANEL, fg=FG, insertbackground=FG,
                                 relief="flat", font=("Consolas", 9), wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.configure(state="disabled")

    # ── step 1: open video ──────────────────────────────────────────────────

    def open_video(self):
        path = filedialog.askopenfilename(
            title="Choose a video",
            filetypes=[("Video files", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.duration = ocr_core.probe_duration(path)
            self.frame_w, self.frame_h = ocr_core.probe_dims(path)
        except Exception as e:
            messagebox.showerror("Couldn't read video", str(e))
            return

        self.video_path = path
        self.video_label.configure(text=Path(path).name)
        self.timestamp_scale.configure(to=max(1, self.duration))
        self.timestamp_var.set(min(30.0, self.duration / 2))
        self.grab_btn.configure(state="normal")
        self.region = None
        self.region_label.configure(text="Region: not set")
        self.run_btn.configure(state="disabled")
        self._log(f"Loaded {Path(path).name} — {self.frame_w}x{self.frame_h}, {self.duration:.0f}s")

    def _update_timestamp_readout(self, *_):
        t = self.timestamp_var.get()
        m, s = divmod(int(t), 60)
        self.timestamp_readout.configure(text=f"{m}:{s:02d}")

    # ── step 2: grab + display preview frame ────────────────────────────────

    def grab_preview(self):
        if not self.video_path:
            return
        tmp_path = str(Path.home() / "AppData" / "Local" / "Temp" / "ocr_app_preview.png") \
            if (Path.home() / "AppData").exists() else "/tmp/ocr_app_preview.png"
        try:
            ocr_core.extract_preview_frame(self.video_path, self.timestamp_var.get(), tmp_path)
            self.preview_full = Image.open(tmp_path).convert("RGB")
        except Exception as e:
            messagebox.showerror("Couldn't grab frame", str(e))
            return

        scale = min(CANVAS_MAX_W / self.preview_full.width, CANVAS_MAX_H / self.preview_full.height, 1.0)
        self.canvas_scale = scale
        disp_w, disp_h = round(self.preview_full.width * scale), round(self.preview_full.height * scale)
        disp_img = self.preview_full.resize((disp_w, disp_h))
        self.preview_photo = ImageTk.PhotoImage(disp_img)

        self.canvas.delete("all")
        self.canvas.configure(width=disp_w, height=disp_h)
        self.canvas.create_image(0, 0, anchor="nw", image=self.preview_photo)
        self.rect_id = None

        # Re-draw the previous region (if any) as a starting point
        if self.region:
            self._draw_region_rect(self.region)
        self._log("Preview frame loaded — drag a box around the caption text.")

    # ── drag-to-select crop region ───────────────────────────────────────────

    def _on_press(self, event):
        if self.preview_photo is None:
            return
        self.drag_start = (event.x, event.y)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                      outline="#ff2828", width=2)

    def _on_drag(self, event):
        if self.drag_start is None or self.rect_id is None:
            return
        x0, y0 = self.drag_start
        self.canvas.coords(self.rect_id, x0, y0, event.x, event.y)

    def _on_release(self, event):
        if self.drag_start is None:
            return
        x0, y0 = self.drag_start
        x1, y1 = event.x, event.y
        self.drag_start = None
        cx0, cx1 = sorted((max(0, x0), max(0, x1)))
        cy0, cy1 = sorted((max(0, y0), max(0, y1)))
        if cx1 - cx0 < 8 or cy1 - cy0 < 8:
            self._log("Box too small — try dragging a larger area.")
            return

        # canvas px -> original-frame fractions
        fx0 = (cx0 / self.canvas_scale) / self.preview_full.width
        fy0 = (cy0 / self.canvas_scale) / self.preview_full.height
        fw = ((cx1 - cx0) / self.canvas_scale) / self.preview_full.width
        fh = ((cy1 - cy0) / self.canvas_scale) / self.preview_full.height
        self.region = (fx0, fy0, fw, fh)
        self.region_label.configure(text=f"Region: x={fx0:.3f} y={fy0:.3f} w={fw:.3f} h={fh:.3f}")
        self._update_crop_preview()
        self.run_btn.configure(state="normal")

    def _draw_region_rect(self, region):
        x, y, w, h = region
        x0 = x * self.preview_full.width * self.canvas_scale
        y0 = y * self.preview_full.height * self.canvas_scale
        x1 = (x + w) * self.preview_full.width * self.canvas_scale
        y1 = (y + h) * self.preview_full.height * self.canvas_scale
        self.rect_id = self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ff2828", width=2)
        self._update_crop_preview()

    def _update_crop_preview(self):
        if not self.region or not self.preview_full:
            return
        x, y, w, h = ocr_core.region_to_px(self.region, self.preview_full.width, self.preview_full.height)
        if w <= 0 or h <= 0:
            return
        crop = self.preview_full.crop((x, y, x + w, y + h))
        target_h = 80
        scale = target_h / max(1, crop.height)
        crop = crop.resize((max(1, round(crop.width * scale)), target_h))
        self.crop_photo = ImageTk.PhotoImage(crop)
        self.crop_preview_label.configure(image=self.crop_photo)

    # ── run pipeline ─────────────────────────────────────────────────────────

    def run_clicked(self):
        if not self.video_path or not self.region:
            return
        try:
            fps = float(self.fps_var.get())
        except ValueError:
            fps = 3.0

        self.cancel_event.clear()
        self.cues = []
        self.run_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.save_btn.configure(state="disabled")
        self.progress.configure(value=0, maximum=100)
        self._clear_log()

        self.worker = threading.Thread(
            target=self._worker_main,
            args=(self.video_path, self.region, fps, self.enhance_var.get()),
            daemon=True,
        )
        self.worker.start()

    def _worker_main(self, video, region, fps, enhance):
        def log_cb(msg):
            self.msg_queue.put(("log", msg))

        def progress_cb(current, total, stage):
            self.msg_queue.put(("progress", current, total))

        def cancel_check():
            return self.cancel_event.is_set()

        try:
            cues = ocr_core.run_pipeline(
                video, region, fps=fps, enhance=enhance,
                progress_cb=progress_cb, log_cb=log_cb, cancel_check=cancel_check,
            )
            self.msg_queue.put(("done", cues, None))
        except ocr_core.Cancelled:
            self.msg_queue.put(("cancelled", None, None))
        except Exception as e:
            self.msg_queue.put(("error", None, str(e)))

    def cancel_clicked(self):
        self.cancel_event.set()
        self._log("Cancelling ...")

    def _poll_queue(self):
        try:
            while True:
                kind, *rest = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(rest[0])
                elif kind == "progress":
                    current, total = rest
                    self.progress.configure(maximum=max(1, total), value=current)
                elif kind == "done":
                    cues, _ = rest
                    self.cues = cues
                    self._log(f"\n=== {len(cues)} cues ===")
                    for i, c in enumerate(cues, 1):
                        self._log(f"{i:4d}  {c.start:8.2f}-{c.end:8.2f}  {c.text}")
                    self._finish_run(success=True)
                elif kind == "cancelled":
                    self._log("Cancelled.")
                    self._finish_run(success=False)
                elif kind == "error":
                    _, err = rest
                    self._log(f"ERROR: {err}")
                    messagebox.showerror("OCR run failed", err)
                    self._finish_run(success=False)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _finish_run(self, success: bool):
        self.run_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.save_btn.configure(state="normal" if (success and self.cues) else "disabled")

    def save_as(self):
        if not self.cues:
            return
        default_name = Path(self.video_path).stem + ".srt" if self.video_path else "captions.srt"
        path = filedialog.asksaveasfilename(
            title="Save subtitle file", defaultextension=".srt",
            initialfile=default_name, filetypes=[("SubRip subtitle", "*.srt")],
        )
        if not path:
            return
        ocr_core.write_srt(self.cues, path)
        self._log(f"Saved to {path}")
        messagebox.showinfo("Saved", f"Saved {len(self.cues)} lines to:\n{path}")

    # ── log helpers ──────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            messagebox.showerror("Korean OCR Subtitle Extractor — failed to start", str(e))
        except Exception:
            pass
