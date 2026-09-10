# Native Windows migration plan

Status: architecture contract for the C# / WinUI 3 implementation.

The existing Python application is the behavioral reference implementation. The native Windows application should reach parity with it before we change product semantics or reorganize the repository.

## Goal

Build a native Windows edition of Photo Metadata Repair Inspector using C#, .NET and WinUI 3, packaged as MSIX for Microsoft Store distribution. Keep the Python implementation as the basis for a later macOS/Linux edition.

This is a port of established behavior, not a greenfield redesign of the repair rules.

## Why WinUI 3

Microsoft currently recommends the Windows App SDK for new Windows desktop applications. WinUI 3 projects are packaged as MSIX by default and current tooling supports C# with .NET 10. For the Store edition, use a packaged WinUI 3 app rather than wrapping the Python executable.

Implementation should pin a stable Windows App SDK version rather than floating on previews.

Official references:

- https://learn.microsoft.com/windows/apps/get-started/winui-get-started-overview
- https://learn.microsoft.com/windows/apps/package-and-deploy/
- https://learn.microsoft.com/windows/apps/package-and-deploy/packaging/

## Repository strategy

Do not move the Python application yet. Add the native implementation under `windows-native/` until it reaches parity and is independently releasable.

Proposed structure:

```text
.
├── photo_repair/                         # existing Python implementation
├── tests/                                # existing Python tests
├── spec/
│   └── behavior-contract.json            # language-neutral parity cases
├── windows-native/
│   ├── PhotoRepair.sln
│   ├── src/
│   │   ├── PhotoRepair.App/              # WinUI 3 UI, app lifecycle, MSIX identity
│   │   ├── PhotoRepair.Core/             # pure domain logic, no Windows APIs
│   │   └── PhotoRepair.Windows/          # filesystem, EXIF/WIC, shell integration
│   └── tests/
│       ├── PhotoRepair.Core.Tests/
│       └── PhotoRepair.Windows.Tests/
└── docs/
    └── windows-native-migration.md
```

After parity, we can rename the repository to `Photo-Metadata-Repair-Inspector` and decide whether the Python implementation should move under a `python/` directory. Do not combine that structural migration with the initial native port.

## Project boundaries

### PhotoRepair.Core

Must remain platform-independent and unit-testable without WinUI or Windows filesystem calls.

Responsibilities:

- `MediaRecord` domain model
- media extension classification
- filename date/time inference
- Unix epoch filename inference
- review-rule evaluation
- repair method definitions
- repair planning and preview values
- selection-range behavior
- search/sort helpers where they are not UI-specific

Use `DateTimeOffset` or an equivalent explicit representation at API boundaries. The current Python implementation interprets filename timestamps as local wall-clock values. Preserve displayed behavior during parity work and do not silently introduce timezone conversion.

### PhotoRepair.Windows

Responsibilities:

- read/set filesystem creation, modification and access timestamps
- read photo capture metadata
- conservatively write `Taken At`
- backup creation and timestamp preservation
- audit log persistence
- concurrent/cancellable scanning
- open file / reveal in Explorer integration

For filesystem timestamps, prefer .NET's native `File.GetCreationTime*`, `File.SetCreationTime*`, `File.GetLastWriteTime*`, and `File.SetLastWriteTime*` APIs rather than P/Invoke unless a measured limitation requires otherwise.

For photo metadata, investigate Windows Imaging Component / Windows Property System first. `System.Photo.DateTaken` is a writable Windows photo property and maps to EXIF DateTimeOriginal. The parity release must remain JPEG-write-only even if Windows APIs also support additional containers, because broadening destructive write support is a separate product change.

Official metadata references:

- https://learn.microsoft.com/windows/win32/properties/props-system-photo-datetaken
- https://learn.microsoft.com/windows/win32/wic/-wic-photoprop-system-photo-datetaken
- https://learn.microsoft.com/windows/win32/api/wincodec/nn-wincodec-iwicmetadataquerywriter

Do not use an image library that re-encodes JPEG pixels merely to change EXIF unless there is no safer viable route. A metadata-only repair must not degrade image data.

### PhotoRepair.App

Use WinUI 3 with MVVM-style separation. Business rules must not live in code-behind.

Suggested view model responsibilities:

- folder selection
- scan lifecycle and cancellation
- Library / Review / Repair log collections
- search/filter/sort state
- unified repair selection state
- repair preview command
- apply command and post-repair rescan

The UI can become more native and polished, but the first native milestone should preserve established interaction semantics.

## Behavioral contract to preserve

The machine-readable examples are in `spec/behavior-contract.json`. The C# core tests should load that file where practical so Python and C# are checked against the same examples.

Current timestamp display format:

```text
YYYY-MM-DD HH:MM:SS
```

Current review tolerance: 1 second.

Current review conditions:

- `Missing Taken At` only for JPEG/JPEG images where the application can write it
- `Taken > Created`
- `Taken > Modified`

