"""Window for the two AVIF profiles."""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from image_compactor import __version__
from image_compactor.encode import (
    EncodeError,
    encode_image,
    encoder_thread_budget,
    find_avifenc,
    worker_plan,
)
from image_compactor.facts import SUPPORTED_SUFFIXES, PhotoFacts, inspect_image
from image_compactor.suggest import (
    BACKUP,
    KEEP,
    PROFILES,
    Decision,
    decide,
    quality_to_crf,
)

PHONE_LABELS = {
    "auto": "Auto detect",
    "budget": "High megapixel",
    "sharp": "High detail",
}
CLASS_LABELS = {
    "auto": "Auto detect",
    "budget": "High megapixel",
    "sharp": "High detail",
    "unknown": "Unknown",
}
PROFILE_LABELS = {KEEP: "High quality", BACKUP: "Small copy"}
RESOLUTION_LABELS = {
    "off": "Original size",
    "suggested": "Suggested",
    "percent": "Custom scale",
}
DIALOG_TYPES = (
    ("Images", "*.jpg *.jpeg *.jfif *.png *.webp *.tif *.tiff *.bmp *.gif"),
    ("JPEG", "*.jpg *.jpeg *.jfif"),
    ("PNG", "*.png"),
    ("All files", "*.*"),
)
MAX_LISTED_FILES = 5000


def describe(facts: PhotoFacts, decision: Decision) -> str:
    make = facts.make.strip()
    model = facts.model.strip()
    camera = model if model.lower().startswith(make.lower()) else f"{make} {model}".strip()
    fmt = facts.format or facts.path.suffix.lstrip(".").upper() or "image"
    lines = [camera or facts.path.name]
    if camera:
        lines.append(f"{facts.path.name}  {fmt}")
    else:
        lines[0] = f"{facts.path.name}  {fmt}"
    lines.append(f"{facts.width} x {facts.height}, {facts.megapixels:.1f} MP")
    if facts.lens:
        lines.append(facts.lens)
    exposure = []
    if facts.iso is not None:
        exposure.append(f"ISO {facts.iso}")
    if facts.f_number is not None:
        exposure.append(f"f/{facts.f_number:g}")
    if facts.focal_length_mm is not None:
        focal = f"{facts.focal_length_mm:g} mm"
        if facts.focal_35mm is not None:
            focal += f" ({facts.focal_35mm} mm equiv)"
        exposure.append(focal)
    if exposure:
        lines.append(", ".join(exposure))
    lines.append(f"ICC: {facts.icc_name or 'none'}")
    if facts.exif_color_space is None:
        lines.append("EXIF ColorSpace: absent")
    else:
        lines.append(f"EXIF ColorSpace: {facts.exif_color_space}")
    if facts.remosaic:
        scene = f" Scene {facts.scene_mode}." if facts.scene_mode else ""
        lines.append(f"Hardware remosaic.{scene}")
    elif facts.scene_mode:
        lines.append(f"Scene {facts.scene_mode}.")
    if facts.sensor_hits:
        lines.append("Header strings: " + ", ".join(facts.sensor_hits) + ".")
    if facts.vendor_json:
        bits = ", ".join(f"{key}={value}" for key, value in facts.vendor_json.items())
        lines.append(f"Maker note: {bits}.")
    if facts.gain_map is not None:
        lines.append(
            f"HDR gain map, {facts.gain_map.length} bytes, "
            f"file offset {facts.gain_map.offset}."
        )
        for key, value in facts.gain_map.fields.items():
            lines.append(f"  {key} = {value}")
        headroom = _headroom_line(facts.gain_map.fields)
        if headroom:
            lines.append(headroom)
    try:
        lines.append(f"File size: {_format_bytes(facts.path.stat().st_size)}")
    except OSError:
        pass
    lines.append("")
    class_label = CLASS_LABELS.get(decision.phone_class, decision.phone_class)
    lines.append(f"Source class: {class_label}")
    lines.append(
        f"Output: {decision.width} x {decision.height}"
        + (
            f", scale {decision.scale:.3f}"
            if decision.scale < 0.999
            else ", full resolution"
        )
    )
    lines.extend(decision.lines)
    return "\n".join(lines)


