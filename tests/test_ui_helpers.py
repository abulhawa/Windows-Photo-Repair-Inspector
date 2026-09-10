from datetime import datetime

from photo_repair.core import MediaRecord
from photo_repair.ui import _record_matches_search, _record_sort_value


def make_record(**overrides):
    created_ts = datetime(2024, 1, 2, 10, 0, 0).timestamp()
    modified_ts = datetime(2024, 1, 3, 10, 0, 0).timestamp()
    values = dict(
        name="Example Photo.jpg",
        size_bytes=1024,
        created="2024-01-02 10:00:00",
        modified="2024-01-03 10:00:00",
        taken="2024-01-01 09:00:00",
        filename_date="2024-01-01 09:00:00",
        path="Pictures/Trips/Example Photo.jpg",
        media_type="image",
        created_ts=created_ts,
        modified_ts=modified_ts,
        taken_ts=datetime(2024, 1, 1, 9, 0, 0).timestamp(),
        filename_ts=datetime(2024, 1, 1, 9, 0, 0).timestamp(),
        issues=("Taken > Modified",),
    )
    values.update(overrides)
    return MediaRecord(**values)


def test_search_matches_filename_case_insensitively():
    record = make_record()
    assert _record_matches_search(record, "example photo")


def test_search_matches_folder_path():
    record = make_record()
    assert _record_matches_search(record, "trips")


def test_search_rejects_unrelated_text():
    record = make_record()
    assert not _record_matches_search(record, "documents")


def test_sort_created_uses_numeric_timestamp():
    record = make_record()
    assert _record_sort_value(record, "created") == record.created_ts


def test_sort_location_uses_containing_folder_only():
    record = make_record()
    location = _record_sort_value(record, "path")
    assert "example photo.jpg" not in location
    assert "pictures" in location
