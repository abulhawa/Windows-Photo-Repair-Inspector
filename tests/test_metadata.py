from datetime import datetime

import piexif
import pytest
from PIL import Image

from photo_repair import metadata
from photo_repair.metadata import write_taken_metadata


def test_write_taken_preserves_existing_exif(tmp_path):
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (12, 12), "white").save(path)

    exif = {
        "0th": {
            piexif.ImageIFD.Artist: b"Original Artist",
            piexif.ImageIFD.DateTime: b"2020:01:02 03:04:05",
        },
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2020:01:02 03:04:05"},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    piexif.insert(piexif.dump(exif), str(path))

    timestamp = datetime(2024, 3, 21, 17, 45, 32).timestamp()
    write_taken_metadata(path, timestamp)

    result = piexif.load(str(path))
    assert result["0th"][piexif.ImageIFD.Artist] == b"Original Artist"
    assert result["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:03:21 17:45:32"
    assert result["Exif"][piexif.ExifIFD.DateTimeDigitized] == b"2024:03:21 17:45:32"


def test_write_refuses_to_replace_unreadable_exif(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (12, 12), "white").save(path)
    original_bytes = path.read_bytes()

    def fail_load(_):
        raise ValueError("bad metadata")

    monkeypatch.setattr(metadata.piexif, "load", fail_load)

    with pytest.raises(ValueError, match="refusing to overwrite"):
        write_taken_metadata(path, datetime(2024, 3, 21, 17, 45, 32).timestamp())

    assert path.read_bytes() == original_bytes
