"""Image metadata readers and writers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

import piexif
from PIL import ExifTags, Image

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


def _format_exif_datetime(value: Any) -> Optional[str]:
    """Normalize an EXIF date value to the application's timestamp format."""
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    # Standard EXIF dates use YYYY:MM:DD HH:MM:SS. Only the first two colons
    # belong to the date; time colons must remain unchanged.
    return value.replace(":", "-", 2)


def _first_datetime(mapping: Mapping[int, Any], tags: tuple[int, ...]) -> Optional[str]:
    for tag in tags:
        value = _format_exif_datetime(mapping.get(tag))
        if value:
            return value
    return None


def get_exif_taken_date(path: Path) -> Optional[str]:
    """Read the best available EXIF capture timestamp without modifying the file.

    Pillow keeps DateTimeOriginal and DateTimeDigitized in the nested Exif IFD
    for many JPEGs. Reading only the top-level EXIF mapping therefore produces
    false negatives, so both the nested IFD and top-level mapping are checked.
    """
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            if not exif:
                return None

            # DateTimeOriginal and DateTimeDigitized normally live in the Exif
            # sub-IFD referenced by tag 34665. Pillow exposes it via get_ifd().
            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except (AttributeError, KeyError, TypeError, ValueError, OSError):
                exif_ifd = {}

            if exif_ifd:
                taken = _first_datetime(
                    exif_ifd,
                    (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _DATETIME),
                )
                if taken:
                    return taken

            # Some encoders flatten capture-date tags or only provide the 0th
            # IFD DateTime value, so keep a top-level fallback.
            return _first_datetime(
                exif,
                (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _DATETIME),
            )
    except (OSError, ValueError):
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
