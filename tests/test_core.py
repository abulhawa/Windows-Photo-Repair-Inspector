from datetime import datetime
from pathlib import Path

from photo_repair.core import (
    MediaRecord,
    classify_media,
    derive_proposed_taken,
    detect_issues,
    extract_date_from_filename,
    extract_fb_epoch_from_filename,
    parse_timestamp,
)


def make_record(**overrides):
    values = dict(
        name="IMG_20240321_174532.jpg",
        size_bytes=100,
        created="2024-03-21 18:00:00",
        modified="2024-03-21 18:00:00",
        taken="2024-03-21 17:45:32",
        filename_date="2024-03-21 17:45:32",
        path=r"C:\photos\IMG_20240321_174532.jpg",
        media_type="image",
        created_ts=parse_timestamp("2024-03-21 18:00:00"),
        modified_ts=parse_timestamp("2024-03-21 18:00:00"),
        taken_ts=parse_timestamp("2024-03-21 17:45:32"),
        filename_ts=parse_timestamp("2024-03-21 17:45:32"),
    )
    values.update(overrides)
    return MediaRecord(**values)


def test_extract_camera_datetime():
    assert extract_date_from_filename("IMG_20240321_174532.jpg") == "2024-03-21 17:45:32"


def test_extract_pixel_datetime():
    assert extract_date_from_filename("PXL_20240321_174532123.jpg") == "2024-03-21 17:45:32"


def test_extract_screenshot_datetime():
    assert (
        extract_date_from_filename("Screenshot 2024-03-21 at 17.45.32.png")
        == "2024-03-21 17:45:32"
    )


def test_extract_date_only_uses_midnight():
    assert extract_date_from_filename("holiday_2024-03-21.jpg") == "2024-03-21 00:00:00"


def test_extract_us_date_only():
    assert extract_date_from_filename("holiday_03-21-2024.jpg") == "2024-03-21 00:00:00"


def test_invalid_calendar_date_is_rejected():
    assert extract_date_from_filename("IMG_20240231.jpg") is None


def test_facebook_epoch_detection():
    result = extract_fb_epoch_from_filename("12345_1711043132_67890.jpg")
    assert result is not None
    token, timestamp = result
    assert token == "1711043132"
    assert datetime.fromtimestamp(timestamp).year == 2024


def test_millisecond_epoch_detection():
    result = extract_fb_epoch_from_filename("photo_1711043132000.jpg")
    assert result is not None
    token, timestamp = result
    assert token == "1711043132000"
    assert datetime.fromtimestamp(timestamp).year == 2024


def test_tif_is_an_image():
    assert classify_media(Path("photo.tif")) == "image"


def test_date_only_proposal_prefers_creation_time():
    assert (
        derive_proposed_taken(
            "2024-03-21 18:00:00", "2024-03-21 00:00:00", ""
        )
        == "2024-03-21 18:00:00"
    )


def test_full_filename_time_is_preserved_in_proposal():
    assert (
        derive_proposed_taken(
            "2024-03-21 18:00:00", "2024-03-21 17:45:32", ""
        )
        == "2024-03-21 17:45:32"
    )


def test_proposal_requires_matching_dates():
    assert (
        derive_proposed_taken(
            "2024-03-22 18:00:00", "2024-03-21 17:45:32", ""
        )
        is None
    )


def test_existing_taken_timestamp_disables_proposal():
    assert (
        derive_proposed_taken(
            "2024-03-21 18:00:00",
            "2024-03-21 17:45:32",
            "2024-03-21 17:00:00",
        )
        is None
    )


def test_detect_missing_taken():
    record = make_record(taken="", taken_ts=None)
    assert "Missing Taken At" in detect_issues(record)


def test_detect_taken_before_created():
    record = make_record()
    assert "Taken < Created" in detect_issues(record)


def test_detect_modified_after_created():
    record = make_record(
        modified="2024-03-21 19:00:00",
        modified_ts=parse_timestamp("2024-03-21 19:00:00"),
    )
    assert "Modified > Created" in detect_issues(record)
