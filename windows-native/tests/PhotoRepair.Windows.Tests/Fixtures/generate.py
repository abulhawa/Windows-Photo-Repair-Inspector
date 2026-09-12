"""Regenerate synthetic 12x12 JPEGs: uv run python <this file>. No personal media."""
from pathlib import Path
from PIL import Image
import piexif

root = Path(__file__).parent
for name, original, digitized, fallback in [
    ("nested", True, True, True),
    ("digitized", False, True, True),
    ("fallback", False, False, True),
    ("empty", False, False, False),
]:
    exif = {"0th": {}, "Exif": {}}
    if original:
        exif["Exif"][36867] = b"2024:03:21 17:45:32"
    if digitized:
        exif["Exif"][36868] = b"2024:03:21 17:45:33"
    if fallback:
        exif["0th"][306] = b"2024:03:21 18:00:00"
    Image.new("RGB", (12, 12), "white").save(root / f"{name}.jpg", exif=piexif.dump(exif))
