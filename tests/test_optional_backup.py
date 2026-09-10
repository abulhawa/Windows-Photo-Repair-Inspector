from datetime import datetime

from photo_repair.core import MediaRecord
from photo_repair.repair import RepairService
import photo_repair.repair as repair_module


def make_record(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"test")
    created_ts = datetime(2024, 3, 21, 18, 0, 0).timestamp()
    modified_ts = datetime(2024, 3, 21, 19, 0, 0).timestamp()
    return MediaRecord(
        name=path.name,
        size_bytes=4,
        created="2024-03-21 18:00:00",
        modified="2024-03-21 19:00:00",
        taken="",
        filename_date="",
        path=str(path),
        media_type="image",
        created_ts=created_ts,
        modified_ts=modified_ts,
        taken_ts=None,
        filename_ts=None,
    )


def test_apply_can_skip_backup_but_still_logs(tmp_path, monkeypatch):
    calls = []

    def fake_set_file_times(path, **kwargs):
        calls.append((path, kwargs))

    monkeypatch.setattr(repair_module, "set_file_times", fake_set_file_times)

    service = RepairService(tmp_path)
    record = make_record(tmp_path)
    service.apply(record, "created", "modified", create_backup=False)

    assert calls
    assert not service.backup_root.exists()
    log_text = service.log_path.read_text(encoding="utf-8")
    assert "OK (no backup)" in log_text


def test_backup_remains_enabled_by_default(tmp_path, monkeypatch):
    def fake_set_file_times(path, **kwargs):
        return None

    monkeypatch.setattr(repair_module, "set_file_times", fake_set_file_times)

    service = RepairService(tmp_path)
    record = make_record(tmp_path)
    service.apply(record, "created", "modified")

    assert (service.backup_root / "photo.jpg").exists()
    log_text = service.log_path.read_text(encoding="utf-8")
    assert "OK" in log_text
