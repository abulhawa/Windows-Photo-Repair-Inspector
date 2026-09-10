"""Safe timestamp repair operations with backups and audit logging."""

from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

from .core import MediaRecord, format_timestamp
from .metadata import write_taken_metadata
from .windows import set_file_times


class RepairService:
    """Apply repairs only after preserving an original copy of each file."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.backup_root = self.root / ".photo-repair-backups"
        self.log_path = self.root / ".photo-repair-repair-log.csv"

    def _source_timestamp(self, record: MediaRecord, source: str) -> float:
        if source == "created":
            return record.created_ts
        if source == "modified":
            return record.modified_ts
        if source == "taken" and record.taken_ts is not None:
            return record.taken_ts
        if source == "filename" and record.filename_ts is not None:
            return record.filename_ts
        raise ValueError(f"{source.title()} timestamp is not available for {record.name}.")

    def preview_change(self, record: MediaRecord, target: str, source: str) -> tuple[str, str]:
        """Return the displayed before/after values for a proposed repair."""
        timestamp = self._source_timestamp(record, source)
        before = {
            "created": record.created,
            "modified": record.modified,
            "taken": record.taken,
        }.get(target)
        if before is None:
            raise ValueError(f"Unknown repair target: {target}")
        return before or "(missing)", format_timestamp(timestamp)

    def backup_file(self, path: Path) -> Path:
        path = path.resolve()
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Selected file is outside the scanned folder.") from exc

        backup = self.backup_root / relative
        if not backup.exists():
            stats = path.stat()
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            # copy2 preserves modified/access metadata, but Windows creation time is
            # not guaranteed to survive a copy. Restore all three explicitly.
            set_file_times(
                backup,
                created_ts=stats.st_ctime,
                modified_ts=stats.st_mtime,
                accessed_ts=stats.st_atime,
            )
        return backup

    def _append_log(
        self,
        *,
        path: Path,
        operation: str,
        before: str,
        after: str,
        backup: Path | None,
        status: str,
    ) -> None:
        exists = self.log_path.exists()
        with self.log_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if not exists:
                writer.writerow(
                    ["logged_at", "file", "operation", "before", "after", "backup", "status"]
                )
            writer.writerow(
                [
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    str(path),
                    operation,
                    before,
                    after,
                    str(backup) if backup else "",
                    status,
                ]
            )

    def apply(self, record: MediaRecord, target: str, source: str) -> None:
        """Copy the original once, then apply one timestamp repair."""
        path = Path(record.path)
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist.")

        timestamp = self._source_timestamp(record, source)
        before, after = self.preview_change(record, target, source)
        operation = f"Set {target.title()} = {source.title()}"

        backup: Path | None = None
        try:
            original_stats = path.stat()
            backup = self.backup_file(path)
            if target == "created":
                set_file_times(path, created_ts=timestamp)
            elif target == "modified":
                set_file_times(path, modified_ts=timestamp)
            elif target == "taken":
                write_taken_metadata(path, timestamp)
                # Metadata insertion writes the file and would otherwise change its
                # filesystem timestamps. Keep an EXIF-only repair EXIF-only.
                set_file_times(
                    path,
                    created_ts=record.created_ts,
                    modified_ts=record.modified_ts,
                    accessed_ts=original_stats.st_atime,
                )
            else:
                raise ValueError(f"Unknown repair target: {target}")
        except Exception as exc:
            self._append_log(
                path=path,
                operation=operation,
                before=before,
                after=after,
                backup=backup,
                status=f"ERROR: {exc}",
            )
            raise

        self._append_log(
            path=path,
            operation=operation,
            before=before,
            after=after,
            backup=backup,
            status="OK",
        )
