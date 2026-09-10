# Photo Metadata Repair Inspector

A Windows desktop utility for inspecting inconsistent photo and media timestamps and repairing them with explicit confirmation, optional backups, and an audit trail.

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

The internal `.photo-repair-backups` directory is excluded from scanning, so recovery copies do not reappear as duplicate media records on later scans.

## Interface

The desktop UI is intentionally compact so the media table remains the main part of the window.

- A small top toolbar contains the scanned folder, scan controls, filename/path search, and media-type filter.
- **Library**, **Review**, and **Repair log** remain separate tabs.
- The Location column shows only the containing folder because the filename already has its own column.
- Column headers are sortable, including Created, Modified, Taken At, Filename Date, Review reason, size, type, file, and location.
- Search filters by filename or full path and applies to both Library and Review.
- Review supports checkboxes, Ctrl-click, Shift-click, **Select all**, and **Clear** using one shared selection state.
- Right-clicking a file exposes open, Explorer, path-copy, and repair-selection actions.
- Repair controls stay in a compact action bar under the Review table instead of occupying a large panel.

## Repair workflow

After selecting files:

1. Choose a repair method from the **Repair** dropdown.
2. Decide whether **Backup originals** should remain enabled. It is enabled by default.
3. Press **Review changes…**.
4. Inspect the preview dialog showing the action, counts, backup status, and up to the first 10 before/after examples.
5. Confirm with **Apply N changes**.

The preview deliberately does not enumerate every file in a large batch. For example, a 1,000-file repair shows summary counts and a limited sample rather than creating an unusable confirmation dialog.

Files that already match the requested value or cannot provide the selected source timestamp are skipped rather than modified unnecessarily.

## What happens after a repair

Each successfully changed file is rescanned immediately. The in-memory record is replaced with the metadata now present on disk, so Created, Modified, Taken At, Filename Date, review reasons, and other displayed values update without requiring a complete folder rescan.

If the repair resolves the file's final review condition, that file disappears from **Review** but remains visible in **Library** with its updated values. If another review condition still applies, it remains in Review with the new metadata.

## Repair safety

Repairs always modify the selected file in place. By default, the application first preserves the original under:

```text
.photo-repair-backups/
```

inside the scanned folder. Existing backups are not overwritten, so the first pre-repair original remains available even if the same file is repaired again later.

Backup creation can be disabled for users who explicitly want an in-place change without a recovery copy. When backup is disabled, the preview dialog clearly states that no recovery copy will be created by the application.

Every attempted repair is appended to:

```text
.photo-repair-repair-log.csv
```

with the file path, operation, before/after values, backup location when applicable, and status. Repairs performed without a backup are marked accordingly in the log.

EXIF writes are deliberately conservative. If existing EXIF metadata cannot be parsed safely, the application refuses the write rather than replacing the metadata with a new empty EXIF block. EXIF-only repairs also restore the original filesystem Created, Modified, and Accessed timestamps after the metadata write.

> Keep an independent backup of important photo collections. Disabling the built-in backup removes the application's recovery copy for that repair.

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

## Project structure

```text
.
├── main.py                 # application entry point
├── photo_repair/
│   ├── app.py              # compatibility entry point
│   ├── ui.py               # Tkinter UI and scan orchestration
│   ├── core.py             # timestamp parsing and review detection
│   ├── metadata.py         # EXIF reading/writing
│   ├── repair.py           # backup, preview, repair and audit-log service
│   ├── scanner.py          # concurrent, cancellable media scanning
│   └── windows.py          # Windows FILETIME operations
├── tests/
│   ├── test_core.py
│   ├── test_metadata.py
│   ├── test_optional_backup.py
│   ├── test_repair_preview.py
│   ├── test_scanner.py
│   ├── test_selection.py
│   └── test_ui_helpers.py
├── .github/workflows/
│   └── tests.yml
├── pyproject.toml
└── requirements.txt
```

The parsing, selection-range, search, and sort logic are kept testable independently of running the full Windows GUI.

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
- If backup creation is disabled, the application does not create a recovery copy for that repair.
