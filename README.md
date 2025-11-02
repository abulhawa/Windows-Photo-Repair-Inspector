# Photo Metadata Viewer

A lightweight Python GUI for quickly inspecting the key timestamps associated with your photos. Point the app at any folder and it will list every supported media file together with the filesystem **Created At** and **Modified At** values, plus the EXIF **Taken At** timestamp whenever available.

## Requirements

- Python 3.9 or newer
- `tkinter` (bundled with most Python distributions)
- [`Pillow`](https://python-pillow.org/) to read EXIF metadata. Install with:

  ```bash
  pip install pillow
  ```

- [`piexif`](https://github.com/hMatoba/Piexif) for the **Taken At Fixes** tab.

The application still runs without Pillow, but the **Taken At** column will remain blank.

## Usage

```bash
python main.py
```

1. Click **Scan Folder…** and choose the directory that contains your photos.
2. Wait for the scan to finish; the status bar shows progress and the number of discovered files.
3. Browse the results in the table. Columns are sortable—just click the heading you want to sort by.

Supported extensions include: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.gif`, `.tiff`, `.heic`, `.webp`, `.raw`.

## Notes

- Scans run on a background thread to keep the UI responsive; large collections may still take time.
- The **Taken At Fixes** tab lists files missing EXIF capture timestamps where the filename-derived date matches the filesystem creation date. Apply fixes to write that timestamp back into the photo (JPEG/TIFF only, requires `piexif`). Use the per-tab fix buttons (including the Taken At tab) to align Created/Modified/Taken timestamps or copy them from filename-derived dates.
- Dedicated tabs flag files where `Modified` and `Created` timestamps disagree, as well as photos whose EXIF `Taken At` diverges from file creation, making it easy to audit anomalies.
- Files the app cannot read (permission issues, corrupt metadata, unsupported formats) are skipped silently to avoid interrupting your review.
- Selection banners above each tab list how many files are currently selected so you know which items will be affected by fixes.
- On Windows, the app requests DPI awareness to look crisp on high-resolution displays.

