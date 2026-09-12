# Native Windows edition

Open `PhotoRepair.sln` in Visual Studio and select **PhotoRepair.App**, **x64**,
and the packaged launch profile. The existing Python application remains at the
repository root as the behavioral reference during native parity work.

## Prerequisites and commands

Windows 10 1809 or newer, Visual Studio with WinUI application development tools,
.NET 10 SDK, and Windows SDK build tools are required. The project pins stable
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
PublisherDisplayName match `docs/store-identity.md`.

Check `InstallLocation` when switching between Debug and Release: Windows can
retain an earlier development registration at the same package version. Uninstall
that development registration before registering a different build directory.
Launching the executable directly does not activate package identity; use Start
or Visual Studio's packaged profile for package verification. Close the running
app before rebuilding to release its DLLs.

## Architecture and behavior

- **PhotoRepair.Core** is platform-independent. It contains records, timestamp and
  filename inference, media classification, review rules, query/sort helpers,
  selection state, repair methods, repair planning, no-op/unavailable-source
  checks, and bounded batch previews.
- **PhotoRepair.Windows** contains bounded scanning, filesystem timestamp access,
  WIC metadata reading, root-confined repair execution, reparse-point rejection,
  first-original backups, transactional rollback, audit logging, post-repair
  rescanning, and conservative JPEG Taken At writes.
- **PhotoRepair.App** is packaged WinUI 3. Code-behind connects native picker,
  keyboard/pointer, clipboard, shell and confirmation-dialog events to the
  UI-independent inspection view model. Business repair rules remain outside the UI.

Discovery is recursive and skips `.photo-repair-backups` before traversal.
Results retain discovery order despite concurrent reads. Cancellation returns
completed partial results; a cancelled scan with no results keeps the previous
collection. Per-file read failures are isolated. Discovery also skips reparse
points and inaccessible subdirectories.

Filesystem values carry explicit offsets. Filename and EXIF timestamps retain
local wall-clock interpretation, and epoch filenames convert to local display.
The shared JSON contract drives the relevant C# parity cases.

## M3 repair safety

A table action never modifies a file. The repair path is:

1. select files and a repair method;
2. build a pure repair plan from the scanned records;
3. skip records whose source timestamp is unavailable, whose destination already
   equals the proposed value, or whose Taken At target is not JPEG;
4. show selected/applicable/skipped counts plus at most 10 exact before/after
   examples in a dedicated confirmation dialog;
5. show an explicit warning if backups are disabled;
6. only after confirmation, re-read each file and reject a stale preview before
   any destructive change;
7. reject the repair if the scanned root, source path, backup path, or audit-log
   path traverses a junction or symbolic link;
8. capture rollback state before the write. Filesystem-time repairs retain the
   original times; Taken At repairs retain a private byte-for-byte temporary copy;
9. apply the repair, restore protected filesystem timestamps when applicable,
   rescan immediately, verify the resulting target equals the value the user
   confirmed, and append the audit entry;
10. commit the repair only after all post-write checks and logging succeed.

If any step after the write fails, the pre-repair state is restored before the
operation is reported as failed. This rollback also applies when built-in backups
were explicitly disabled. Temporary Taken At rollback copies use delete-on-close
storage and are not retained after the attempt completes.

Backups are enabled by default. The first pre-repair original is stored under
`.photo-repair-backups/` using the source path relative to the scanned root.
Existing backups are never overwritten. A record outside the scanned root is
refused, and existing reparse points anywhere in the root/source/backup traversal
are refused rather than resolved and trusted. Every normal repair attempt is
appended to `.photo-repair-repair-log.csv`, including failures and explicitly
chosen no-backup repairs. The log path itself is also rejected if it is redirected
through a reparse point.

Created and Modified repairs use the native .NET filesystem timestamp APIs.
Taken At repair remains JPEG-only and never invokes a JPEG encoder. The native
writer operates only on the EXIF APP1 metadata segment:

- if the JPEG has no EXIF APP1 segment, a minimal EXIF segment is inserted before
  image data;
- if EXIF already exists, the existing TIFF payload remains at the same relative
  offsets, unknown IFD entries and pointers are preserved, and new IFD0/Exif IFD
  tables are appended with DateTime, DateTimeOriginal and DateTimeDigitized set
  to the confirmed value;
- malformed TIFF headers, unsupported EXIF IFD pointer representations, invalid
  offsets, or an APP1 payload that would exceed JPEG's segment-size limit fail
  closed rather than rewriting image pixels.

For Taken At repairs, filesystem Created, Modified and Accessed timestamps are
captured before metadata access, restored before the required post-repair rescan,
and restored again after the read. A repair is reported as failed if the refreshed
record does not contain the confirmed target value; the original bytes and
filesystem timestamps are then restored from the private rollback state.

## Verification

M1/M2 was manually validated on Windows 11 build 26200 with .NET SDK 10.0.401:

| Check | Result |
| --- | --- |
| Release solution build | Passed, zero warnings/errors |
| Core/shared-contract tests | Passed |
| Windows adapter/view-model tests | Passed |
| Existing Python tests | Passed |
| Python compileall | Passed |
| Unsigned Release MSIX | Built |
| Development registration and packaged activation | Passed with corrected PFN |
| Live folder picker and generated fixture scan | Passed |
| Live search, filters, sorting, scrolling and selection | Passed |
| Live Stop during a 5,000-file synthetic scan | Stopped promptly and retained previous results |

M3 adds automated coverage for repair planning, unavailable/no-op skipping,
10-example preview limits, first-original backups, backup-off auditing, root
confinement, stale-preview refusal, Created/Modified application, post-repair
view-model refresh, failure-path rollback, junction redirection of the source and
backup tree, filesystem timestamp restoration, and JPEG Taken At repair. JPEG
tests compare bytes from the Start Of Scan marker onward so a metadata repair
cannot silently pass after image recompression. Existing-EXIF, empty-EXIF, and
genuinely no-EXIF paths are exercised on synthetic fixtures. Post-write tests
also force verification and audit-log failures with backups disabled and require
the pre-repair state to be restored.

A final M3 manual destructive-operation pass on Windows is still required before
native repair parity is declared complete. That pass should exercise the preview
UI, backup-on and backup-off warnings, a real JPEG with existing EXIF, the Repair
log, and post-repair Library/Review behavior.

## M4 remains separate

Store identity is already populated from the Partner Center reservation and the
Release configuration can build an unsigned MSIX. Final Store artwork, production
signing, clean-profile install/uninstall validation, and Microsoft Store submission
remain M4 work. The unsigned MSIX build can warn when optional `mspdbcmf.exe`
symbol-package tooling is absent; that warning does not prevent MSIX creation.