The following are deliberately not review errors:

- `Modified > Created`
- `Created > Modified`
- `Taken < Created`

Current repair methods:

- Set Taken At from filename
- Set Taken At from Created
- Set Created from Taken At
- Set Created from filename
- Set Modified from Taken At
- Set Modified from filename

## Safety invariants

These are release blockers, not optional refinements.

1. No file is modified from the initial table action. The user must first see a dedicated repair preview and explicitly confirm application of the changes.
2. Backup creation defaults to enabled.
3. With backups enabled, preserve the first pre-repair original under `.photo-repair-backups/` using its path relative to the scanned root.
4. Never overwrite an existing backup of the same source path. The backup is the first pre-repair original, not version history.
5. Exclude `.photo-repair-backups` recursively from scans.
6. Every attempted repair is appended to `.photo-repair-repair-log.csv`, including failures and no-backup repairs.
7. Refuse a destructive EXIF write when existing metadata cannot be read safely.
8. A `Taken At` metadata-only repair must restore/preserve filesystem Created, Modified and Accessed timestamps.
9. Skip a repair when the source timestamp is unavailable.
10. Skip a repair when the destination already equals the proposed value.
11. After a successful repair, immediately rescan that file and replace its in-memory record.
12. A repaired file always remains in Library. It leaves Review only if no review issue remains.
13. Repair preview must summarize large batches and show at most 10 before/after examples rather than listing every selected file.
14. Backup-off state must be obvious in the preview before confirmation.
15. Files outside the selected scan root must never be backed up or repaired through a record associated with that scan root.

## Scanner behavior

Preserve these semantics:

- supported paths are discovered recursively
- backup directories are excluded
- metadata reads are concurrent with a bounded worker count
- cancellation is cooperative
- progress is reported as completed / total during metadata processing
- ordinary per-file read failures do not abort the entire scan
- returned records remain in discovery order
- a stopped scan may return already completed partial results

The C# implementation does not need to copy Python's thread-pool mechanics exactly. `Parallel.ForEachAsync`, Channels, Tasks, or another bounded asynchronous design are acceptable if externally visible behavior remains equivalent.

## UI parity requirements

The first native UI should contain:

- Library, Review and Repair log views
- a compact folder scan control and Stop action
- filename/path search
- media filter
- sortable table columns
- File, Type, Size, Created, Modified, Taken At, Filename Date, Location, and Review reason where applicable
- Location displays the containing folder, not the filename again
- checkboxes plus Ctrl/Shift range selection using one selection model
- Select all and Clear
- right-click open, reveal in Explorer and copy-path actions
- sticky repair action area with selection count, repair method, backup state and `Review changes…`
- dedicated repair preview dialog

Do not reproduce Tkinter-specific implementation details when WinUI has a more appropriate native control.

## Cross-platform Python direction

Do not claim identical filesystem capabilities across operating systems.

The Python edition can later become the macOS/Linux implementation for:

- EXIF inspection and repair where safe
- filename timestamp inference
- modification-time repair
- backups and audit logging
- scanning/review workflow

Windows filesystem creation-time mutation remains a Windows-specific capability. macOS birth-time and Linux birth-time support should be added only when the platform/filesystem exposes a safe, tested implementation.

## Migration milestones

### M0: contract

- this architecture document committed
- shared behavior fixture committed

### M1: native skeleton

- WinUI 3 packaged solution under `windows-native/`
- .NET core and test projects
- CI builds/tests native solution on Windows
- no destructive operations yet

### M2: read-only parity

- folder selection
- scanner
- filesystem timestamps
- EXIF Taken At reading
- filename inference
- review rules
- Library and Review UI
- search/filter/sort
- parity tests passing

### M3: repair parity

- repair planning/preview
- backups
- audit logging
- Created and Modified repair
- conservative JPEG Taken At repair
- post-repair rescan
- failure-path tests

### M4: Store package

- package identity populated from Partner Center reservation
- release configuration builds MSIX/MSIX bundle
- package tested on a clean Windows user profile
- Microsoft Store submission assets prepared

### M5: Python cross-platform work

Only after the Windows native edition is stable:

- extract Windows-specific Python filesystem code behind a platform adapter
- make Linux/macOS capability differences explicit in the UI
- package Python edition for non-technical macOS/Linux users

## Definition of native parity

The native edition is considered at parity only when:

- all relevant cases in `spec/behavior-contract.json` pass in C#
- translated safety tests pass
- manual scans against the same sample folders produce materially equivalent values and review decisions
- at least one real JPEG with existing EXIF is repaired without image-payload degradation and without changing filesystem timestamps during an EXIF-only operation
- backup and audit artifacts match the documented semantics
- cancellation and large-batch preview behavior are verified manually
- MSIX installs, launches, uninstalls cleanly and can access user-selected folders

Until then, the Python implementation remains the source of truth for product behavior.
