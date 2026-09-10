# Photo Metadata Repair Inspector

A Windows desktop utility for inspecting inconsistent photo and media timestamps and repairing them with explicit backups and an audit trail.

Photo collections copied between computers, restored from backups, downloaded from social platforms, or migrated between services often end up with conflicting dates. The filesystem may say one thing, EXIF metadata another, while the original filename still contains the capture date. This tool puts those signals side by side, identifies conditions worth reviewing, and provides controlled repair actions.

## What it inspects

For each supported media file the application compares:

- Windows filesystem **Created** timestamp
- Windows filesystem **Modified** timestamp
- EXIF **Taken At** timestamp when available
- Capture timestamps inferred from common camera, phone, screenshot, and social-media filenames

The **Review** view is deliberately conservative. It currently highlights:

- missing EXIF `Taken At` on JPEG files, where the application can actually repair it
- `Taken > Created`
- `Taken > Modified`

Normal filesystem ordering is not treated as an error. `Modified > Created` is expected after editing a file. `Created > Modified` is common after copying a file while preserving its older modification timestamp, and `Taken < Created` is normal when an older photo is imported onto a newer filesystem.

Timestamp comparisons use a one-second tolerance so sub-second filesystem precision does not create review items that appear identical in the UI.

## Scanning

Media metadata is read concurrently with a bounded worker pool to keep scans responsive without overwhelming storage. During a scan the interface shows:

- exact processed and total file counts
- percentage complete
- elapsed time
- estimated remaining time once enough samples are available for a useful estimate
- a **Stop** control for cooperative cancellation

Stopping a metadata scan cancels queued work and allows currently active metadata reads to finish cleanly. Any already completed records can be shown as partial results. If scanning is stopped before metadata processing begins, the previous collection remains loaded.

## Repair workflow

Repair selection is explicit and does not depend on knowing Windows multi-select shortcuts. The **Review** table has a checkbox column for choosing which files belong to the repair batch, together with **Select all visible** and **Clear selection** controls.

After selecting files:

1. Choose a repair method from the **Repair method** dropdown.
2. Review the selected-file count.
3. Press **Apply repair**.
4. Confirm the operation before any file is changed.

The Apply button remains disabled until both a repair method and at least one file have been selected.

## Repair safety

Repairs modify the selected file in place, but the application first preserves the original under:

```text
.photo-repair-backups/
```

inside the scanned folder. Existing backups are not overwritten, so the first-seen original remains available.

Every attempted repair is also appended to:

```text
.photo-repair-repair-log.csv
```

with the file path, operation, before/after values, backup location, and status.

EXIF writes are deliberately conservative. If existing EXIF metadata cannot be parsed safely, the application refuses the write rather than replacing the metadata with a new empty EXIF block. EXIF-only repairs also restore the original filesystem Created, Modified, and Accessed timestamps after the metadata write.

> Keep an independent backup of important photo collections. This utility changes file metadata and filesystem timestamps by design.

## Supported media

The scanner recognizes common image formats including JPEG, PNG, BMP, GIF, TIFF, HEIC/HEIF, and WebP, plus common video formats such as MP4, MOV, AVI, MKV, WMV, M4V, MPEG, 3GP, and WebM.

EXIF capture-time reading is format-dependent. HEIC/HEIF reading is enabled through `pillow-heif`.

Writing `Taken At` metadata is intentionally limited to JPEG files. TIFF can be inspected but is not modified because the current EXIF writer does not safely support in-place TIFF insertion. Video files are currently inspected using filesystem and filename timestamps only.

## Filename timestamp inference

The parser recognizes common patterns such as:

```text
IMG_20240321_174532.jpg
PXL_20240321_174532.jpg
Screenshot 2024-03-21 at 17.45.32.png
holiday_2024-03-21.jpg
holiday_03-21-2024.jpg
```

It also recognizes plausible 10-digit and 13-digit Unix epoch values embedded in social-media export filenames.

Date-only filenames are treated conservatively: when the filename date agrees with the Windows creation date, the creation time is preferred over inventing a midnight capture time.

## Installation

Requirements:

- Windows 10 or 11
- Python 3.10+

Clone the repository and install it in editable mode:

```bash
git clone https://github.com/abulhawa/Windows-Photo-Repair-Inspector.git
cd Windows-Photo-Repair-Inspector
python -m pip install -e .
```

Run it with either:

```bash
python main.py
```

or:

```bash
photo-repair-inspector
```

A plain requirements file is also included:

```bash
python -m pip install -r requirements.txt
```

## Workflow

1. Click **Scan Folder…** and select a media collection.
2. Follow the live progress indicator, or click **Stop** to cancel the current scan.
3. Browse all detected files in **Library**.
4. Open **Review** to see only conditions worth checking or repairing.
5. Filter the review list if needed.
6. Select files using the checkbox column, or use **Select all visible**.
7. Choose a repair method from the dropdown.
8. Press **Apply repair** and confirm the operation.
9. Review the resulting CSV audit trail under **Repair Log**.

## Project structure

```text
.
├── main.py                 # small application entry point
├── photo_repair/
│   ├── app.py              # Tkinter UI and scan orchestration
│   ├── core.py             # timestamp parsing and review detection
│   ├── metadata.py         # EXIF reading/writing
│   ├── repair.py           # backup, repair and audit-log service
│   ├── scanner.py          # concurrent, cancellable media scanning
│   └── windows.py          # Windows FILETIME operations
├── tests/
│   ├── test_core.py
│   ├── test_metadata.py
│   └── test_scanner.py
├── .github/workflows/
│   └── tests.yml
├── pyproject.toml
└── requirements.txt
```

The parsing and review logic is kept independent of Tkinter and Windows APIs so it can be unit tested directly.

## Tests

Install development dependencies and run:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

GitHub Actions runs the test suite on both Windows and Linux and also compiles the package to catch syntax/import regressions.

## Current limitations

- The application is Windows-only because filesystem creation-time repair uses the Windows API.
- EXIF `Taken At` writes are limited to JPEG.
- RAW camera formats are not currently supported.
- The tool does not infer timezone offsets that are absent from source metadata.
- Backups can consume significant disk space when many large files are repaired.
