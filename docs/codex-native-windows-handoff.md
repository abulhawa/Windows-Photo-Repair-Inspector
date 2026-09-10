# Codex handoff: native Windows implementation

Work in the repository `abulhawa/Windows-Photo-Repair-Inspector`.

Read these files before changing code:

- `docs/windows-native-migration.md`
- `spec/behavior-contract.json`
- `photo_repair/core.py`
- `photo_repair/metadata.py`
- `photo_repair/repair.py`
- `photo_repair/scanner.py`
- `photo_repair/ui.py`
- all existing Python tests

The Python implementation is the current behavioral reference. Do not rewrite or relocate it during the initial native work.

## Objective

Create a native Windows edition under `windows-native/` using C#, .NET 10 and a packaged WinUI 3 application. The first implementation should reach behavioral parity with the Python application before adding new repair rules or expanding writable formats.

Use the latest stable Windows App SDK available in the installed toolchain. Do not use preview packages unless a stable package cannot satisfy a required feature, and if that happens stop and report the blocker rather than silently adopting preview dependencies.

## Required solution structure

Create:

```text
windows-native/
├── PhotoRepair.sln
├── src/
│   ├── PhotoRepair.App/
│   ├── PhotoRepair.Core/
│   └── PhotoRepair.Windows/
└── tests/
    ├── PhotoRepair.Core.Tests/
    └── PhotoRepair.Windows.Tests/
```

Use nullable reference types, warnings as errors where practical, analyzers, and deterministic builds.

`PhotoRepair.Core` must not reference WinUI or Windows-specific APIs.

## First delivery scope

Implement milestones M1 and M2 from `docs/windows-native-migration.md` first. Do not implement destructive repairs until the read-only application and parity tests are stable.

### M1

- solution and projects compile on Windows
- packaged WinUI 3 app launches
- core project and xUnit test project exist
- GitHub Actions builds/tests the native solution on Windows
- C# tests load `spec/behavior-contract.json`

### M2

- folder picker
- recursive supported-media discovery
- exclusion of `.photo-repair-backups`
- bounded concurrent metadata scanning
- cooperative cancellation
- Created and Modified filesystem timestamps
- Taken At metadata reading
- filename date/time inference
- review rules
- Library and Review views
- filename/path search
- media/review filters
- sortable columns
- selection behavior sufficient for later repair workflow

Preserve discovery-order results even if metadata work completes out of order.

## Core parity

Translate the Python behavior, not its syntax.

At minimum, consume every relevant case from `spec/behavior-contract.json` in C# tests. The following must match exactly:

- timestamp display format
- filename parsing cases
- date-only proposal logic
- current review conditions and one-second tolerance
- current repair method labels/target/source definitions, even before repair execution is implemented
- inclusive selection range behavior

Do not change `Taken > Created`, `Taken > Modified`, or `Missing Taken At` semantics during this port. Product-rule changes belong in separate later work.

## Windows timestamp implementation

Prefer .NET filesystem APIs for creation and last-write timestamps. Do not introduce P/Invoke merely to mirror the Python implementation.

Keep timestamp representation explicit. Avoid accidental UTC/local conversions. The Python reference displays local wall-clock timestamps and filename-derived timestamps are local wall-clock values.

## Photo metadata implementation

Read `System.Photo.DateTaken` / EXIF capture metadata using Windows-native facilities where practical. Prefer Windows Imaging Component or the Windows Property System over an image pipeline that re-encodes files.

For the future write path, the safety requirement is stronger than convenience: changing Taken At must not recompress JPEG image data or silently destroy unrelated metadata.

Do not implement TIFF Taken At writes in the parity release even if the Windows API exposes them. Python currently permits Taken At writes only for `.jpg` and `.jpeg`.

## UI direction

Use native WinUI controls and Windows interaction conventions. Do not copy Tkinter layout mechanically.

The application should remain table-centric and compact. Required concepts:

- Library
- Review
- Repair log
- scan folder / stop
- search
- filters
- sortable metadata table
- selection state

The eventual repair action bar and preview dialog are described in the migration plan, but destructive repair execution belongs to M3.

## Testing rules

Do not weaken existing Python tests to make the native implementation easier.

Add tests for Windows-specific adapters using temporary directories/files. Where a test requires Windows, keep it in `PhotoRepair.Windows.Tests` and run it only in the Windows CI job.

For JPEG metadata tests, include generated fixture files rather than relying on personal photos. Tests should verify that reading DateTimeOriginal works when it is stored in the EXIF sub-IFD.

Before implementing writes in M3, add a regression test that can detect pixel/image payload changes caused by metadata-only operations.

## Git discipline

Use a new feature branch for the native implementation. Keep commits scoped and readable. Do not commit Visual Studio user files, build outputs, generated package artifacts, signing keys, certificates or secrets.

Do not rename the repository in this task.

## Stop conditions

Stop and report rather than guessing if any of these occur:

- WinUI template/tooling unavailable on the machine
- stable Windows App SDK cannot target the intended supported Windows versions
- selected metadata API requires JPEG re-encoding for a Taken At-only write
- Store/MSIX identity values are required but have not yet been supplied from Partner Center
- a parity decision conflicts with the existing Python tests or `spec/behavior-contract.json`

## Completion report

At the end of each milestone, report:

- files/projects added
- architecture decisions made
- test counts and results
- manual run result
- any behavioral differences from Python
- remaining blockers before the next milestone

Do not claim parity unless the shared contract tests pass and the native app has been manually run on Windows.