def _headroom_line(fields: dict[str, str]) -> str:
    try:
        gain_max = float(fields["GainMapMax"])
        offset_sdr = float(fields.get("OffsetSDR", "0") or 0)
        offset_hdr = float(fields.get("OffsetHDR", "0") or 0)
    except (KeyError, ValueError):
        return ""
    peak = 2.0 ** gain_max
    if offset_sdr == 0 and offset_hdr == 0:
        return (
            f"At full display headroom, a map value of 1 multiplies linear light by {peak:.2f}."
        )
    return (
        f"GainMapMax {gain_max:g} is a linear ratio of {peak:.2f} at map value 1, "
        "before the offsets."
    )


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _short_path(path: Path, limit: int = 46) -> str:
    text = str(path)
    if len(text) <= limit:
        return text
    return "..." + text[-(limit - 3) :]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Image Compactor {__version__}")
        self.root.minsize(1000, 720)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.style = ttk.Style(root)
        try:
            if "vista" in self.style.theme_names():
                self.style.theme_use("vista")
            self.style.configure("Muted.TLabel", foreground="#5f6368")
            self.style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        except tk.TclError:
            pass
        self.normal_color = self.style.lookup("TLabel", "foreground") or "#1a1a1a"
        self.error_color = "#b3261e"

        self.paths: list[Path] = []
        self.known: set[str] = set()
        self.cache: dict[Path, tuple] = {}
        self.cancel = threading.Event()
        self.executor: ThreadPoolExecutor | None = None
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.closing = False
        self.total = 0
        self.done = 0
        self.successes = 0
        self.failures = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.avifenc: Path | None = None
        self.encoder_override: Path | None = None
        self.suspend_refresh = False
        self.locked_widgets: list[tk.Widget] = []

        self.profile = tk.StringVar(value=KEEP)
        self.phone = tk.StringVar(value="auto")
        self.speed = tk.IntVar(value=PROFILES[KEEP].speed)
        self.quality = tk.DoubleVar(value=PROFILES[KEEP].quality)
        self.bit_depth = tk.IntVar(value=PROFILES[KEEP].bit_depth)
        self.resolution = tk.StringVar(value=PROFILES[KEEP].downscale)
        self.percent = tk.DoubleVar(value=75)
        self.tag_p3 = tk.BooleanVar(value=True)
        self.output_mode = tk.StringVar(value="beside")
        self.output_dir = tk.StringVar(value="")
        self.quality_text = tk.StringVar(value="")
        self.output_size_text = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Ready")
        self.progress_text = tk.StringVar(value="")
        self.encoder_text = tk.StringVar(value="")
        self.count_text = tk.StringVar(value="0 photos")

        self._build()
        self._bind_traces()
        self.apply_profile()
        self._check_encoder()

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(14, 12, 14, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Image Compactor", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text=f"Version {__version__}   JPEG, PNG, WebP, TIFF, BMP, GIF to AVIF",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        encoder_row = ttk.Frame(header)
        encoder_row.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(encoder_row, text="Encoder", style="Muted.TLabel").grid(
            row=0, column=0, sticky="e"
        )
        self.encoder_label = ttk.Label(
            encoder_row, textvariable=self.encoder_text, width=46, anchor="e"
        )
        self.encoder_label.grid(row=0, column=1, sticky="e", padx=(6, 0))
        self.encoder_button = ttk.Button(
            encoder_row, text="Browse...", command=self.choose_encoder
        )
        self.encoder_button.grid(row=0, column=2, padx=(6, 0))
        self.locked_widgets.append(self.encoder_button)

        body = ttk.Frame(self.root, padding=(14, 6, 14, 6))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        files = ttk.LabelFrame(left, text="Photos", padding=8)
        files.grid(row=0, column=0, sticky="nsew")
        files.columnconfigure(0, weight=1)
        files.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(files)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.add_files_button = ttk.Button(
            toolbar, text="Add files", command=self.add_files
        )
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(
            toolbar, text="Add folder", command=self.add_folder
        )
        self.add_folder_button.pack(side="left", padx=6)
        self.remove_button = ttk.Button(
            toolbar, text="Remove", command=self.remove_selected
        )
        self.remove_button.pack(side="left")
        self.clear_button = ttk.Button(
            toolbar, text="Clear", command=self.clear_list
        )
        self.clear_button.pack(side="left", padx=6)
        self.locked_widgets.extend(
            [
                self.add_files_button,
                self.add_folder_button,
                self.remove_button,
                self.clear_button,
            ]
        )
        ttk.Label(files, textvariable=self.count_text, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(6, 4)
        )
        self.tree = ttk.Treeview(
            files,
            columns=("name", "size", "status"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("name", text="File")
        self.tree.heading("size", text="Size")
        self.tree.heading("status", text="Status")
        self.tree.column("name", width=220, minwidth=160, stretch=True)
        self.tree.column("size", width=75, minwidth=60, anchor="e", stretch=False)
        self.tree.column("status", width=110, minwidth=90, anchor="w", stretch=False)
        self.tree.grid(row=2, column=0, sticky="nsew")
        file_scroll = ttk.Scrollbar(files, orient="vertical", command=self.tree.yview)
        file_scroll.grid(row=2, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=file_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.refresh())
        self.tree.tag_configure("queued", foreground="#5f6368")
        self.tree.tag_configure("active", foreground="#0b57d0")
        self.tree.tag_configure("done", foreground="#16794a")
        self.tree.tag_configure("failed", foreground=self.error_color)
        self.tree.tag_configure("skipped", foreground="#5f6368")

        settings = ttk.LabelFrame(right, text="Output settings", padding=8)
        settings.grid(row=0, column=0, sticky="new")
        settings.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(settings, text="Profile").grid(
            row=row, column=0, sticky="nw", pady=(0, 4)
        )
        profile_row = ttk.Frame(settings)
        profile_row.grid(row=row, column=1, sticky="w", pady=(0, 4))
        for key in (KEEP, BACKUP):
            button = ttk.Radiobutton(
                profile_row,
                text=PROFILE_LABELS[key],
                value=key,
                variable=self.profile,
                command=self.apply_profile,
            )
            button.pack(side="left", padx=(0, 10))
            self.locked_widgets.append(button)
        row += 1
        ttk.Label(
            settings,
            text="High quality: 10-bit, preset 4. Small copy: 8-bit, preset 5 with a suggested resize.",
            style="Muted.TLabel",
            wraplength=370,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1
        ttk.Separator(settings, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )
        row += 1

        ttk.Label(settings, text="Source class").grid(
            row=row, column=0, sticky="nw", pady=(0, 4)
        )
        class_row = ttk.Frame(settings)
        class_row.grid(row=row, column=1, sticky="w", pady=(0, 4))
        for key, label in PHONE_LABELS.items():
            button = ttk.Radiobutton(
                class_row, text=label, value=key, variable=self.phone
            )
            button.pack(side="left", padx=(0, 8))
            self.locked_widgets.append(button)
        row += 1
        ttk.Label(
            settings,
            text="Auto detect reads the capture log and pixel count.",
            style="Muted.TLabel",
            wraplength=520,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1
        ttk.Separator(settings, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )
        row += 1

        ttk.Label(settings, text="Resolution").grid(
            row=row, column=0, sticky="nw", pady=(0, 4)
        )
        resolution_row = ttk.Frame(settings)
        resolution_row.grid(row=row, column=1, sticky="w", pady=(0, 4))
        for key, label in RESOLUTION_LABELS.items():
            button = ttk.Radiobutton(
                resolution_row, text=label, value=key, variable=self.resolution
            )
            button.pack(side="left", padx=(0, 8))
            self.locked_widgets.append(button)
        row += 1
        scale_row = ttk.Frame(settings)
        scale_row.grid(row=row, column=1, sticky="w", pady=(0, 4))
        self.percent_spin = ttk.Spinbox(
            scale_row,
            from_=5,
            to=100,
            increment=5,
            textvariable=self.percent,
            width=6,
        )
        self.percent_spin.pack(side="left")
        ttk.Label(scale_row, text="% of each side").pack(side="left", padx=(6, 0))
        self.locked_widgets.append(self.percent_spin)
        row += 1
        ttk.Label(
            settings,
            text="Suggested applies the size rules to large or remosaic photos.",
            style="Muted.TLabel",
            wraplength=520,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        ttk.Label(settings, text="Output size").grid(
            row=row, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(settings, textvariable=self.output_size_text).grid(
            row=row, column=1, sticky="w", pady=(0, 8)
        )
        row += 1
        ttk.Separator(settings, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )
        row += 1

        ttk.Label(settings, text="Quality").grid(
            row=row, column=0, sticky="w", pady=(0, 4)
        )
        quality_row = ttk.Frame(settings)
        quality_row.grid(row=row, column=1, sticky="ew", pady=(0, 4))
        self.quality_scale = ttk.Scale(
            quality_row,
            from_=0,
            to=100,
            variable=self.quality,
            orient="horizontal",
        )
        self.quality_scale.pack(side="left", fill="x", expand=True)
        ttk.Label(quality_row, textvariable=self.quality_text, width=20).pack(
            side="left", padx=(8, 0)
        )
        self.locked_widgets.append(self.quality_scale)
        row += 1

        ttk.Label(settings, text="SVT preset").grid(
            row=row, column=0, sticky="w", pady=(0, 4)
        )
        preset_row = ttk.Frame(settings)
        preset_row.grid(row=row, column=1, sticky="w", pady=(0, 4))
        self.speed_spin = ttk.Spinbox(
            preset_row, from_=2, to=5, textvariable=self.speed, width=5
        )
        self.speed_spin.pack(side="left")
        ttk.Label(
            preset_row, text="2 slowest, 5 fastest", style="Muted.TLabel"
        ).pack(side="left", padx=(6, 0))
        self.locked_widgets.append(self.speed_spin)
        row += 1

        ttk.Label(settings, text="Bit depth").grid(
            row=row, column=0, sticky="w", pady=(0, 4)
        )
        depth_row = ttk.Frame(settings)
        depth_row.grid(row=row, column=1, sticky="w", pady=(0, 4))
        for value, label in ((8, "8-bit"), (10, "10-bit")):
            button = ttk.Radiobutton(
                depth_row, text=label, value=value, variable=self.bit_depth
            )
            button.pack(side="left", padx=(0, 8))
            self.locked_widgets.append(button)
        row += 1

        self.p3_check = ttk.Checkbutton(
            settings,
            text="Tag Display P3 when the source profile is P3",
            variable=self.tag_p3,
        )
        self.p3_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 8))
        self.locked_widgets.append(self.p3_check)
        row += 1
        ttk.Separator(settings, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )
        row += 1

        ttk.Label(settings, text="Save to").grid(
            row=row, column=0, sticky="nw", pady=(0, 4)
        )
        output_row = ttk.Frame(settings)
        output_row.grid(row=row, column=1, sticky="w", pady=(0, 4))
        for value, label in (("beside", "Beside source"), ("folder", "Folder")):
            button = ttk.Radiobutton(
                output_row, text=label, value=value, variable=self.output_mode
            )
            button.pack(side="left", padx=(0, 10))
            self.locked_widgets.append(button)
        row += 1
        folder_row = ttk.Frame(settings)
        folder_row.grid(row=row, column=1, sticky="ew", pady=(0, 2))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.output_dir)
        self.folder_entry.grid(row=0, column=0, sticky="ew")
        self.folder_button = ttk.Button(
            folder_row, text="Browse...", command=self.choose_folder
        )
        self.folder_button.grid(row=0, column=1, padx=(6, 0))
        self.locked_widgets.extend([self.folder_entry, self.folder_button])

        details_frame = ttk.LabelFrame(left, text="Selected photo", padding=8)
        details_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        self.details = tk.Text(
            details_frame,
            wrap="word",
            height=14,
            relief="flat",
            borderwidth=0,
            font="TkFixedFont",
            padx=6,
            pady=6,
        )
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll = ttk.Scrollbar(
            details_frame, orient="vertical", command=self.details.yview
        )
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)
        self._set_text(self.details, "Add photos, then select one to inspect.")

        log_frame = ttk.LabelFrame(right, text="Activity", padding=(10, 6))
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_box = tk.Text(
            log_frame,
            height=5,
            wrap="word",
            state="disabled",
            font="TkFixedFont",
            relief="flat",
            borderwidth=0,
            padx=6,
            pady=4,
        )
        self.log_box.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_box.yview
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_box.configure(yscrollcommand=log_scroll.set)

        footer = ttk.Frame(self.root, padding=(14, 0, 14, 12))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        progress_row = ttk.Frame(footer)
        progress_row.grid(row=0, column=0, sticky="ew")
        progress_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            progress_row, mode="determinate", maximum=1, value=0
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            progress_row, textvariable=self.progress_text, width=12, anchor="e"
        ).grid(row=0, column=1, padx=(8, 0))
        action_row = ttk.Frame(footer)
        action_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        ttk.Label(action_row, textvariable=self.status_text).grid(
            row=0, column=0, sticky="w"
        )
        self.stop_button = ttk.Button(
            action_row, text="Stop", command=self.stop, state="disabled"
        )
        self.stop_button.grid(row=0, column=1, padx=(8, 0))
        self.encode_button = ttk.Button(
            action_row, text="Convert to AVIF", command=self.encode_list
        )
        self.encode_button.grid(row=0, column=2)

    def _bind_traces(self) -> None:
        for var in (
            self.phone,
            self.speed,
            self.quality,
            self.bit_depth,
            self.resolution,
            self.percent,
            self.tag_p3,
            self.output_mode,
        ):
            var.trace_add("write", self._settings_changed)

    def _settings_changed(self, *_args) -> None:
        if not self.suspend_refresh:
            self.refresh()

    def _check_encoder(self) -> None:
        try:
            path = self.encoder_override or find_avifenc()
            if not Path(path).is_file():
                raise EncodeError(f"{path} is not a file")
        except EncodeError as exc:
            self.avifenc = None
            self.encoder_text.set("avifenc.exe not found")
            self.encoder_label.configure(foreground=self.error_color)
            self.log(str(exc))
            return
        self.avifenc = Path(path)
        self.encoder_text.set(_short_path(self.avifenc))
        self.encoder_label.configure(foreground=self.normal_color)
        self.log(f"Encoder: {self.avifenc}")

    def apply_profile(self) -> None:
        defaults = PROFILES[self.profile.get()]
        self.suspend_refresh = True
        try:
            self.speed.set(defaults.speed)
            self.quality.set(defaults.quality)
            self.bit_depth.set(defaults.bit_depth)
            self.resolution.set(defaults.downscale)
        finally:
            self.suspend_refresh = False
        self.refresh()

    def add_files(self) -> None:
        names = filedialog.askopenfilenames(title="Add photos", filetypes=DIALOG_TYPES)
        if names:
            self.add_paths([Path(name) for name in names])

    def add_folder(self) -> None:
        name = filedialog.askdirectory(title="Folder of photos")
        if not name:
            return
        found = _image_paths(Path(name))
        self.add_paths(found)
        if len(found) >= MAX_LISTED_FILES:
            self.log(f"Stopped listing at {MAX_LISTED_FILES} photos.")

    def add_paths(self, paths: list[Path]) -> None:
        added = 0
        skipped = 0
        duplicates = 0
        first_added: Path | None = None
        for path in paths:
            path = Path(path)
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                skipped += 1
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key in self.known:
                duplicates += 1
                continue
            try:
                if not path.is_file():
                    skipped += 1
                    continue
                size = path.stat().st_size
            except OSError as exc:
                self.log(f"{path.name}: {exc}")
                skipped += 1
                continue
            self.paths.append(path)
            self.known.add(key)
            self.tree.insert(
                "",
                "end",
                iid=str(path),
                values=(path.name, _format_bytes(size), "Ready"),
            )
            if first_added is None:
                first_added = path
            added += 1
        if added and not self.tree.selection():
            self.tree.selection_set(str(first_added))
        self._update_count()
        self.refresh()
        parts = []
        if added:
            parts.append(f"Added {added} photo" + ("s" if added != 1 else ""))
        if duplicates:
            parts.append(f"{duplicates} duplicate" + ("s" if duplicates != 1 else ""))
        if skipped:
            parts.append(f"{skipped} skipped")
        if parts:
            self.log(", ".join(parts) + ".")

    def remove_selected(self) -> None:
        if self.busy:
            return
        selected = self.tree.selection()
        if not selected:
            return
        index = self.tree.index(selected[0])
        for iid in selected:
            self.tree.delete(iid)
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[min(index, len(children) - 1)])
        self._resync()
        self.refresh()

    def clear_list(self) -> None:
        if self.busy:
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.paths = []
        self.known = set()
        self._update_count()
        self.refresh()

    def _resync(self) -> None:
        self.paths = [Path(iid) for iid in self.tree.get_children()]
        self.known = {
            os.path.normcase(os.path.abspath(path)) for path in self.paths
        }
        self._update_count()

    def _update_count(self) -> None:
        count = len(self.paths)
        total = 0
        for path in self.paths:
            try:
                total += path.stat().st_size
            except OSError:
                pass
        label = f"{count} photo" + ("" if count == 1 else "s")
        if total:
            label += f"   {_format_bytes(total)}"
        self.count_text.set(label)

    def choose_folder(self) -> None:
        name = filedialog.askdirectory(title="Folder for AVIF files")
        if not name:
            return
        self.output_dir.set(name)
        self.output_mode.set("folder")
        self.log(f"Output folder: {name}")

    def choose_encoder(self) -> None:
        name = filedialog.askopenfilename(
            title="Select avifenc.exe",
            filetypes=[
                ("avifenc", "avifenc.exe"),
                ("Programs", "*.exe"),
                ("All files", "*.*"),
            ],
        )
        if not name:
            return
        self.encoder_override = Path(name)
        self._check_encoder()

    def selected_path(self) -> Path | None:
        selected = self.tree.selection()
        return Path(selected[0]) if selected else None

    def current_decision(self, facts: PhotoFacts) -> Decision:
        return decide(
            facts,
            phone_override=self.phone.get(),
            speed=self._int(self.speed, PROFILES[KEEP].speed),
            quality=self._int(self.quality, PROFILES[KEEP].quality),
            bit_depth=self._int(self.bit_depth, 8),
            downscale=self.resolution.get(),
            percent=self._float(self.percent, 75),
            tag_p3=bool(self.tag_p3.get()),
        )

    def refresh(self) -> None:
        quality = self._int(self.quality, 0)
        self.quality_text.set(f"Quality {quality}   CRF {quality_to_crf(quality)}")
        self._update_resolution_state()
        self._update_output_state()
        path = self.selected_path()
        if path is None:
            self._set_text(self.details, "Add photos, then select one to inspect.")
            self.output_size_text.set("")
            return
        try:
            facts = self._facts(path)
            decision = self.current_decision(facts)
        except Exception as exc:
            self._set_text(self.details, f"{path.name}\n{exc}")
            self.output_size_text.set("")
            return
        self._set_text(self.details, describe(facts, decision))
        megapixels = decision.width * decision.height / 1_000_000
        self.output_size_text.set(
            f"{decision.width} x {decision.height}  ({megapixels:.1f} MP)"
        )

    def _facts(self, path: Path) -> PhotoFacts:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self.cache.get(path)
        if cached and cached[0] == key:
            return cached[1]
        facts = inspect_image(path)
        self.cache[path] = (key, facts)
        return facts

    def _update_resolution_state(self) -> None:
        enabled = not self.busy and self.resolution.get() == "percent"
        self.percent_spin.configure(state="normal" if enabled else "disabled")

    def _update_output_state(self) -> None:
        enabled = not self.busy and self.output_mode.get() == "folder"
        state = "normal" if enabled else "disabled"
        self.folder_entry.configure(state=state)
        self.folder_button.configure(state=state)

    def encode_list(self) -> None:
        if self.busy:
            return
        if not self.paths:
            messagebox.showinfo("Image Compactor", "Add at least one photo.")
            return
        folder = self.output_dir.get().strip()
        if self.output_mode.get() == "folder":
            if not folder:
                messagebox.showinfo(
                    "Image Compactor", "Choose a folder, or save beside each source."
                )
                return
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(
                    "Image Compactor", f"Cannot create {folder}:\n{exc}"
                )
                return
        if self.avifenc is None or not self.avifenc.is_file():
            self._check_encoder()
        if self.avifenc is None:
            messagebox.showerror(
                "Image Compactor",
                "avifenc.exe is not available. Choose it with Browse in the header.",
            )
            return

        jobs = list(self.paths)
        settings = self._snapshot()
        workers, thread_counts = worker_plan(len(jobs), encoder_thread_budget())
        self.cancel = threading.Event()
        self.total = len(jobs)
        self.done = 0
        self.successes = 0
        self.failures = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.progress.configure(maximum=len(jobs), value=0)
        self.progress_text.set(f"0 / {len(jobs)}")
        for path in jobs:
            self._set_status(path, "Queued", "queued")
        self._set_busy(True)
        noun = "photo" if len(jobs) == 1 else "photos"
        self.status_text.set(f"Converting {len(jobs)} {noun}...")
        thread_total = sum(thread_counts)
        self.log(
            f"Batch: {len(jobs)} photo{'s' if len(jobs) != 1 else ''}, "
            f"{workers} at a time, {thread_total} encoder thread"
            f"{'s' if thread_total != 1 else ''} total, below-normal priority."
        )
        thread_slots: queue.Queue = queue.Queue()
        for count in thread_counts:
            thread_slots.put(count)
        self.executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="avif"
        )
        for path in jobs:
            self.executor.submit(self._encode_one, path, settings, thread_slots)
        self.root.after(80, self._poll_events)

    def stop(self) -> None:
        if not self.busy:
            return
        self.cancel.set()
        self.stop_button.configure(state="disabled")
        self.status_text.set("Stopping the running encoders...")
        self.log("Stop requested.")

    def _snapshot(self) -> dict:
        return {
            "phone": self.phone.get(),
            "speed": self._int(self.speed, PROFILES[KEEP].speed),
            "quality": self._int(self.quality, PROFILES[KEEP].quality),
            "bit_depth": self._int(self.bit_depth, 8),
            "resolution": self.resolution.get(),
            "percent": self._float(self.percent, 75),
            "tag_p3": bool(self.tag_p3.get()),
            "output_mode": self.output_mode.get(),
            "output_dir": self.output_dir.get().strip(),
            "avifenc": self.avifenc,
        }

    def _encode_one(self, path: Path, settings: dict, thread_slots: queue.Queue) -> None:
        threads = thread_slots.get()
        try:
            if self.cancel.is_set():
                self._post("item", path, "Skipped", "skipped")
                return
            self._post("item", path, "Inspecting", "active")
            try:
                facts = inspect_image(path)
            except Exception as exc:
                if self.cancel.is_set():
                    self._post("item", path, "Stopped", "skipped")
                else:
                    self._post("item", path, "Failed", "failed")
                    self._post("log", f"{path.name}: {exc}")
                    self._post("failure")
                return
            decision = decide(
                facts,
                phone_override=settings["phone"],
                speed=settings["speed"],
                quality=settings["quality"],
                bit_depth=settings["bit_depth"],
                downscale=settings["resolution"],
                percent=settings["percent"],
                tag_p3=settings["tag_p3"],
            )
            dest_dir = (
                Path(settings["output_dir"])
                if settings["output_mode"] == "folder"
                else path.parent
            )
            self._post("item", path, "Converting", "active")
            result = encode_image(
                path,
                dest_dir,
                decision,
                avifenc=settings["avifenc"],
                threads=threads,
                cancel=self.cancel,
            )
            self._post("item", path, f"Done  {_format_bytes(result.bytes_out)}", "done")
            ratio = result.bytes_out / result.bytes_in * 100 if result.bytes_in else 0
            self._post(
                "log",
                f"{result.output.name}: {_format_bytes(result.bytes_in)} -> "
                f"{_format_bytes(result.bytes_out)} ({ratio:.0f}%)",
            )
            self._post("size", result.bytes_in, result.bytes_out)
            self._post("success")
        except Exception as exc:
            if self.cancel.is_set():
                self._post("item", path, "Stopped", "skipped")
                self._post("log", f"{path.name}: stopped")
            else:
                self._post("item", path, "Failed", "failed")
                self._post("log", f"{path.name}: {exc}")
                self._post("failure")
        finally:
            thread_slots.put(threads)
            self._post("task")

    def _post(self, kind: str, *args) -> None:
        self.events.put((kind, *args))

    def _poll_events(self) -> None:
        finished = False
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind, *args = event
            if kind == "log":
                self.log(args[0])
            elif kind == "item":
                self._set_status(*args)
            elif kind == "success":
                self.successes += 1
            elif kind == "failure":
                self.failures += 1
            elif kind == "size":
                self.bytes_in += args[0]
                self.bytes_out += args[1]
            elif kind == "task":
                self.done += 1
                self.progress.configure(value=self.done)
                self.progress_text.set(f"{self.done} / {self.total}")
                if self.done >= self.total:
                    finished = True
        if finished:
            self._finish_batch()
        elif self.busy:
            self.root.after(80, self._poll_events)

    def _set_status(self, path: Path, text: str, tag: str) -> None:
        iid = str(path)
        if not self.tree.exists(iid):
            return
        self.tree.set(iid, "status", text)
        self.tree.item(iid, tags=(tag,) if tag else ())

    def _finish_batch(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=False)
            self.executor = None
        self._set_busy(False)
        skipped = max(0, self.total - self.successes - self.failures)
        if self.cancel.is_set():
            summary = f"Stopped: {self.successes} converted"
            if self.failures:
                summary += f", {self.failures} failed"
            if skipped:
                summary += f", {skipped} skipped"
        else:
            summary = f"Finished: {self.successes} converted"
            if self.failures:
                summary += f", {self.failures} failed"
        summary += "."
        if self.successes and self.bytes_in:
            summary += (
                f" {_format_bytes(self.bytes_in)} -> {_format_bytes(self.bytes_out)}"
            )
            saved = self.bytes_in - self.bytes_out
            if saved > 0:
                summary += f" ({saved / self.bytes_in * 100:.0f}% smaller)"
            summary += "."
        self.status_text.set(summary)
        self.log(summary)
        if self.closing:
            self.root.destroy()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in self.locked_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        self.encode_button.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")
        self._update_resolution_state()
        self._update_output_state()

    def close(self) -> None:
        if self.closing:
            return
        if self.busy:
            if not messagebox.askyesno(
                "Image Compactor", "Stop the current batch and close?"
            ):
                return
            self.closing = True
            self.cancel.set()
            self.stop_button.configure(state="disabled")
            self.status_text.set("Stopping...")
            return
        self.root.destroy()

    def log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{stamp}] {text.rstrip()}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    @staticmethod
    def _int(var, default: int) -> int:
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return default

    @staticmethod
    def _float(var, default: float) -> float:
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            return default

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")


def _image_paths(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in sorted(filenames):
            if Path(name).suffix.lower() in SUPPORTED_SUFFIXES:
                found.append(Path(dirpath) / name)
                if len(found) >= MAX_LISTED_FILES:
                    return found
    return found


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
