"""Turn photo facts and the two profiles into encoder settings."""

from __future__ import annotations

import math
from dataclasses import dataclass

from image_compactor.facts import PhotoFacts

# avifenc -s is passed straight through as the SVT-AV1 preset since SVT 0.9.
SPEED_MIN = 2
SPEED_MAX = 5

KEEP = "keep"
BACKUP = "backup"


@dataclass(frozen=True)
class ProfileDefaults:
    key: str
    speed: int
    quality: int
    bit_depth: int
    downscale: str


PROFILES = {
    KEEP: ProfileDefaults(KEEP, speed=4, quality=45, bit_depth=10, downscale="off"),
    BACKUP: ProfileDefaults(BACKUP, speed=5, quality=35, bit_depth=8, downscale="suggested"),
}


def quality_to_crf(quality: int) -> int:
    # libavif svtQualityToQuantizer: ((100 - q) * 63 + 50) / 100, integer division.
    # Quality 45 -> CRF 35. Quality 35 -> CRF 41. Quality 100 -> CRF 0.
    return ((100 - int(quality)) * 63 + 50) // 100


def classify_phone(facts: PhotoFacts, override: str) -> str:
    if override in ("budget", "sharp"):
        return override
    if facts.remosaic or facts.megapixels >= 40:
        return "budget"
    if 8 <= facts.megapixels <= 32:
        return "sharp"
    return "unknown"


def backup_target_megapixels(megapixels: float, phone_class: str, remosaic: bool) -> float | None:
    """Pixel count to aim for on the backup profile.

    A 50 MP quad-bayer remosaic is four photosites guessing a full grid.
    24 MP is the count asked for: enough to keep a crop, short of the invented pixels.
    108 MP and 200 MP on a sharp class stop at 48 MP. The same files on a budget class stop at 24.
    A file already under 40 MP, with no remosaic flag, is left alone.
    """
    large = megapixels >= 40 or remosaic
    if not large:
        return None
    if megapixels >= 80 and phone_class == "sharp":
        return 48.0
    return 24.0


def linear_scale_for_megapixels(megapixels: float, target: float) -> float:
    if megapixels <= 0 or target >= megapixels:
        return 1.0
    return math.sqrt(target / megapixels)


def even_dimension(value: float) -> int:
    rounded = max(2, int(round(value)))
    if rounded % 2:
        rounded -= 1
    return max(2, rounded)


@dataclass(frozen=True)
class Decision:
    phone_class: str
    speed: int
    quality: int
    crf: int
    bit_depth: int
    scale: float
    width: int
    height: int
    target_megapixels: float | None
    cicp: str | None
    drop_xmp: bool
    lines: tuple[str, ...]


def decide(
    facts: PhotoFacts,
    *,
    phone_override: str,
    speed: int,
    quality: int,
    bit_depth: int,
    downscale: str,
    percent: float,
    tag_p3: bool,
) -> Decision:
    phone_class = classify_phone(facts, phone_override)
    speed = min(SPEED_MAX, max(SPEED_MIN, int(speed)))
    quality = min(100, max(0, int(quality)))
    bit_depth = 10 if int(bit_depth) == 10 else 8
    lines: list[str] = []

    target = None
    scale = 1.0
    if downscale == "percent":
        scale = max(0.05, min(1.0, float(percent) / 100.0))
        lines.append(
            f"Downscale {percent:g}% on each side, {scale * scale * 100:.1f}% of the pixels."
        )
    elif downscale == "suggested":
        target = backup_target_megapixels(facts.megapixels, phone_class, facts.remosaic)
        if target is None:
            lines.append(
                f"{facts.megapixels:.1f} MP, class {phone_class}. Suggested downscale is off."
            )
        else:
            scale = linear_scale_for_megapixels(facts.megapixels, target)
            lines.append(
                f"Suggested downscale {facts.megapixels:.1f} MP -> {target:.0f} MP "
                f"({scale * 100:.1f}% on each side)."
            )
    else:
        lines.append("Resolution stays at the JPEG size.")

    width = even_dimension(facts.width * scale)
    height = even_dimension(facts.height * scale)
    if width == facts.width and height == facts.height:
        scale = 1.0

    cicp = None
    if tag_p3 and facts.display_p3:
        cicp = "12/13/6"
        lines.append(
            "ICC is Display P3. CICP will be primaries 12, transfer 13, matrix 6."
        )
        if facts.exif_says_srgb:
            lines.append(
                "EXIF ColorSpace is 1 (sRGB). The tag stays. The AVIF colour box carries P3."
            )
    elif facts.display_p3:
        lines.append("Display P3 ICC is present. CICP tagging is off for this job.")

    if facts.gain_map is not None:
        lines.append(
            f"HDR gain map, {facts.gain_map.length} bytes. "
            "The AVIF encode keeps the SDR base and drops the map."
        )
    if facts.remosaic:
        lines.append(
            f"Capture log says hardware remosaic"
            + (f", scene {facts.scene_mode}." if facts.scene_mode else ".")
        )
    if facts.sensor_hits:
        lines.append("Header strings: " + ", ".join(facts.sensor_hits) + ".")

    lines.append(
        f"SVT-AV1 preset {speed}, quality {quality}, CRF {quality_to_crf(quality)}, "
        f"{bit_depth}-bit, 4:2:0, full range."
    )
    return Decision(
        phone_class=phone_class,
        speed=speed,
        quality=quality,
        crf=quality_to_crf(quality),
        bit_depth=bit_depth,
        scale=scale,
        width=width,
        height=height,
        target_megapixels=target,
        cicp=cicp,
        drop_xmp=facts.gain_map is not None,
        lines=tuple(lines),
    )
