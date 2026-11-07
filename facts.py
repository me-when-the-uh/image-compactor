"""Read what a phone JPEG actually contains: size, ICC, remosaic flag, gain map."""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ExifTags

# EXIF ColorSpace: 1 is sRGB, 65535 is uncalibrated.
EXIF_SRGB = 1


@dataclass
class GainMap:
    length: int
    offset: int
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class PhotoFacts:
    path: Path
    width: int
    height: int
    make: str
    model: str
    lens: str
    iso: int | None
    f_number: float | None
    focal_length_mm: float | None
    focal_35mm: int | None
    icc_name: str
    exif_color_space: int | None
    remosaic: bool
    scene_mode: str
    sensor_hits: tuple[str, ...]
    gain_map: GainMap | None
    vendor_json: dict[str, str]
    capture_note: str

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1_000_000

    @property
    def display_p3(self) -> bool:
        return "display p3" in self.icc_name.lower()

    @property
    def exif_says_srgb(self) -> bool:
        return self.exif_color_space == EXIF_SRGB


_SENSOR_NEEDLES = (
    b"imx766",
    b"lyt700",
    b"lyt-700",
    b"s5khp5",
    b"isocell hp5",
    b"hp5",
)


def inspect_jpeg(path: Path) -> PhotoFacts:
    path = Path(path)
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"{path}: not a JPEG")

    header_end = _scan_end(data)
    header = data[:header_end]
    icc = _icc_name(header)
    gain = _gain_map(data, header)
    note = _capture_note(header)
    hits = _sensor_hits(header)

    with Image.open(path) as image:
        width, height = image.size
        exif = image.getexif()
        flat = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
        try:
            sub = exif.get_ifd(0x8769)
        except Exception:
            sub = {}
        sub_named = {ExifTags.TAGS.get(k, str(k)): v for k, v in sub.items()}

    def pick(*names):
        for name in names:
            if name in sub_named:
                return sub_named[name]
            if name in flat:
                return flat[name]
        return None

    maker = pick("MakerNote")
    vendor = _vendor_json(maker)
    user_comment = _user_comment(pick("UserComment"))
    capture = note or user_comment
    scene = _scene_mode(header)

    color_space = pick("ColorSpace")
    if isinstance(color_space, int):
        exif_color = color_space
    else:
        exif_color = None

    iso = pick("ISOSpeedRatings", "PhotographicSensitivity")
    try:
        iso = int(iso) if iso is not None else None
    except (TypeError, ValueError):
        iso = None

    return PhotoFacts(
        path=path,
        width=width,
        height=height,
        make=_text(pick("Make") or flat.get("Make") or ""),
        model=_text(pick("Model") or flat.get("Model") or ""),
        lens=_text(pick("LensModel") or ""),
        iso=iso,
        f_number=_float(pick("FNumber")),
        focal_length_mm=_float(pick("FocalLength")),
        focal_35mm=_int(pick("FocalLengthIn35mmFilm")),
        icc_name=icc,
        exif_color_space=exif_color,
        remosaic=_is_remosaic(capture),
        scene_mode=scene,
        sensor_hits=hits,
        gain_map=gain,
        vendor_json=vendor,
        capture_note=capture[:500],
    )


def _scan_end(data: bytes) -> int:
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            if marker == 0xD9:
                return i
            continue
        if i + 2 > len(data):
            break
        seglen = struct.unpack(">H", data[i : i + 2])[0]
        i += seglen
        if marker == 0xDA:
            return i
    return min(len(data), 2_000_000)


def _icc_name(header: bytes) -> str:
    marker = header.find(b"ICC_PROFILE")
    if marker < 0:
        return ""
    desc = header.find(b"Display P3", marker, marker + 800)
    if desc >= 0:
        return "Display P3"
    desc = header.find(b"sRGB", marker, marker + 800)
    if desc >= 0:
        return "sRGB"
    return "ICC"


def _sensor_hits(header: bytes) -> tuple[str, ...]:
    folded = header.lower()
    found = []
    for needle in _SENSOR_NEEDLES:
        start = 0
        while start < len(folded):
            at = folded.find(needle, start)
            if at < 0:
                break
            before = folded[at - 1] if at else 0
            after_at = at + len(needle)
            after = folded[after_at] if after_at < len(folded) else 0
            if _token_edge(before) and _token_edge(after):
                found.append(needle.decode("ascii"))
                break
            start = at + 1
    return tuple(found)


def _token_edge(value: int) -> bool:
    return not (48 <= value <= 57 or 97 <= value <= 122)


