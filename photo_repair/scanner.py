"""Media collection scanning."""

from __future__ import annotations

import os
import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional

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
ProgressCallback = Callable[[int, int], None]


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


def iter_scannable_paths(
    root: Path,
    cancel_event: Optional[threading.Event] = None,
) -> Iterable[Path]:
    """Yield supported files, stopping discovery promptly when requested."""
    for path in iter_media_files(root):
        if cancel_event is not None and cancel_event.is_set():
            break
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            relative_parts = path.parts
        if _BACKUP_DIR_NAME in relative_parts:
            continue
        yield path


def _safe_scan_file(
    path: Path,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[MediaRecord]:
    """Scan one file while isolating ordinary per-file read failures."""
    if cancel_event is not None and cancel_event.is_set():
        return None
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


def scan_directory(
    root: Path,
    *,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> list[MediaRecord]:
    """Scan media metadata concurrently with cancellation and progress reporting.

    File discovery is performed first so the caller receives an exact total. Metadata
    reads then run in a bounded thread pool. Results are returned in discovery order,
    even though individual files finish out of order. If cancellation is requested,
    pending work is cancelled and already completed records are returned.
    """
    paths = list(iter_scannable_paths(root, cancel_event))
    total = len(paths)
    if progress_callback is not None:
        progress_callback(0, total)

    if not paths or (cancel_event is not None and cancel_event.is_set()):
        return []

    workers = _scan_worker_count(total)
    ordered_records: list[Optional[MediaRecord]] = [None] * total
    completed = 0

    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="photo-scan",
    ) as executor:
        futures = {
            executor.submit(_safe_scan_file, path, cancel_event): index
            for index, path in enumerate(paths)
        }

        for future in as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                for pending in futures:
                    pending.cancel()
                break

            index = futures[future]
            try:
                record = future.result()
            except CancelledError:
                continue

            if record is not None:
                ordered_records[index] = record
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, total)

    return [record for record in ordered_records if record is not None]
