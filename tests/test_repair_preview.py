from datetime import datetime

import pytest

from photo_repair.core import MediaRecord
from photo_repair.repair import RepairService


def make_record(tmp_path, **overrides):
    created_ts = datetime(2024, 3, 21, 18, 0, 0).timestamp()
    modified_ts = datetime(2024, 3, 21, 19, 0, 0).timestamp()
    filename_ts = datetime(2024, 3, 21, 17, 45, 32).timestamp()
    values = dict(
        name="IMG_20240321_174532.jpg",
        size_bytes=100,
        created="2024-03-21 18:00:00",
        modified="2024-03-21 19:00:00",
        taken="",
        filename_date="2024-03-21 17:45:32",
        path=str(tmp_path / "IMG_20240321_174532.jpg"),
        media_type="image",
        created_ts=created_ts,
        modified_ts=modified_ts,
        taken_ts=None,
        filename_ts=filename_ts,
    )
    values.update(overrides)
    return MediaRecord(**values)


def test_preview_change_shows_missing_taken_and_filename_value(tmp_path):
    service = RepairService(tmp_path)
    record = make_record(tmp_path)

    before, after = service.preview_change(record, "taken", "filename")

    assert before == "(missing)"
    assert after == "2024-03-21 17:45:32"


def test_preview_change_uses_existing_target_value(tmp_path):
    service = RepairService(tmp_path)
    record = make_record(tmp_path)

    before, after = service.preview_change(record, "created", "filename")

    assert before == "2024-03-21 18:00:00"
    assert after == "2024-03-21 17:45:32"


def test_preview_change_rejects_unavailable_source(tmp_path):
    service = RepairService(tmp_path)
    record = make_record(tmp_path)

    with pytest.raises(ValueError, match="Taken timestamp is not available"):
        service.preview_change(record, "created", "taken")
