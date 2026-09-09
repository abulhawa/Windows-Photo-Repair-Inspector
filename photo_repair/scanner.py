"""Media collection scanning."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .core import (
    MediaRecord,
    classify_media,
    detect_issues,
    derive_proposed_taken,
    extract_date_from_filename,
    format_timestamp,
    iter_media_files,
    parse_timestamp,
)
from .metadata import get_exif_taken_date

_BACKUP_DIR_NAME = ".photo-repair-backups"


def scan_file(path: Path) -> MediaRecord:
    stats = path.stat()
    media_type = classify_media(path)
    taken = get_exif_taken_date(path) if media_type == "image" else None
    taken = taken or ""
    filename_date = extract_date_from_filename(path.name) or ""

    record = MediaRecord(
        name=path.name,
        size_bytes=stats.st_size,
        created=format_timestamp(stats.st_ctime),
        modified=format_timestamp(stats.st_mtime),
        taken=taken,
        filename_date=filename_date,
        path=str(path),
        media_type=media_type,
        created_ts=stats.st_ctime,
        modified_ts=stats.st_mtime,
        taken_ts=parse_timestamp(taken),
        filename_ts=parse_timestamp(filename_date),
        proposed_taken=derive_proposed_taken(
            format_timestamp(stats.st_ctime), filename_date, taken
        ),
    )
    record.issues = detect_issues(record)
    return record


def iter_scannable_paths(root: Path) -> Iterable[Path]:
    for path in iter_media_files(root):
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            relative_parts = path.parts
        if _BACKUP_DIR_NAME in relative_parts:
            continue
        yield path


def scan_directory(root: Path) -> list[MediaRecord]:
    records: list[MediaRecord] = []
    for path in iter_scannable_paths(root):
        try:
            records.append(scan_file(path))
        except (OSError, ValueError):
            continue
    return records
