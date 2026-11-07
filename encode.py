"""Run the XL Converter avifenc build. One JPEG in, one AVIF out."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from image_compactor.suggest import Decision

AVIFENC_CANDIDATES = (
    Path(r"C:\Program Files (x86)\XL Converter\_internal\bin\win\libavif\avifenc.exe"),
    Path(r"C:\Program Files\XL Converter\_internal\bin\win\libavif\avifenc.exe"),
)


class EncodeError(RuntimeError):
    pass


def find_avifenc() -> Path:
    env = os.environ.get("AVIFENC")
    if env:
        path = Path(env)
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
        "avifenc.exe was not found. Install XL Converter, or set AVIFENC to avifenc.exe."
    )


def avifenc_command(
    avifenc: Path,
    source: Path,
    dest: Path,
    decision: Decision,
    *,
    resized: bool,
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
        "all",
        # Still-picture tune used by XL Converter's SVT path. This build is SVT-AV1 3.0.2.
        "-a",
        "tune=4",
    ]
    if decision.cicp:
        command += ["--cicp", decision.cicp]
    if resized:
        # Direct JPEG copies skip the RGB round trip. A resized PNG does not.
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


@dataclass
class EncodeResult:
    output: Path
    command: list[str]
    bytes_out: int
    log: str


def encode_jpeg(
    source: Path,
    dest_dir: Path,
    decision: Decision,
    *,
    avifenc: Path | None = None,
    cancel: threading.Event | None = None,
) -> EncodeResult:
    avifenc = avifenc or find_avifenc()
    dest = unique_output(dest_dir, Path(source).stem)
    with tempfile.TemporaryDirectory(prefix="image-compactor-") as temp_name:
        temp = Path(temp_name)
        encoder_input, resized, exif_path = _prepare(Path(source), temp, decision)
        command = avifenc_command(
            avifenc,
            encoder_input,
            dest,
            decision,
            resized=resized,
            exif_path=exif_path,
        )
        if cancel is not None and cancel.is_set():
            raise EncodeError(f"Stopped before {source.name}")
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
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
        stdout, stderr = proc.communicate()
        log = (stdout or "") + (stderr or "")
        stopped = cancel is not None and cancel.is_set() and proc.returncode != 0
        failed = proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0
        if stopped or failed:
            if dest.is_file():
                dest.unlink()
            if stopped:
                raise EncodeError(f"Stopped during {source.name}")
            raise EncodeError(
                f"avifenc failed on {source.name} (exit {proc.returncode})\n{log[-2000:]}"
            )
        _copy_file_times(Path(source), dest)
        return EncodeResult(
            output=dest,
            command=command,
            bytes_out=dest.stat().st_size,
            log=log,
        )


def _prepare(source: Path, temp: Path, decision: Decision) -> tuple[Path, bool, Path | None]:
    needs_resize = decision.width != 0 and (
        decision.scale < 0.999 or decision.width * decision.height < _jpeg_pixels(source)
    )
    # scale 1 keeps the JPEG bytes on the avifenc direct-copy path.
    if not needs_resize:
        return source, False, None

    image = Image.open(source)
    image = ImageOps.exif_transpose(image)
    icc = image.info.get("icc_profile")
    resized = image.convert("RGB").resize(
        (decision.width, decision.height),
        Image.Resampling.LANCZOS,
    )
    png_path = temp / "resized.png"
    save_kwargs = {}
    if icc:
        save_kwargs["icc_profile"] = icc
    resized.save(png_path, **save_kwargs)

    exif_path = _exif_sidecar(image, temp)
    return png_path, True, exif_path


def _copy_file_times(source: Path, dest: Path) -> None:
    # Date modified is the filesystem time galleries use when EXIF is ignored.
    stat = source.stat()
    os.utime(dest, (stat.st_atime, stat.st_mtime))


def _jpeg_pixels(source: Path) -> int:
    with Image.open(source) as image:
        return image.size[0] * image.size[1]


def _exif_sidecar(image: Image.Image, temp: Path) -> Path | None:
    try:
        exif = image.getexif()
        # Orientation is already applied by exif_transpose.
        exif[0x0112] = 1
        payload = exif.tobytes()
    except Exception:
        return None
    if not payload:
        return None
    path = temp / "exif.bin"
    path.write_bytes(payload)
    return path
