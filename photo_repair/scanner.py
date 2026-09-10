"""Media collection scanning."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional

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
_MAX_SCAN_WORKERS = 8


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


def _safe_scan_file(path: Path) -> Optional[MediaRecord]:
    """Scan one file while isolating ordinary per-file read failures."""
    try:
        return scan_file(path)
    except (OSError, ValueError):
        return None


def _scan_worker_count(file_count: int) -> int:
    """Choose a conservative number of workers for metadata-heavy I/O."""
    if file_count <= 1:
        return 1
    cpu_hint = os.cpu_count() or 2
    return min(_MAX_SCAN_WORKERS, file_count, max(2, cpu_hint))


def scan_directory(root: Path) -> list[MediaRecord]:
    """Scan media metadata concurrently while preserving discovery order.

    Image inspection is dominated by short filesystem and metadata reads rather
    than CPU-heavy image decoding. A bounded thread pool allows those reads to
    overlap on modern storage without spawning an excessive number of workers.
    """
    paths = list(iter_scannable_paths(root))
    if not paths:
        return []

    workers = _scan_worker_count(len(paths))
    if workers == 1:
        record = _safe_scan_file(paths[0])
        return [record] if record is not None else []

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="photo-scan") as executor:
        results = executor.map(_safe_scan_file, paths)
        return [record for record in results if record is not None]
