"""Run avifenc. One source image in, one AVIF out."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from image_compactor.facts import oriented_size
from image_compactor.suggest import Decision

AVIFENC_CANDIDATES = (
    Path(r"C:\Program Files (x86)\XL Converter\_internal\bin\win\libavif\avifenc.exe"),
    Path(r"C:\Program Files\XL Converter\_internal\bin\win\libavif\avifenc.exe"),
)

ENCODER_CREATION_FLAGS = 0
if os.name == "nt":
    ENCODER_CREATION_FLAGS = (
        getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )

_output_lock = threading.Lock()


class EncodeError(RuntimeError):
    pass


def physical_cores() -> int:
    if os.name != "nt":
        return max(1, (os.cpu_count() or 2) // 2)
    try:
        return _windows_physical_cores()
    except (AttributeError, OSError):
        return max(1, (os.cpu_count() or 2) // 2)


def _windows_physical_cores() -> int:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetLogicalProcessorInformationEx
    get_info.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    get_info.restype = wintypes.BOOL
    length = wintypes.DWORD(0)
    get_info(0, None, ctypes.byref(length))
    if not length.value:
        raise OSError("GetLogicalProcessorInformationEx returned no size")
    buffer = ctypes.create_string_buffer(length.value)
    if not get_info(0, ctypes.byref(buffer), ctypes.byref(length)):
        raise ctypes.WinError(ctypes.get_last_error())
    offset = 0
    cores = 0
    while offset + 8 <= length.value:
        # RelationProcessorCore is 0.
        relationship = ctypes.c_uint32.from_buffer(buffer, offset).value
        size = ctypes.c_uint32.from_buffer(buffer, offset + 4).value
        if size < 8:
            break
        if relationship == 0:
            cores += 1
        offset += size
    return max(1, cores)


def encoder_thread_budget() -> int:
    return max(1, physical_cores() - 1)


def worker_plan(jobs: int, budget: int) -> tuple[int, list[int]]:
    """Concurrent encoders and the thread count for each worker."""
    jobs = max(1, int(jobs))
    budget = max(1, int(budget))
    workers = min(jobs, budget)
    base, extra = divmod(budget, workers)
    return workers, [base + (1 if index < extra else 0) for index in range(workers)]


def _bundled_avifenc() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for candidate in (
        base / "avifenc" / "avifenc.exe",
        Path(sys.executable).parent / "avifenc" / "avifenc.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def find_avifenc() -> Path:
    # The frozen app carries its own encoder. Source runs may use AVIFENC or XL Converter.
    bundled = _bundled_avifenc()
    if bundled is not None:
        return bundled
    env = os.environ.get("AVIFENC", "").strip().strip('"')
    if env:
        path = Path(os.path.expandvars(env))
        if path.is_file():
            return path
        raise EncodeError(f"AVIFENC is set to {env}, and that file is not there")
    for candidate in AVIFENC_CANDIDATES:
        if candidate.is_file():
            return candidate
    found = shutil.which("avifenc")
    if found:
        return Path(found)
    raise EncodeError(
        "avifenc.exe was not found. The build should include one in the avifenc folder. "
        "Set AVIFENC or choose the encoder in the window."
    )


def avifenc_command(
    avifenc: Path,
    source: Path,
    dest: Path,
    decision: Decision,
    *,
    threads: int,
    png_input: bool,
    exif_path: Path | None,
) -> list[str]:
    command = [
        str(avifenc),
        "-c",
        "svt",
        "-q",
        str(decision.quality),
        "-s",
        str(decision.speed),
        "-y",
        "420",
        "-d",
        str(decision.bit_depth),
        "-r",
        "full",
        "-j",
        str(max(1, int(threads))),
        # Still-picture tune used by XL Converter's SVT path. This build is SVT-AV1 3.0.2.
        "-a",
        "tune=4",
    ]
    if decision.cicp:
        command += ["--cicp", decision.cicp]
    if png_input:
        # A resized JPEG and every converted format pass through an RGB PNG.
        command.append("--sharpyuv")
    if decision.drop_xmp:
        command.append("--ignore-xmp")
    if exif_path is not None:
        command += ["--exif", str(exif_path)]
    command += [str(source), str(dest)]
    return command


def unique_output(directory: Path, stem: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}.avif"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = directory / f"{stem}-{index}.avif"
        if not candidate.exists():
            return candidate
        index += 1


def output_path(directory: Path, stem: str, overwrite: bool = False) -> Path:
    """Plain name when overwrite is on, otherwise the next free name."""
    directory.mkdir(parents=True, exist_ok=True)
    if overwrite:
        return directory / f"{stem}.avif"
    return unique_output(directory, stem)


@dataclass
class EncodeResult:
    output: Path
    command: list[str]
    bytes_in: int
    bytes_out: int
    log: str


def encode_image(
    source: Path,
    dest_dir: Path,
    decision: Decision,
    *,
    avifenc: Path | None = None,
    threads: int | None = None,
    overwrite: bool = False,
    cancel: threading.Event | None = None,
) -> EncodeResult:
    avifenc = avifenc or find_avifenc()
    source = Path(source)
    dest_dir = Path(dest_dir)
    limit = encoder_thread_budget()
    threads = limit if threads is None else min(limit, max(1, int(threads)))
    if decision.width < 2 or decision.height < 2:
        raise EncodeError(
            f"{source.name}: output size {decision.width} x {decision.height} is too small"
        )
    if cancel is not None and cancel.is_set():
        raise EncodeError(f"Stopped before {source.name}")

    source_stat = source.stat()
    dest_dir.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{source.stem}-", suffix=".avif", dir=dest_dir
    )
    os.close(handle)
    temp_output = Path(temp_name)
    try:
        with tempfile.TemporaryDirectory(prefix="image-compactor-") as work_name:
            work = Path(work_name)
            encoder_input, png_input, exif_path = _prepare(source, work, decision)
            command = avifenc_command(
                avifenc,
                encoder_input,
                temp_output,
                decision,
                threads=threads,
                png_input=png_input,
                exif_path=exif_path,
            )
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=ENCODER_CREATION_FLAGS,
            )
            captured: dict[str, str] = {}

            def collect() -> None:
                captured["stdout"], captured["stderr"] = proc.communicate()

            # Drain both pipes while the process runs. A full pipe blocks avifenc.
            reader = threading.Thread(target=collect, daemon=True)
            reader.start()
            while proc.poll() is None:
                if cancel is not None and cancel.is_set():
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    break
                try:
                    proc.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    pass
            reader.join()
            log = (captured.get("stdout") or "") + (captured.get("stderr") or "")
            stopped = cancel is not None and cancel.is_set() and proc.returncode != 0
            failed = (
                proc.returncode != 0
                or not temp_output.is_file()
                or temp_output.stat().st_size == 0
            )
            if stopped:
                raise EncodeError(f"Stopped during {source.name}")
            if failed:
                raise EncodeError(
                    f"avifenc failed on {source.name} (exit {proc.returncode})\n{log[-2000:]}"
                )
        with _output_lock:
            dest = output_path(dest_dir, source.stem, overwrite)
            os.replace(temp_output, dest)
        _copy_file_times(source_stat, dest)
        return EncodeResult(
            output=dest,
            command=command,
            bytes_in=source_stat.st_size,
            bytes_out=dest.stat().st_size,
            log=log,
        )
    finally:
        temp_output.unlink(missing_ok=True)


def _prepare(source: Path, work: Path, decision: Decision) -> tuple[Path, bool, Path | None]:
    target = (decision.width, decision.height)
    with Image.open(source) as opened:
        direct = (
            opened.format in ("JPEG", "MPO")
            and opened.mode in ("RGB", "L")
            and oriented_size(opened) == target
        )
        if direct:
            return source, False, None
        icc = opened.info.get("icc_profile")
        has_alpha = opened.mode in ("RGBA", "LA") or "transparency" in opened.info
        image = ImageOps.exif_transpose(opened)
        if image.size != target:
            image = image.resize(target, Image.Resampling.LANCZOS)
        prepared = image.convert("RGBA" if has_alpha else "RGB")
        png_path = work / "prepared.png"
        save_kwargs = {}
        if icc:
            save_kwargs["icc_profile"] = icc
        prepared.save(png_path, **save_kwargs)
        exif_path = _exif_sidecar(image, work)
        return png_path, True, exif_path


def _copy_file_times(source_stat: os.stat_result, dest: Path) -> None:
    # Date modified is the filesystem time galleries use when EXIF is ignored.
    os.utime(dest, (source_stat.st_atime, source_stat.st_mtime))


def _exif_sidecar(image: Image.Image, work: Path) -> Path | None:
    try:
        exif = image.getexif()
        if not exif:
            return None
        # Orientation is already applied by exif_transpose.
        exif[0x0112] = 1
        payload = exif.tobytes()
    except (AttributeError, OSError, SyntaxError, TypeError, ValueError):
        return None
    if not payload:
        return None
    path = work / "exif.bin"
    path.write_bytes(payload)
    return path