def _scene_mode(header: bytes) -> str:
    # vivo stores a numeric sceneMode and, in a second log, a name.
    values = []
    for match in re.finditer(br"sceneMode:\s*([^;\x00\r\n]{1,40})", header):
        raw = match.group(1).decode("latin1", "replace")
        text = "".join(ch for ch in raw if 32 <= ord(ch) < 127).strip()
        if text:
            values.append(text)
    for text in values:
        if any(ch.isalpha() for ch in text):
            return text
    return values[0] if values else ""


def _user_comment(value) -> str:
    if isinstance(value, bytes):
        for prefix in (
            b"ASCII\x00\x00\x00",
            b"UNICODE\x00",
            b"JIS\x00\x00\x00\x00\x00",
            b"\x00" * 8,
        ):
            if value.startswith(prefix):
                value = value[len(prefix) :]
                break
        text = value.decode("utf-8", "replace")
    elif value is None:
        return ""
    else:
        text = str(value)
    text = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in text)
    text = " ".join(text.split())
    lowered = text.lower()
    if "hw-remosaic" not in lowered and "scenemode:" not in lowered:
        return ""
    return text


def _is_remosaic(text: str) -> bool:
    lowered = text.lower().replace(" ", "")
    return "hw-remosaic:true" in lowered or "moduleid:remosaic" in lowered


def _capture_note(header: bytes) -> str:
    # vivo writes a semicolon log in APP6. Qualcomm debug blobs sit in APP4.
    start = header.find(b"hw-remosaic")
    if start < 0:
        start = header.find(b"sceneMode:")
    if start < 0:
        return ""
    chunk = header[max(0, start - 80) : start + 400]
    text = chunk.decode("latin1", "replace")
    text = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in text)
    return " ".join(text.split())


def _gain_map(data: bytes, header: bytes) -> GainMap | None:
    if b"hdrgm:" not in header and b"Item:Semantic=\"GainMap\"" not in header:
        return None
    length_match = re.search(br'Item:Semantic="GainMap".{0,200}Item:Length="(\d+)"', header, re.S)
    length = int(length_match.group(1)) if length_match else 0
    images = _mpf_images(data)
    secondary = next((item for item in images if item["offset"] != 0), None)
    if secondary is None:
        return GainMap(length=length, offset=-1) if length else None
    absolute = secondary["absolute"]
    fields = {}
    if 0 <= absolute < len(data):
        blob = data[absolute : absolute + min(secondary["size"], 65536)]
        xmp_start = blob.find(b"hdrgm:")
        if xmp_start >= 0:
            snippet = blob[xmp_start : xmp_start + 2500].decode("latin1", "replace")
            for key, value in re.findall(r"hdrgm:([A-Za-z0-9]+)=\"([^\"]*)\"", snippet):
                fields[key] = value
    return GainMap(length=secondary["size"] or length, offset=absolute, fields=fields)


def _mpf_images(data: bytes) -> list[dict]:
    mpf_at = data.find(b"MPF\x00")
    if mpf_at < 0 or mpf_at + 16 > len(data):
        return []
    tiff = mpf_at + 4
    endian = ">" if data[tiff : tiff + 2] == b"MM" else "<"
    ifd_off = struct.unpack(endian + "I", data[tiff + 4 : tiff + 8])[0]
    count_pos = tiff + ifd_off
    if count_pos + 2 > len(data):
        return []
    nentries = struct.unpack(endian + "H", data[count_pos : count_pos + 2])[0]
    pos = count_pos + 2
    n_images = 0
    entry_off = None
    for _ in range(nentries):
        if pos + 12 > len(data):
            return []
        tag, _typ, _count, val = struct.unpack(endian + "HHII", data[pos : pos + 12])
        pos += 12
        if tag == 0xB001:
            n_images = val
        elif tag == 0xB002:
            entry_off = val
    if entry_off is None or n_images < 1:
        return []
    base = tiff + entry_off
    images = []
    for index in range(n_images):
        start = base + index * 16
        if start + 12 > len(data):
            break
        _attr, size, offset = struct.unpack(endian + "III", data[start : start + 12])
        absolute = 0 if offset == 0 else tiff + offset
        images.append({"size": size, "offset": offset, "absolute": absolute})
    return images


def _vendor_json(maker) -> dict[str, str]:
    if isinstance(maker, bytes):
        text = maker.decode("utf-8", "replace")
    else:
        text = str(maker or "")
    brace = text.find("{")
    if brace < 0:
        return {}
    try:
        parsed = json.loads(text[brace:])
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    kept = {}
    for key in ("hdrStat", "lightUp", "hdrFusion", "cvtm", "nightFlag"):
        if key in parsed:
            kept[key] = str(parsed[key])
    return kept


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value).strip("\x00 ").strip()


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
