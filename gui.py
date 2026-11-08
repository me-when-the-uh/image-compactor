"""Window for the AVIF profiles."""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    DND_FILES = None

from image_compactor import __version__
from image_compactor.encode import (
    EncodeError,
    encode_image,
    encoder_thread_budget,
    find_avifenc,
    physical_cores,
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

BG = "#3d3d3d"
HEADER_BG = "#333333"
PANEL_BG = "#2f2f2f"
FIELD_BG = "#252525"
FIELD_FG = "#f1f1f1"
TEXT = "#eeeeee"
MUTED = "#a8a8a8"
BORDER = "#444444"
ACCENT = "#229af7"
ACCENT_DARK = "#0079d6"
GREEN = "#21ba45"
GREEN_HOVER = "#2ecc55"
RED = "#db2828"
ERROR = "#ff6b6b"

FONT_UI = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Impact", 20)
FONT_MONO = ("Consolas", 9)

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


def _short_path(path: Path, limit: int = 52) -> str:
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
        self.root.configure(bg=BG)

        self.style = ttk.Style(root)
        self._configure_style()

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
        self.current_page = "convert"
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.pages: dict[str, ttk.Frame] = {}
        self.dnd_ready = False

        self.profile = tk.StringVar(value=KEEP)
        self.phone = tk.StringVar(value="auto")
        self.speed = tk.IntVar(value=PROFILES[KEEP].speed)
        self.quality = tk.IntVar(value=PROFILES[KEEP].quality)
        self.bit_depth = tk.IntVar(value=PROFILES[KEEP].bit_depth)
        self.resolution = tk.StringVar(value=PROFILES[KEEP].downscale)
        self.percent = tk.DoubleVar(value=75)
        self.tag_p3 = tk.BooleanVar(value=True)
        self.overwrite = tk.BooleanVar(value=False)
        self.output_mode = tk.StringVar(value="same")
        self.output_dir = tk.StringVar(value="")
        self.quality_text = tk.StringVar(value="")
        self.output_size_text = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Ready")
        self.progress_text = tk.StringVar(value="")
        self.encoder_text = tk.StringVar(value="")
        self.encoder_full_text = tk.StringVar(value="")
        self.count_text = tk.StringVar(value="0 photos")

        self._build()
        self._bind_traces()
        self.apply_profile()
        self._check_encoder()
        self._enable_dnd()
        self.show_page("convert")

    def _configure_style(self) -> None:
        style = self.style
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            ".",
            background=BG,
            foreground=TEXT,
            fieldbackground=FIELD_BG,
            font=FONT_UI,
        )
        style.configure("Page.TFrame", background=BG)
        style.configure("Header.TFrame", background=HEADER_BG)
        style.configure("Panel.TFrame", background=PANEL_BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
        style.configure(
            "PanelMuted.TLabel",
            background=PANEL_BG,
            foreground=MUTED,
            font=FONT_SMALL,
        )
        style.configure(
            "DropActive.TLabel",
            background=PANEL_BG,
            foreground=ACCENT,
            font=FONT_BOLD,
        )
        style.configure("Setting.TLabel", background=BG, foreground=TEXT, font=FONT_BOLD)
        style.configure(
            "PageTitle.TLabel",
            background=BG,
            foreground=TEXT,
            font=("Segoe UI", 14, "bold"),
        )
        style.configure(
            "Title.TLabel",
            background=HEADER_BG,
            foreground="#f4f4f4",
            font=FONT_TITLE,
        )
        style.configure(
            "Side.TLabel",
            background=HEADER_BG,
            foreground="#666666",
            font=("Segoe UI", 18),
        )
        style.configure(
            "Card.TLabelframe",
            background=PANEL_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=PANEL_BG,
            foreground=TEXT,
            font=FONT_BOLD,
        )
        style.configure("TSeparator", background="#4b4b4b")

        style.configure(
            "Primary.TButton",
            background=GREEN,
            foreground="#ffffff",
            bordercolor=GREEN,
            lightcolor=GREEN,
            darkcolor=GREEN,
            relief="flat",
            borderwidth=0,
            focusthickness=0,
            focuscolor=GREEN,
            padding=(11, 6),
            font=FONT_BOLD,
        )
        style.map(
            "Primary.TButton",
            background=[
                ("pressed", GREEN_HOVER),
                ("active", GREEN_HOVER),
                ("disabled", "#343434"),
            ],
            foreground=[("disabled", "#777777")],
        )
        style.configure(
            "Blue.TButton",
            background=ACCENT_DARK,
            foreground="#ffffff",
            bordercolor=ACCENT_DARK,
            lightcolor=ACCENT_DARK,
            darkcolor=ACCENT_DARK,
            relief="flat",
            borderwidth=0,
            focusthickness=0,
            focuscolor=ACCENT_DARK,
            padding=(11, 6),
            font=FONT_BOLD,
        )
        style.map(
            "Blue.TButton",
            background=[
                ("pressed", ACCENT),
                ("active", ACCENT),
                ("disabled", "#343434"),
            ],
            foreground=[("disabled", "#777777")],
        )
        style.configure(
            "Danger.TButton",
            background=RED,
            foreground="#ffffff",
            bordercolor=RED,
            lightcolor=RED,
            darkcolor=RED,
            relief="flat",
            borderwidth=0,
            focusthickness=0,
            focuscolor=RED,
            padding=(11, 6),
            font=FONT_BOLD,
        )
        style.map(
            "Danger.TButton",
            background=[
                ("pressed", "#c82323"),
                ("active", "#c82323"),
                ("disabled", "#343434"),
            ],
            foreground=[("disabled", "#777777")],
        )
        style.configure(
            "Secondary.TButton",
            background="#3a3a3a",
            foreground="#dddddd",
            bordercolor="#4f4f4f",
            lightcolor="#4f4f4f",
            darkcolor="#3a3a3a",
            relief="flat",
            borderwidth=1,
            focusthickness=0,
            focuscolor="#3a3a3a",
            padding=(9, 5),
            font=FONT_UI,
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("pressed", "#454545"),
                ("active", "#454545"),
                ("disabled", "#333333"),
            ],
            foreground=[("disabled", "#777777")],
            bordercolor=[("disabled", "#3f3f3f")],
        )
        style.configure(
            "Nav.TButton",
            background=HEADER_BG,
            foreground="#e6e6e6",
            bordercolor=HEADER_BG,
            lightcolor=HEADER_BG,
            darkcolor=HEADER_BG,
            relief="flat",
            borderwidth=0,
            focusthickness=0,
            focuscolor=HEADER_BG,
            padding=(10, 6),
            font=FONT_UI,
        )
        style.map(
            "Nav.TButton",
            background=[("pressed", "#3f3f3f"), ("active", "#3f3f3f")],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "NavActive.TButton",
            background="#304352",
            foreground="#ffffff",
            bordercolor="#304352",
            lightcolor="#304352",
            darkcolor="#304352",
            relief="flat",
            borderwidth=0,
            focusthickness=0,
            focuscolor="#304352",
            padding=(10, 6),
            font=FONT_BOLD,
        )
        style.map(
            "NavActive.TButton",
            background=[("pressed", "#304352"), ("active", "#304352")],
            foreground=[("active", "#ffffff")],
        )

        style.configure(
            "TEntry",
            fieldbackground=FIELD_BG,
            foreground=FIELD_FG,
            insertcolor=FIELD_FG,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(7, 5),
            font=FONT_UI,
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", "#2b2b2b")],
            foreground=[("disabled", "#777777")],
            bordercolor=[("focus", ACCENT)],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=FIELD_BG,
            background=FIELD_BG,
            foreground=FIELD_FG,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(6, 4),
            font=FONT_UI,
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("disabled", "#2b2b2b")],
            foreground=[("disabled", "#777777")],
            arrowcolor=[("disabled", "#555555")],
            bordercolor=[("focus", ACCENT)],
        )

        for name in ("Dark.TRadiobutton", "Dark.TCheckbutton"):
            style.configure(
                name,
                background=BG,
                foreground=TEXT,
                focuscolor=BG,
                indicatorbackground=FIELD_BG,
                indicatorforeground=ACCENT,
                upperbordercolor="#555555",
                lowerbordercolor="#222222",
                padding=(0, 3),
                font=FONT_UI,
            )
            style.map(
                name,
                background=[("active", BG)],
                foreground=[("disabled", "#777777")],
                indicatorbackground=[("selected", ACCENT), ("disabled", "#2b2b2b")],
                indicatorforeground=[("selected", "#ffffff"), ("disabled", "#666666")],
            )

        style.configure(
            "Treeview",
            background=FIELD_BG,
            fieldbackground=FIELD_BG,
            foreground="#dddddd",
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            borderwidth=1,
            relief="flat",
            rowheight=26,
            font=FONT_UI,
        )
        style.map(
            "Treeview",
            background=[("selected", ACCENT_DARK)],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Treeview.Heading",
            background=HEADER_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=HEADER_BG,
            darkcolor=HEADER_BG,
            relief="flat",
            borderwidth=0,
            padding=(8, 6),
            font=FONT_BOLD,
        )
        style.map("Treeview.Heading", background=[("active", "#3f3f3f")])

        style.configure(
            "Dark.Vertical.TScrollbar",
            background="#3a3a3a",
            troughcolor="#2a2a2a",
            bordercolor=BORDER,
            arrowcolor=TEXT,
            lightcolor="#4a4a4a",
            darkcolor="#2a2a2a",
            gripcount=0,
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#4a4a4a")],
        )

        style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor=FIELD_BG,
            background=ACCENT,
            bordercolor="#000000",
            lightcolor="#4db8ff",
            darkcolor="#006fc7",
            thickness=11,
        )
        style.configure(
            "Done.Horizontal.TProgressbar",
            troughcolor=FIELD_BG,
            background=GREEN,
            bordercolor="#000000",
            lightcolor="#7fdc9f",
            darkcolor="#1a9e3f",
            thickness=11,
        )
        style.configure(
            "Stopped.Horizontal.TProgressbar",
            troughcolor=FIELD_BG,
            background="#767676",
            bordercolor="#000000",
            lightcolor="#9a9a9a",
            darkcolor="#5a5a5a",
            thickness=11,
        )

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        self._build_header()
        container = ttk.Frame(self.root, style="Page.TFrame")
        container.grid(row=2, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        for name in ("convert", "settings", "about"):
            page = ttk.Frame(container, style="Page.TFrame", padding=(12, 10, 12, 12))
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[name] = page
        self._build_convert_page(self.pages["convert"])
        self._build_settings_page(self.pages["settings"])
        self._build_about_page(self.pages["about"])

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        title_row = ttk.Frame(header, style="Header.TFrame")
        title_row.grid(row=0, column=0, sticky="w", padx=(12, 0), pady=7)
        ttk.Label(title_row, text="⇒", style="Side.TLabel").pack(side="left")
        ttk.Label(title_row, text="IMAGE COMPACTOR", style="Title.TLabel").pack(
            side="left", padx=(5, 5)
        )
        ttk.Label(title_row, text="⇐", style="Side.TLabel").pack(side="left")
        nav = ttk.Frame(header, style="Header.TFrame")
        nav.grid(row=0, column=1, sticky="e", padx=(0, 10))
        for name, label in (
            ("convert", "Convert"),
            ("settings", "Settings"),
            ("about", "About"),
        ):
            button = ttk.Button(
                nav,
                text=label,
                width=9,
                style="Nav.TButton",
                command=lambda page=name: self.show_page(page),
            )
            button.pack(side="left", padx=(2, 0))
            self.nav_buttons[name] = button
        tk.Frame(self.root, bg="#000000", height=1).grid(row=1, column=0, sticky="ew")

    def _build_convert_page(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2)
        page.rowconfigure(1, weight=1)

        tools = ttk.Frame(page, style="Page.TFrame")
        tools.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.add_files_button = ttk.Button(
            tools, text="Add files", style="Blue.TButton", command=self.add_files
        )
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(
            tools, text="Add folder", style="Blue.TButton", command=self.add_folder
        )
        self.add_folder_button.pack(side="left", padx=(6, 0))
        self.remove_button = ttk.Button(
            tools, text="Remove", style="Secondary.TButton", command=self.remove_selected
        )
        self.remove_button.pack(side="left", padx=(12, 0))
        self.clear_button = ttk.Button(
            tools, text="Clear", style="Secondary.TButton", command=self.clear_list
        )
        self.clear_button.pack(side="left", padx=(6, 0))
        ttk.Label(tools, textvariable=self.count_text, style="Muted.TLabel").pack(
            side="right"
        )
        self.locked_widgets.extend(
            [
                self.add_files_button,
                self.add_folder_button,
                self.remove_button,
                self.clear_button,
            ]
        )

        self.files_card = ttk.LabelFrame(
            page, text="Photos", style="Card.TLabelframe", padding=10
        )
        self.files_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.files_card.columnconfigure(0, weight=1)
        self.files_card.rowconfigure(1, weight=1)
        hint_row = ttk.Frame(self.files_card, style="Panel.TFrame")
        hint_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        hint_row.columnconfigure(0, weight=1)
        self.drop_hint = ttk.Label(
            hint_row,
            text="Add photos or a folder to begin",
            style="PanelMuted.TLabel",
        )
        self.drop_hint.grid(row=0, column=0, sticky="w")

        self.tree = ttk.Treeview(
            self.files_card,
            columns=("name", "size", "status"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("name", text="File")
        self.tree.heading("size", text="Size")
        self.tree.heading("status", text="Status")
        self.tree.column("name", width=260, minwidth=180, stretch=True)
        self.tree.column("size", width=80, minwidth=65, anchor="e", stretch=False)
        self.tree.column("status", width=180, minwidth=150, anchor="w", stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew")
        file_scroll = ttk.Scrollbar(
            self.files_card,
            orient="vertical",
            command=self.tree.yview,
            style="Dark.Vertical.TScrollbar",
        )
        file_scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=file_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.refresh())
        self.tree.tag_configure("queued", foreground=MUTED)
        self.tree.tag_configure("active", foreground="#8fc9ff")
        self.tree.tag_configure("done", foreground="#7fdc9f")
        self.tree.tag_configure("failed", foreground=ERROR)
        self.tree.tag_configure("skipped", foreground=MUTED)

        right = ttk.Frame(page, style="Page.TFrame")
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)

        details_card = ttk.LabelFrame(
            right, text="Selected photo", style="Card.TLabelframe", padding=10
        )
        details_card.grid(row=0, column=0, sticky="nsew")
        details_card.columnconfigure(0, weight=1)
        details_card.rowconfigure(0, weight=1)
        self.details = tk.Text(
            details_card,
            wrap="word",
            height=12,
            bg=FIELD_BG,
            fg="#dddddd",
            insertbackground=TEXT,
            selectbackground=ACCENT_DARK,
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=FONT_MONO,
            padx=9,
            pady=8,
        )
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll = ttk.Scrollbar(
            details_card,
            orient="vertical",
            command=self.details.yview,
            style="Dark.Vertical.TScrollbar",
        )
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)
        self._set_text(self.details, "Add photos, then select one to inspect.")

        activity_card = ttk.LabelFrame(
            right, text="Activity", style="Card.TLabelframe", padding=10
        )
        activity_card.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        activity_card.columnconfigure(0, weight=1)
        activity_card.rowconfigure(0, weight=1)
        self.log_box = tk.Text(
            activity_card,
            height=6,
            wrap="word",
            state="disabled",
            bg=FIELD_BG,
            fg="#dddddd",
            insertbackground=TEXT,
            selectbackground=ACCENT_DARK,
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=FONT_MONO,
            padx=9,
            pady=7,
        )
        self.log_box.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(
            activity_card,
            orient="vertical",
            command=self.log_box.yview,
            style="Dark.Vertical.TScrollbar",
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_box.configure(yscrollcommand=log_scroll.set)

        footer = ttk.Frame(page, style="Page.TFrame")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        progress_row = ttk.Frame(footer, style="Page.TFrame")
        progress_row.grid(row=0, column=0, sticky="ew")
        progress_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            progress_row,
            mode="determinate",
            maximum=1,
            value=0,
            style="Blue.Horizontal.TProgressbar",
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            progress_row,
            textvariable=self.progress_text,
            style="Muted.TLabel",
            width=10,
            anchor="e",
        ).grid(row=0, column=1, padx=(8, 0))
        action_row = ttk.Frame(footer, style="Page.TFrame")
        action_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        ttk.Label(action_row, textvariable=self.status_text, style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.stop_button = ttk.Button(
            action_row,
            text="Stop",
            style="Danger.TButton",
            command=self.stop,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=1, padx=(8, 0))
        self.encode_button = ttk.Button(
            action_row,
            text="Convert to AVIF",
            style="Primary.TButton",
            command=self.encode_list,
        )
        self.encode_button.grid(row=0, column=2, padx=(8, 0))

    def _section(
        self, parent: ttk.Frame, row: int, title: str, hint: str
    ) -> tuple[ttk.Frame, int]:
        ttk.Label(parent, text=title, style="Setting.TLabel").grid(
            row=row, column=0, sticky="nw", pady=(9, 5)
        )
        controls = ttk.Frame(parent, style="Page.TFrame")
        controls.grid(row=row, column=1, sticky="ew", pady=(9, 5))
        ttk.Label(
            parent,
            text=hint,
            style="Muted.TLabel",
            wraplength=660,
            justify="left",
        ).grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Separator(parent, orient="horizontal").grid(
            row=row + 2, column=0, columnspan=2, sticky="ew", pady=(0, 2)
        )
        return controls, row + 3

    def _build_settings_page(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        settings_header = ttk.Frame(page, style="Page.TFrame")
        settings_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        settings_header.columnconfigure(0, weight=1)
        ttk.Label(settings_header, text="Output settings", style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            settings_header,
            text="The batch keeps the settings it starts with.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.reset_button = ttk.Button(
            settings_header,
            text="Use profile defaults",
            style="Secondary.TButton",
            command=self.apply_profile,
        )
        self.reset_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.locked_widgets.append(self.reset_button)

        holder = ttk.Frame(page, style="Page.TFrame")
        holder.grid(row=1, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.settings_canvas = tk.Canvas(
            holder,
            bg=BG,
            highlightthickness=0,
            bd=0,
            width=760,
            height=420,
            yscrollincrement=24,
        )
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scroll = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self.settings_canvas.yview,
            style="Dark.Vertical.TScrollbar",
        )
        settings_scroll.grid(row=0, column=1, sticky="ns")
        self.settings_canvas.configure(yscrollcommand=settings_scroll.set)
        self.settings_form = ttk.Frame(
            self.settings_canvas, style="Page.TFrame", padding=(4, 0, 12, 10)
        )
        self.settings_window = self.settings_canvas.create_window(
            (0, 0), window=self.settings_form, anchor="nw"
        )
        self.settings_form.bind("<Configure>", self._settings_form_configured)
        self.settings_canvas.bind("<Configure>", self._settings_canvas_configured)
        form = self.settings_form
        form.columnconfigure(0, minsize=170)
        form.columnconfigure(1, weight=1)
        row = 0

        controls, row = self._section(
            form,
            row,
            "Profile",
            "High quality: 10-bit, preset 3. Small copy: 8-bit, preset 4 with a suggested resize.",
        )
        for key in (KEEP, BACKUP):
            button = ttk.Radiobutton(
                controls,
                text=PROFILE_LABELS[key],
                value=key,
                variable=self.profile,
                command=self.apply_profile,
                style="Dark.TRadiobutton",
            )
            button.pack(side="left", padx=(0, 12))
            self.locked_widgets.append(button)

        controls, row = self._section(
            form,
            row,
            "Source class",
            "Auto detect reads the capture log and pixel count.",
        )
        for key, label in PHONE_LABELS.items():
            button = ttk.Radiobutton(
                controls,
                text=label,
                value=key,
                variable=self.phone,
                style="Dark.TRadiobutton",
            )
            button.pack(side="left", padx=(0, 10))
            self.locked_widgets.append(button)

        controls, row = self._section(
            form,
            row,
            "Resolution",
            "Suggested applies the size rules to large or remosaic photos. Custom scale uses the percentage of each side.",
        )
        radio_row = ttk.Frame(controls, style="Page.TFrame")
        radio_row.pack(fill="x")
        for key, label in RESOLUTION_LABELS.items():
            button = ttk.Radiobutton(
                radio_row,
                text=label,
                value=key,
                variable=self.resolution,
                style="Dark.TRadiobutton",
            )
            button.pack(side="left", padx=(0, 10))
            self.locked_widgets.append(button)
        scale_row = ttk.Frame(controls, style="Page.TFrame")
        scale_row.pack(fill="x", pady=(5, 0))
        self.percent_spin = ttk.Spinbox(
            scale_row,
            from_=5,
            to=100,
            increment=5,
            textvariable=self.percent,
            width=6,
        )
        self.percent_spin.pack(side="left")
        ttk.Label(scale_row, text="% of each side", style="Muted.TLabel").pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(
            scale_row, textvariable=self.output_size_text, style="Muted.TLabel"
        ).pack(side="left", padx=(18, 0))
        self.locked_widgets.append(self.percent_spin)

        controls, row = self._section(
            form,
            row,
            "Quality",
            "Higher quality means a lower CRF and a larger file.",
        )
        self.quality_spin = ttk.Spinbox(
            controls, from_=0, to=100, textvariable=self.quality, width=5
        )
        self.quality_spin.pack(side="left")
        ttk.Label(
            controls, textvariable=self.quality_text, style="Muted.TLabel"
        ).pack(side="left", padx=(8, 0))
        self.locked_widgets.append(self.quality_spin)

        controls, row = self._section(
            form,
            row,
            "SVT preset",
            "Lower presets spend more time finding savings.",
        )
        self.speed_spin = ttk.Spinbox(
            controls, from_=2, to=5, textvariable=self.speed, width=5
        )
        self.speed_spin.pack(side="left")
        ttk.Label(controls, text="2 slowest, 5 fastest", style="Muted.TLabel").pack(
            side="left", padx=(8, 0)
        )
        self.locked_widgets.append(self.speed_spin)

        controls, row = self._section(
            form,
            row,
            "Bit depth",
            "10-bit keeps more color detail. 8-bit matches the older samples.",
        )
        for value, label in ((8, "8-bit"), (10, "10-bit")):
            button = ttk.Radiobutton(
                controls,
                text=label,
                value=value,
                variable=self.bit_depth,
                style="Dark.TRadiobutton",
            )
            button.pack(side="left", padx=(0, 12))
            self.locked_widgets.append(button)

        controls, row = self._section(
            form,
            row,
            "Color",
            "The ICC profile is kept. The tag is only added when the source profile says Display P3.",
        )
        self.p3_check = ttk.Checkbutton(
            controls,
            text="Tag Display P3 when the source profile is P3",
            variable=self.tag_p3,
            style="Dark.TCheckbutton",
        )
        self.p3_check.pack(side="left")
        self.locked_widgets.append(self.p3_check)

        controls, row = self._section(
            form,
            row,
            "Save to",
            "Same folder writes beside each source. Someplace else uses the folder below. Overwrite replaces an existing AVIF only after the new encode succeeds. Off adds -2, -3 to the name.",
        )
        overwrite_row = ttk.Frame(controls, style="Page.TFrame")
        overwrite_row.pack(fill="x")
        self.overwrite_check = ttk.Checkbutton(
            overwrite_row,
            text="Overwrite existing AVIFs",
            variable=self.overwrite,
            style="Dark.TCheckbutton",
        )
        self.overwrite_check.pack(side="left")
        self.locked_widgets.append(self.overwrite_check)
        output_row = ttk.Frame(controls, style="Page.TFrame")
        output_row.pack(fill="x", pady=(5, 0))
        for value, label in (("same", "Same folder"), ("elsewhere", "Someplace else")):
            button = ttk.Radiobutton(
                output_row,
                text=label,
                value=value,
                variable=self.output_mode,
                style="Dark.TRadiobutton",
            )
            button.pack(side="left", padx=(0, 12))
            self.locked_widgets.append(button)
        folder_row = ttk.Frame(controls, style="Page.TFrame")
        folder_row.pack(fill="x", pady=(5, 0))
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.output_dir)
        self.folder_entry.pack(side="left", fill="x", expand=True)
        self.folder_button = ttk.Button(
            folder_row,
            text="Browse...",
            style="Secondary.TButton",
            command=self.choose_folder,
        )
        self.folder_button.pack(side="left", padx=(6, 0))
        self.locked_widgets.extend([self.folder_entry, self.folder_button])

        controls, row = self._section(
            form,
            row,
            "Encoder",
            "Set AVIFENC or choose avifenc.exe. The batch uses the encoder shown here.",
        )
        self.encoder_label = ttk.Label(
            controls,
            textvariable=self.encoder_text,
            style="TLabel",
            width=52,
            anchor="w",
        )
        self.encoder_label.pack(side="left")
        self.encoder_button = ttk.Button(
            controls,
            text="Browse...",
            style="Secondary.TButton",
            command=self.choose_encoder,
        )
        self.encoder_button.pack(side="left", padx=(8, 0))
        self.locked_widgets.append(self.encoder_button)

    def _settings_form_configured(self, _event) -> None:
        self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all"))

    def _settings_canvas_configured(self, event) -> None:
        self.settings_canvas.itemconfigure(self.settings_window, width=event.width)

    def _build_about_page(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        ttk.Label(page, text="Image Compactor", style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(page, text=f"Version {__version__}", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 10)
        )
        about = ttk.LabelFrame(
            page, text="What it does", style="Card.TLabelframe", padding=12
        )
        about.grid(row=2, column=0, sticky="new")
        about.columnconfigure(0, weight=1)
        paragraphs = [
            "Converts phone photos to AVIF with SVT-AV1.",
            "Accepts JPEG, PNG, WebP, TIFF, BMP and GIF. EXIF orientation is applied before a resize. PNG and WebP alpha is kept. Animated files use the first frame.",
            "Drag photos or folders onto the Photos list, or use Add files and Add folder.",
            f"Uses one fewer thread than the {physical_cores()} physical cores detected on this machine and starts every encoder at below-normal priority.",
            "The two profiles set the bit depth, CRF, SVT preset and suggested resolution. Every setting can be changed before a batch starts.",
        ]
        for index, text in enumerate(paragraphs):
            ttk.Label(
                about,
                text=text,
                style="Panel.TLabel",
                wraplength=760,
                justify="left",
            ).grid(row=index, column=0, sticky="w", pady=(0, 7))
        encoder = ttk.LabelFrame(
            page, text="Encoder", style="Card.TLabelframe", padding=12
        )
        encoder.grid(row=3, column=0, sticky="new", pady=(10, 0))
        encoder.columnconfigure(0, weight=1)
        ttk.Label(
            encoder,
            textvariable=self.encoder_full_text,
            style="Panel.TLabel",
            font=FONT_MONO,
            wraplength=760,
            justify="left",
        ).grid(row=0, column=0, sticky="w")

    def show_page(self, name: str) -> None:
        if name not in self.pages:
            return
        self.current_page = name
        self.pages[name].tkraise()
        for key, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if key == name else "Nav.TButton")
        if name == "settings":
            self.root.bind_all("<MouseWheel>", self._on_settings_wheel)
        else:
            self.root.unbind_all("<MouseWheel>")

    def _on_settings_wheel(self, event) -> None:
        if self.current_page != "settings":
            return
        step = -1 if event.delta > 0 else 1
        self.settings_canvas.yview_scroll(step * 3, "units")

    def _enable_dnd(self) -> None:
        if DND_FILES is None:
            self.drop_hint.configure(text="Add photos or a folder to begin")
            return
        targets = (self.files_card, self.tree, self.drop_hint)
        for target in targets:
            if not hasattr(target, "drop_target_register"):
                continue
            try:
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self._on_drop)
                target.dnd_bind("<<DropEnter>>", self._on_drag_enter)
                target.dnd_bind("<<DropLeave>>", self._on_drag_leave)
            except tk.TclError as exc:
                self.log(f"Drag and drop is unavailable: {exc}")
                self.drop_hint.configure(text="Add photos or a folder to begin")
                return
            self.dnd_ready = True
        if self.dnd_ready:
            self.drop_hint.configure(text="Drop photos or folders anywhere in this list")

    def _on_drop(self, event) -> None:
        try:
            items = self.root.tk.splitlist(event.data)
        except tk.TclError:
            items = [event.data]
        paths = [Path(item) for item in items]
        files = [item for item in paths if item.is_file()]
        folders = [item for item in paths if item.is_dir()]
        if files:
            self.add_paths(files)
        for folder in folders:
            self._add_folder_path(folder)
        if not files and not folders:
            self.log("Dropped items were not files or folders.")
        self._on_drag_leave(event)

    def _on_drag_enter(self, _event) -> None:
        if self.dnd_ready:
            self.drop_hint.configure(
                text="Drop to add photos or folders", style="DropActive.TLabel"
            )

    def _on_drag_leave(self, _event=None) -> None:
        if self.dnd_ready:
            self.drop_hint.configure(
                text="Drop photos or folders anywhere in this list",
                style="PanelMuted.TLabel",
            )
        else:
            self.drop_hint.configure(
                text="Add photos or a folder to begin", style="PanelMuted.TLabel"
            )

    def _add_folder_path(self, folder: Path) -> None:
        found = _image_paths(folder)
        if not found:
            self.log(f"{folder.name}: no supported photos found.")
            return
        self.add_paths(found)
        if len(found) >= MAX_LISTED_FILES:
            self.log(f"Stopped listing at {MAX_LISTED_FILES} photos.")

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
            self.encoder_full_text.set(
                "avifenc.exe not found. Set AVIFENC or choose Browse."
            )
            self.encoder_label.configure(foreground=ERROR)
            self.log(str(exc))
            return
        self.avifenc = Path(path)
        self.encoder_text.set(_short_path(self.avifenc))
        self.encoder_full_text.set(str(self.avifenc))
        self.encoder_label.configure(foreground=TEXT)
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
        if name:
            self._add_folder_path(Path(name))

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
        self.output_mode.set("elsewhere")
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
        self.quality_text.set(f"CRF {quality_to_crf(quality)}")
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
        enabled = not self.busy and self.output_mode.get() == "elsewhere"
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
        if self.output_mode.get() == "elsewhere":
            if not folder:
                messagebox.showinfo(
                    "Image Compactor", "Choose a folder, or use Same folder."
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
                "avifenc.exe is not available. Choose it with Browse on the Settings page.",
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
        self.progress.configure(
            style="Blue.Horizontal.TProgressbar", maximum=len(jobs), value=0
        )
        self.progress_text.set(f"0 / {len(jobs)}")
        for path in jobs:
            self._set_status(path, "Queued", "queued")
        self._set_busy(True)
        noun = "photo" if len(jobs) == 1 else "photos"
        self.status_text.set(f"Converting {len(jobs)} {noun}...")
        thread_total = sum(thread_counts)
        overwrite_note = ", overwriting existing AVIFs" if settings["overwrite"] else ""
        self.log(
            f"Batch: {len(jobs)} photo{'s' if len(jobs) != 1 else ''}, "
            f"{workers} at a time, {thread_total} encoder thread"
            f"{'s' if thread_total != 1 else ''} total, below-normal priority"
            f"{overwrite_note}."
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
            "overwrite": bool(self.overwrite.get()),
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
                if settings["output_mode"] == "elsewhere"
                else path.parent
            )
            self._post("item", path, "Converting", "active")
            result = encode_image(
                path,
                dest_dir,
                decision,
                avifenc=settings["avifenc"],
                threads=threads,
                overwrite=settings["overwrite"],
                cancel=self.cancel,
            )
            ratio = result.bytes_out / result.bytes_in * 100 if result.bytes_in else 0
            self._post(
                "item",
                path,
                f"Done  {_format_bytes(result.bytes_out)} ({ratio:.0f}%)",
                "done",
            )
            self._post(
                "log",
                f"{result.output.name}: {_format_bytes(result.bytes_in)} -> "
                f"{_format_bytes(result.bytes_out)} ({ratio:.0f}% of source)",
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
        self.progress.configure(
            style="Stopped.Horizontal.TProgressbar"
            if self.cancel.is_set()
            else "Done.Horizontal.TProgressbar"
        )
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
            ratio = self.bytes_out / self.bytes_in * 100
            summary += (
                f" {_format_bytes(self.bytes_in)} -> {_format_bytes(self.bytes_out)}"
                f" ({ratio:.0f}% of source)."
            )
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
    try:
        from tkinterdnd2 import TkinterDnD

        root = TkinterDnD.Tk()
    except (ImportError, tk.TclError):
        root = tk.Tk()
    App(root)
    root.mainloop()
