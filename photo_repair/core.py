"""Pure, platform-independent logic for media timestamp inspection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".webp",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".webm",
}

SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
WRITABLE_TAKEN_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass
class MediaRecord:
    name: str
    size_bytes: int
    created: str
    modified: str
    taken: str
    filename_date: str
    path: str
    media_type: str
    created_ts: float
    modified_ts: float
    taken_ts: Optional[float]
    filename_ts: Optional[float]
    issues: tuple[str, ...] = ()
    proposed_taken: Optional[str] = None


def format_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def format_timestamp(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return ""


def parse_timestamp(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def _valid_datetime(parts: tuple[str, str, str, str, str, str]) -> Optional[datetime]:
    try:
        year, month, day, hour, minute, second = map(int, parts)
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def extract_fb_epoch_from_filename(filename: str) -> Optional[tuple[str, float]]:
    """Return an epoch-like token and timestamp from common social-media filenames."""
    stem = Path(filename).stem
    for token in re.findall(r"(?<!\d)\d{10}(?:\d{3})?(?!\d)", stem):
        seconds = float(int(token)) if len(token) == 10 else float(int(token)) / 1000.0
        try:
            dt = datetime.fromtimestamp(seconds)
        except (ValueError, OSError, OverflowError):
            continue
        if 2004 <= dt.year <= 2100:
            return token, seconds
    return None


def extract_date_from_filename(filename: str) -> Optional[str]:
    """Infer a local capture timestamp from common camera, phone and export filenames."""
    stem = Path(filename).stem

    full_datetime_patterns = [
        # IMG_20240321_174532, PXL_20240321_174532123, 20240321-174532
        r"(?<!\d)(20\d{2})[-_.]?([01]\d)[-_.]?([0-3]\d)[ _T.-]+([0-2]\d)[.:_-]?([0-5]\d)[.:_-]?([0-5]\d)(?:\d{3})?(?!\d)",
        # Screenshot 2024-03-21 at 17.45.32, WhatsApp-like exports
        r"(?<!\d)(20\d{2})[-_.]([01]\d)[-_.]([0-3]\d).*?([0-2]\d)[.:_-]([0-5]\d)[.:_-]([0-5]\d)(?:\d{3})?(?!\d)",
    ]

    for pattern in full_datetime_patterns:
        match = re.search(pattern, stem)
        if not match:
            continue
        dt = _valid_datetime(match.groups())
        if dt is not None:
            return dt.strftime("%Y-%m-%d %H:%M:%S")

    date_patterns = [
        r"(?<!\d)(20\d{2})([-_.]?)(0[1-9]|1[0-2])\2(0[1-9]|[12]\d|3[01])(?!\d)",
        r"(?<!\d)(0[1-9]|1[0-2])([-_.])(0[1-9]|[12]\d|3[01])\2(20\d{2})(?!\d)",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, stem)
        if not match:
            continue
        groups = match.groups()
        if pattern.startswith("(?<!\\d)(20"):
            year, _, month, day = groups
        else:
            month, _, day, year = groups
        try:
            dt = datetime(int(year), int(month), int(day))
        except ValueError:
            continue
        return dt.strftime("%Y-%m-%d 00:00:00")

    epoch = extract_fb_epoch_from_filename(filename)
    if epoch is not None:
        return format_timestamp(epoch[1])
    return None


def classify_media(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def iter_media_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def derive_proposed_taken(created: str, filename_date: str, taken: str) -> Optional[str]:
    """Return a conservative proposed EXIF capture time when evidence is consistent."""
    if not created or not filename_date or taken:
        return None
    if created[:10] != filename_date[:10]:
        return None
    # If the filename contains a real time, preserve it. For date-only names, the
    # filesystem creation time is more informative than midnight.
    return filename_date if filename_date[11:] != "00:00:00" else created


def detect_issues(record: MediaRecord) -> tuple[str, ...]:
    issues: list[str] = []
    if not record.taken and record.media_type == "image":
        issues.append("Missing Taken At")
    if record.modified_ts > record.created_ts:
        issues.append("Modified > Created")
    elif record.created_ts > record.modified_ts:
        issues.append("Created > Modified")
    if record.taken_ts is not None:
        if record.taken_ts > record.created_ts:
            issues.append("Taken > Created")
        elif record.taken_ts < record.created_ts:
            issues.append("Taken < Created")
    return tuple(issues)
