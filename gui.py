"""Window for the two AVIF profiles."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from image_compactor import __version__
from image_compactor.encode import EncodeError, encode_jpeg, find_avifenc
from image_compactor.facts import PhotoFacts, inspect_jpeg
from image_compactor.suggest import (
    BACKUP,
    KEEP,
    PROFILES,
    Decision,
    decide,
    quality_to_crf,
)

PHONE_LABELS = {"auto": "Auto", "budget": "Budget", "sharp": "Sharp"}
DOWNSCALE_LABELS = {
    "off": "Off",
    "suggested": "Suggested",
    "percent": "Percent of each side",
}


def describe(facts: PhotoFacts, decision: Decision) -> str:
    lines = [
        f"{facts.make} {facts.model}".strip() or facts.path.name,
        f"{facts.width} x {facts.height}, {facts.megapixels:.1f} MP",
    ]
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
    icc = facts.icc_name or "none"
    lines.append(f"ICC: {icc}")
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
        lines.append(f"HDR gain map, {facts.gain_map.length} bytes, file offset {facts.gain_map.offset}.")
        for key, value in facts.gain_map.fields.items():
            lines.append(f"  {key} = {value}")
        headroom = _headroom_line(facts.gain_map.fields)
        if headroom:
            lines.append(headroom)
    try:
        lines.append(f"JPEG size: {facts.path.stat().st_size:,} bytes")
    except OSError:
        pass
    lines.append("")
    lines.append(f"Phone class: {decision.phone_class}")
    lines.append(
        f"Output: {decision.width} x {decision.height}"
        + (f", scale {decision.scale:.3f}" if decision.scale < 0.999 else ", full resolution")
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
        f"GainMapMax {gain_max:g} is a linear ratio of {peak:.2f} at map value 1, before the offsets."
    )


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Image Compactor {__version__}")
        self.root.minsize(880, 640)
        self.paths: list[Path] = []
        self.cache: dict[Path, tuple] = {}
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None

        self.profile = tk.StringVar(value=KEEP)
        self.phone = tk.StringVar(value="auto")
        self.speed = tk.IntVar(value=PROFILES[KEEP].speed)
        self.quality = tk.DoubleVar(value=PROFILES[KEEP].quality)
        self.bit_depth = tk.IntVar(value=PROFILES[KEEP].bit_depth)
        self.downscale = tk.StringVar(value=PROFILES[KEEP].downscale)
        self.percent = tk.DoubleVar(value=75)
        self.tag_p3 = tk.BooleanVar(value=True)
        self.output_mode = tk.StringVar(value="beside")
        self.output_dir = tk.StringVar(value="")
        self.crf_text = tk.StringVar(value="")
        self.status = tk.StringVar(value="")

        self._build()
        self._bind_traces()
        self.apply_profile()
        self._check_encoder()

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        files = ttk.LabelFrame(outer, text="JPEG files", padding=6)
        files.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        files.rowconfigure(1, weight=1)
        files.columnconfigure(0, weight=1)
        buttons = ttk.Frame(files)
        buttons.grid(row=0, column=0, sticky="ew")
        ttk.Button(buttons, text="Add files", command=self.add_files).pack(side="left")
        ttk.Button(buttons, text="Add folder", command=self.add_folder).pack(side="left", padx=6)
        ttk.Button(buttons, text="Remove", command=self.remove_selected).pack(side="left")
        self.list = tk.Listbox(files, exportselection=False, activestyle="dotbox")
        self.list.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        scroll = ttk.Scrollbar(files, orient="vertical", command=self.list.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        self.list.configure(yscrollcommand=scroll.set)
        self.list.bind("<<ListboxSelect>>", lambda _event: self.refresh())

        form = ttk.LabelFrame(outer, text="Encode", padding=6)
        form.grid(row=0, column=1, sticky="new")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Profile").grid(row=0, column=0, sticky="w")
        profile_row = ttk.Frame(form)
        profile_row.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            profile_row, text="Keep", value=KEEP, variable=self.profile, command=self.apply_profile
        ).pack(side="left")
        ttk.Radiobutton(
            profile_row,
            text="Backup",
            value=BACKUP,
            variable=self.profile,
            command=self.apply_profile,
        ).pack(side="left", padx=8)

        ttk.Label(form, text="Phone").grid(row=1, column=0, sticky="w", pady=(6, 0))
        phone_row = ttk.Frame(form)
        phone_row.grid(row=1, column=1, sticky="w", pady=(6, 0))
        for key, label in PHONE_LABELS.items():
            ttk.Radiobutton(phone_row, text=label, value=key, variable=self.phone).pack(side="left", padx=(0, 8))

        ttk.Label(form, text="Speed").grid(row=2, column=0, sticky="w", pady=(6, 0))
        speed = ttk.Spinbox(form, from_=2, to=5, textvariable=self.speed, width=6)
        speed.grid(row=2, column=1, sticky="w", pady=(6, 0))

        ttk.Label(form, text="Quality").grid(row=3, column=0, sticky="w", pady=(6, 0))
        quality_row = ttk.Frame(form)
        quality_row.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        ttk.Scale(quality_row, from_=0, to=100, variable=self.quality, orient="horizontal").pack(
            side="left", fill="x", expand=True
        )
        ttk.Label(quality_row, textvariable=self.crf_text, width=22).pack(side="left", padx=(8, 0))

        ttk.Label(form, text="Bit depth").grid(row=4, column=0, sticky="w", pady=(6, 0))
        depth_row = ttk.Frame(form)
        depth_row.grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Radiobutton(depth_row, text="8", value=8, variable=self.bit_depth).pack(side="left")
        ttk.Radiobutton(depth_row, text="10", value=10, variable=self.bit_depth).pack(side="left", padx=8)

        ttk.Label(form, text="Downscale").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            form,
            state="readonly",
            textvariable=self.downscale,
            values=tuple(DOWNSCALE_LABELS.values()),
            width=24,
        ).grid(row=5, column=1, sticky="w", pady=(6, 0))

        ttk.Label(form, text="Percent").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(form, from_=5, to=100, increment=5, textvariable=self.percent, width=6).grid(
            row=6, column=1, sticky="w", pady=(6, 0)
        )

        ttk.Checkbutton(
            form,
            text="Tag Display P3 when the JPEG carries that ICC profile",
            variable=self.tag_p3,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(form, text="Save").grid(row=8, column=0, sticky="w", pady=(6, 0))
        save_row = ttk.Frame(form)
        save_row.grid(row=8, column=1, sticky="w", pady=(6, 0))
        ttk.Radiobutton(save_row, text="Next to each JPEG", value="beside", variable=self.output_mode).pack(side="left")
        ttk.Radiobutton(save_row, text="Folder", value="folder", variable=self.output_mode).pack(side="left", padx=8)
        ttk.Button(save_row, text="Choose", command=self.choose_folder).pack(side="left")

        action = ttk.Frame(form)
        action.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.encode_button = ttk.Button(action, text="Encode list", command=self.encode_list)
        self.encode_button.pack(side="left")
        self.stop_button = ttk.Button(action, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)

        details_frame = ttk.LabelFrame(outer, text="Selected photo", padding=6)
        details_frame.grid(row=1, column=1, sticky="nsew", pady=(8, 0))
        details_frame.rowconfigure(0, weight=1)
        details_frame.columnconfigure(0, weight=1)
        self.details = tk.Text(details_frame, wrap="word", height=12, relief="flat")
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll = ttk.Scrollbar(details_frame, command=self.details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)

        log_frame = ttk.LabelFrame(outer, text="Log", padding=6)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        outer.rowconfigure(2, weight=0)
        self.log_box = tk.Text(log_frame, wrap="word", height=6, relief="flat")
        self.log_box.grid(row=0, column=0, sticky="nsew")
        ttk.Label(outer, textvariable=self.status).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _bind_traces(self) -> None:
        for var in (
            self.phone,
            self.speed,
            self.quality,
            self.bit_depth,
            self.downscale,
            self.percent,
            self.tag_p3,
        ):
            var.trace_add("write", lambda *_args: self.refresh())

    def _check_encoder(self) -> None:
        try:
            path = find_avifenc()
        except EncodeError as exc:
            self.status.set(str(exc))
            self.log(str(exc))
            return
        self.status.set(f"Encoder: {path}")

    def apply_profile(self) -> None:
        defaults = PROFILES[self.profile.get()]
        self.speed.set(defaults.speed)
        self.quality.set(defaults.quality)
        self.bit_depth.set(defaults.bit_depth)
        self.downscale.set(DOWNSCALE_LABELS[defaults.downscale])
        self.refresh()

    def add_files(self) -> None:
        names = filedialog.askopenfilenames(
            title="JPEG photos",
            filetypes=[("JPEG", "*.jpg *.jpeg"), ("All files", "*.*")],
        )
        self.add_paths([Path(name) for name in names])

    def add_folder(self) -> None:
        name = filedialog.askdirectory(title="Folder of JPEG photos")
        if not name:
            return
        found = _jpeg_paths(Path(name))
        self.add_paths(found)
        if len(found) >= 2000:
            self.log("Stopped listing at 2000 JPEG files.")

    def add_paths(self, paths: list[Path]) -> None:
        added = False
        for path in paths:
            path = Path(path)
            if path.suffix.lower() not in {".jpg", ".jpeg"}:
                continue
            resolved = path
            if resolved in self.paths:
                continue
            self.paths.append(resolved)
            self.list.insert("end", f"{resolved.parent.name} / {resolved.name}")
            added = True
        if added and not self.list.curselection():
            self.list.selection_set(0)
        self.refresh()

    def remove_selected(self) -> None:
        indexes = list(self.list.curselection())
        if not indexes:
            return
        for index in reversed(indexes):
            del self.paths[index]
            self.list.delete(index)
        if self.paths:
            self.list.selection_set(min(indexes[0] if indexes else 0, len(self.paths) - 1))
        self.refresh()

    def choose_folder(self) -> None:
        name = filedialog.askdirectory(title="Folder for AVIF files")
        if not name:
            return
        self.output_dir.set(name)
        self.output_mode.set("folder")
        self.status.set(name)

    def selected_path(self) -> Path | None:
        indexes = self.list.curselection()
        if not indexes:
            return None
        return self.paths[indexes[0]]

    def current_decision(self, facts: PhotoFacts) -> Decision:
        return decide(
            facts,
            phone_override=self.phone.get(),
            speed=self._int(self.speed, PROFILES[KEEP].speed),
            quality=self._int(self.quality, PROFILES[KEEP].quality),
            bit_depth=self._int(self.bit_depth, 8),
            downscale=self._downscale_key(),
            percent=self._float(self.percent, 75),
            tag_p3=bool(self.tag_p3.get()),
        )

    def refresh(self) -> None:
        quality = self._int(self.quality, 0)
        self.crf_text.set(f"{quality}   CRF {quality_to_crf(quality)}")
        path = self.selected_path()
        self._set_text(self.details, self._details_for(path) if path else "Add JPEG files, then select one.")

    def _details_for(self, path: Path) -> str:
        try:
            facts = self._facts(path)
        except Exception as exc:
            return f"{path.name}\n{exc}"
        return describe(facts, self.current_decision(facts))

    def _facts(self, path: Path) -> PhotoFacts:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self.cache.get(path)
        if cached and cached[0] == key:
            return cached[1]
        facts = inspect_jpeg(path)
        self.cache[path] = (key, facts)
        return facts

    def encode_list(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.paths:
            messagebox.showinfo("Image Compactor", "Add at least one JPEG.")
            return
        if self.output_mode.get() == "folder" and not self.output_dir.get():
            messagebox.showinfo("Image Compactor", "Choose a folder, or save next to each JPEG.")
            return
        try:
            find_avifenc()
        except EncodeError as exc:
            messagebox.showerror("Image Compactor", str(exc))
            return
        jobs = list(self.paths)
        settings = self._snapshot()
        self.cancel = threading.Event()
        self.encode_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.worker = threading.Thread(target=self._encode_worker, args=(jobs, settings), daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.cancel.set()
        self.status.set("Stopping after the current encoder step.")

    def _snapshot(self) -> dict:
        return {
            "phone": self.phone.get(),
            "speed": self._int(self.speed, 4),
            "quality": self._int(self.quality, 45),
            "bit_depth": self._int(self.bit_depth, 8),
            "downscale": self._downscale_key(),
            "percent": self._float(self.percent, 75),
            "tag_p3": bool(self.tag_p3.get()),
            "output_mode": self.output_mode.get(),
            "output_dir": self.output_dir.get(),
        }

    def _encode_worker(self, jobs: list[Path], settings: dict) -> None:
        for index, path in enumerate(jobs, start=1):
            if self.cancel.is_set():
                self.root.after(0, lambda: self.log("Stopped."))
                break
            label = f"{index} / {len(jobs)}  {path.name}"
            self.root.after(0, lambda text=label: self.status.set(text))
            try:
                facts = inspect_jpeg(path)
                decision = decide(
                    facts,
                    phone_override=settings["phone"],
                    speed=settings["speed"],
                    quality=settings["quality"],
                    bit_depth=settings["bit_depth"],
                    downscale=settings["downscale"],
                    percent=settings["percent"],
                    tag_p3=settings["tag_p3"],
                )
                dest_dir = Path(settings["output_dir"]) if settings["output_mode"] == "folder" else path.parent
                result = encode_jpeg(path, dest_dir, decision, cancel=self.cancel)
            except Exception as exc:
                self.root.after(0, lambda text=f"{path.name}: {exc}": self.log(text))
                continue
            self.root.after(0, lambda result=result: self._log_result(result))
        self.root.after(0, self._encode_finished)

    def _log_result(self, result) -> None:
        self.log(f"{result.output}  ({result.bytes_out:,} bytes)")

    def _encode_finished(self) -> None:
        self.encode_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status.set("Idle.")

    def log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text.rstrip() + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _downscale_key(self) -> str:
        label = self.downscale.get()
        for key, value in DOWNSCALE_LABELS.items():
            if value == label or key == label:
                return key
        return "off"

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


def _jpeg_paths(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for name in filenames:
            if name.lower().endswith((".jpg", ".jpeg")):
                found.append(Path(dirpath) / name)
                if len(found) >= 2000:
                    return found
    return found


def main() -> None:
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
