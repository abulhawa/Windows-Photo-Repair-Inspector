"""Image metadata readers and writers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import piexif
from PIL import Image

from .core import WRITABLE_TAKEN_EXTENSIONS, format_timestamp

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - dependency is declared, kept defensive
    pass

# EXIF numeric tag ids.
_DATETIME = 306
_DATETIME_ORIGINAL = 36867
_DATETIME_DIGITIZED = 36868


def get_exif_taken_date(path: Path) -> Optional[str]:
    """Read the best available EXIF capture timestamp without modifying the file."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            if not exif:
                return None
            for tag in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _DATETIME):
                value = exif.get(tag)
                if isinstance(value, bytes):
                    try:
                        value = value.decode("ascii", errors="strict")
                    except UnicodeDecodeError:
                        continue
                if isinstance(value, str) and value.strip():
                    return value.strip().replace(":", "-", 2)
    except (OSError, ValueError):
        return None
    return None


def write_taken_metadata(path: Path, timestamp: float) -> None:
    """Update JPEG EXIF capture timestamps while preserving existing metadata.

    If existing EXIF cannot be parsed safely, the write is refused rather than
    replacing metadata with a new empty EXIF block.
    """
    if path.suffix.lower() not in WRITABLE_TAKEN_EXTENSIONS:
        raise ValueError("Taken At updates are currently supported only for JPEG files.")

    value = format_timestamp(timestamp)
    if not value:
        raise ValueError("Timestamp is outside the supported range.")
    exif_value = value.replace("-", ":", 2).encode("ascii")

    try:
        exif_dict = piexif.load(str(path))
    except Exception as exc:
        raise ValueError(
            "Existing EXIF metadata could not be read safely; refusing to overwrite it."
        ) from exc

    exif_dict.setdefault("0th", {})
    exif_dict.setdefault("Exif", {})
    exif_dict.setdefault("GPS", {})
    exif_dict.setdefault("1st", {})
    exif_dict.setdefault("thumbnail", None)

    exif_dict["0th"][piexif.ImageIFD.DateTime] = exif_value
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_value
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = exif_value

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, str(path))
