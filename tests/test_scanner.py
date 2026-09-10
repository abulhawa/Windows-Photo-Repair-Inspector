import threading
import time
from pathlib import Path

from photo_repair import scanner
from photo_repair.core import MediaRecord


def _record_for(path: Path) -> MediaRecord:
    return MediaRecord(
        name=path.name,
        size_bytes=1,
        created="2024-01-01 00:00:00",
        modified="2024-01-01 00:00:00",
        taken="",
        filename_date="",
        path=str(path),
        media_type="image",
        created_ts=0.0,
        modified_ts=0.0,
        taken_ts=None,
        filename_ts=None,
    )


def _make_jpegs(root: Path, count: int) -> None:
    for index in range(count):
        (root / f"photo_{index:03d}.jpg").write_bytes(b"x")


def test_scan_directory_reports_exact_progress(tmp_path, monkeypatch):
    _make_jpegs(tmp_path, 5)

    def fake_scan(path, cancel_event=None):
        return _record_for(path)

    monkeypatch.setattr(scanner, "_safe_scan_file", fake_scan)
    updates = []

    records = scanner.scan_directory(
        tmp_path,
        progress_callback=lambda completed, total: updates.append((completed, total)),
    )

    assert len(records) == 5
    assert updates[0] == (0, 5)
    assert updates[-1] == (5, 5)
    assert [completed for completed, _ in updates] == [0, 1, 2, 3, 4, 5]


def test_scan_directory_returns_partial_results_after_cancel(tmp_path, monkeypatch):
    _make_jpegs(tmp_path, 30)
    cancel_event = threading.Event()

    def fake_scan(path, cancel_event=None):
        time.sleep(0.01)
        if cancel_event is not None and cancel_event.is_set():
            return None
        return _record_for(path)

    monkeypatch.setattr(scanner, "_safe_scan_file", fake_scan)
    updates = []

    def on_progress(completed, total):
        updates.append((completed, total))
        if completed >= 3:
            cancel_event.set()

    records = scanner.scan_directory(
        tmp_path,
        cancel_event=cancel_event,
        progress_callback=on_progress,
    )

    assert cancel_event.is_set()
    assert updates[0] == (0, 30)
    assert 1 <= len(records) < 30
    assert updates[-1][0] < 30


def test_scan_can_be_cancelled_before_metadata_work(tmp_path, monkeypatch):
    _make_jpegs(tmp_path, 5)
    cancel_event = threading.Event()
    cancel_event.set()

    called = False

    def fake_scan(path, cancel_event=None):
        nonlocal called
        called = True
        return _record_for(path)

    monkeypatch.setattr(scanner, "_safe_scan_file", fake_scan)
    updates = []

    records = scanner.scan_directory(
        tmp_path,
        cancel_event=cancel_event,
        progress_callback=lambda completed, total: updates.append((completed, total)),
    )

    assert records == []
    assert called is False
    assert updates == [(0, 0)]
