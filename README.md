# Windows Photo Repair Inspector

Windows Photo Repair Inspector is a Windows desktop utility that scans a folder of photos and videos, analyses filename and metadata to reconstruct real capture dates, flags compressed duplicates, and lets you safely preview and apply fixes. The tool never deletes or overwrites content without an explicit approval and can move deleted copies to a recovery folder for easy rollback.

## Features

- Recursive scan of a chosen root folder with support for common photo/video formats (`.jpg`, `.jpeg`, `.png`, `.heic`, `.mp4`, `.mov`).
- Date reconstruction from filenames using rules for common camera, Pixel, and WhatsApp patterns.
- Detection of SD card copy issues based on a configurable "problem date" and tolerance window.
- EXIF extraction to highlight missing or conflicting metadata with the option to write EXIF timestamps from filenames.
- Duplicate grouping by parsed timestamp with size-aware primary/variant selection and optional offers to delete smaller compressed copies.
- WhatsApp and other compressed copies detection without automatic deletion.
- Suspicious groups tab that highlights groups with only compressed/WhatsApp variants.
- Split view UI with sortable grid, live preview pane, planned changes summary, and per-file apply/ignore buttons.
- Safety-first application workflow with explicit checkboxes and global option to move deletions into a `Recovered_Deleted` folder inside the scanned root.
- Human-readable action log per scan stored alongside the media folder (e.g. `photo-fixer-log-YYYYMMDDHHMMSS.txt`).

## Building

The solution targets **.NET 8 (Windows)** and uses WPF. Open the `WindowsPhotoRepairInspector.sln` solution in Visual Studio 2022 (or newer) on Windows with the .NET Desktop development workload installed, restore NuGet packages, and build.

## Running

1. Launch the application.
2. Click **Scan folder...** and choose the root directory that contains your media. The scan walks all subfolders.
3. Review the proposed actions in the grid. Files that require attention are highlighted. Use the dropdown to adjust the action per file. Smaller duplicates default to **No change** so you must opt-in to remove them.
4. Inspect the right-hand preview to confirm the actual media, proposed metadata changes, duplicate details, and planned log entry.
5. Use **Apply selected changes** to execute the queued operations, or apply/ignore a single file directly from the preview pane. All operations are logged and, if configured, deletions are moved into the recovery folder to stay reversible.

## Configuration

The top toolbar lets you adjust:

- **Problem date** and **Tolerance**: identifies files copied on a known "bad" date and offers to rewrite their file timestamps from the filename.
- **Auto-group by parsed date**: toggles duplicate grouping.
- **Show only items with changes**: filters the grid to focus on actionable items.
- **Move deleted files to Recovered_Deleted**: enables the safety net for deletions.

Additional defaults (size ratio for compressed copies, supported extensions, recycle folder name, etc.) live in `Models/AppConfig.cs` and can be tailored if needed.
