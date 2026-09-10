# Native Windows read-only edition (M1/M2)

Open `PhotoRepair.sln` in Visual Studio and select **PhotoRepair.App**, **x64**,
and the packaged launch profile. The existing Python application remains at the
repository root and is unchanged.

## Prerequisites and commands

Windows 10 1809 or newer, Visual Studio with WinUI application development tools,
.NET 10 SDK, and Windows SDK build tools are required. This project pins stable
Windows App SDK **2.4.0** and builds a self-contained x64 desktop package.
No preview dependencies or signing certificates are required for development.
Enable Windows Developer Mode to register the loose development package.

Run from the repository root:

```powershell
dotnet build windows-native/PhotoRepair.sln -c Release -p:Platform=x64
dotnet test windows-native/tests/PhotoRepair.Core.Tests -c Release --no-build
dotnet test windows-native/tests/PhotoRepair.Windows.Tests -c Release --no-build
uv run --locked --group dev pytest
uv run --locked python -m compileall -q photo_repair main.py

# Create an unsigned MSIX; production signing and Store submission belong to M4.
dotnet build windows-native/src/PhotoRepair.App -c Release -p:Platform=x64 -p:GenerateAppxPackageOnBuild=true -p:AppxPackageSigningEnabled=false

# Register the built package, then launch Photo Metadata Repair Inspector from Start.
$appDirectory = Resolve-Path windows-native/src/PhotoRepair.App/bin/x64/Release/net10.0-windows10.0.19041.0/win-x64
Add-AppxPackage -Register "$appDirectory/AppxManifest.xml"
Get-AppxPackage QortxAI.PhotoMetadataRepairInspector | Format-List PackageFamilyName,InstallLocation
```

The registered family must be
`QortxAI.PhotoMetadataRepairInspector_whp60drgnydpm`. Name, Publisher and
PublisherDisplayName match `docs/store-identity.md`. The PFN in that document
was corrected after the owner rechecked Partner Center.

Check `InstallLocation` when switching between Debug and Release: Windows can
retain an earlier development registration at the same package version. Uninstall
that development registration before registering a different build directory.
Launching the executable directly does not activate package identity; use Start
or Visual Studio's packaged profile for package verification. Close the running
app before rebuilding to release its DLLs.

## Boundaries and behavior

- **PhotoRepair.Core** is platform-independent: records, local timestamp/filename
  inference, media classification, review rules, query/sort helpers, repair method
  definitions, and one selection model. Repair definitions do not execute repairs.
- **PhotoRepair.Windows** uses .NET filesystem reads and the managed WPF adapter
  to Windows Imaging Component (WIC). Metadata queries prefer the EXIF sub-IFD's
  DateTimeOriginal, then DateTimeDigitized, then DateTime; top-level IFD is the
  fallback. There is no encoder, metadata setter, or filesystem timestamp setter.
  Streams are read-only and metadata readers run on at most eight workers.
- **PhotoRepair.App** is packaged WinUI 3. Its code-behind connects native picker,
  keyboard/pointer, clipboard and shell events to the UI-independent inspection
  view model. Library, Review and the existing CSV repair log are readable.
  Search/media/review filters, numeric column sorting, horizontal scrolling,
  checkboxes, Ctrl/Shift selection, Select all and Clear are available.

Discovery is recursive and skips backup folders before traversal. Results retain
discovery order despite concurrent reads. Cancellation returns completed partial
results; a cancelled scan with no results keeps the previous collection. File
read failures are isolated. Discovery also skips reparse points (avoiding junction
cycles/out-of-root traversal) and inaccessible subdirectories. This is a deliberate
defensive difference from Python's path traversal.

Filesystem values carry explicit offsets. Filename and EXIF timestamps retain
local wall-clock interpretation, and epoch filenames convert to local display.
The shared JSON contract drives every relevant M1/M2 case in the C# tests.

WIC codec availability differs from Pillow/pillow-heif. Discovery supports the
same extension set; capture metadata for formats beyond the tested JPEG/IFD
queries depends on installed codecs and exposed metadata paths. Unsupported or
unreadable metadata is displayed as missing. This delivery establishes the tested
read-only contract, not complete cross-format or repair parity.

## Verification and next milestone

Local verification on Windows 11 build 26200 with .NET SDK 10.0.401:

| Check | Result |
| --- | --- |
| Release solution build | Passed, zero warnings/errors |
| Core/shared-contract tests | 29 passed |
| Windows adapter/view-model tests | 12 passed |
| Existing Python tests | 46 passed |
| Python compileall | Passed |
| Unsigned Release MSIX | Built; optional symbol-package warning below |
| Development registration and packaged activation | Passed with corrected PFN |
| Live folder picker and generated fixture scan | 4 JPEGs, 1 Review item; same capture dates and issues as Python |
| Live search, media/review filters, numeric sorting, horizontal scrolling | Passed |
| Live Select all/Clear, checkbox state and repair-log view | Passed |
| Live Stop during discovery of 5,000 synthetic JPEGs | Stopped promptly and retained previous results |

The final Release build was activated through Windows' application activation
manager. The running process's package identity was checked (not inferred from
its executable path). Table layout and fixture results were visually inspected.
Inclusive Ctrl/Shift range behavior, concurrent partial cancellation and failure
isolation also have automated coverage. GitHub Actions performs the same native
build/test/package steps on pull requests.

Generated 12x12 JPEG fixtures under `tests/PhotoRepair.Windows.Tests/Fixtures`
contain nested, digitized-only, top-level and absent EXIF dates. `generate.py`
recreates them with the repository's Python dependencies. Tests check capture
values, unchanged file bytes and Created/Modified timestamps, supported discovery,
backup exclusion, concurrency bounds, progress, ordering, cancellation, isolated
failures, and view-model filtering/selection.

Before M3, implement and verify the migration document's safety invariants:
preview/confirmation, first-original backups, audit logging, containment checks,
conservative JPEG metadata writes, image-payload preservation, filesystem timestamp
restoration, and post-repair rescanning. No M3 write behavior is present here.

Store assets are the installed WinUI template's development placeholders. Store
signing, final artwork, clean-profile installation/uninstallation and submission
remain M4 work. The unsigned MSIX build may warn that optional `mspdbcmf.exe`
symbol-package tooling is absent; this does not prevent creating the MSIX.
