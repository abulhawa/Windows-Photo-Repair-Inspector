using System.Globalization;
using System.IO;
using System.Text;
using PhotoRepair.Core;

namespace PhotoRepair.Windows;

public sealed record RepairExecutionResult(
    RepairPlanItem Plan,
    bool Success,
    string Status,
    string? BackupPath,
    MediaRecord? RefreshedRecord);

public sealed class RepairService
{
    private readonly string root;
    private readonly string backupRoot;
    private readonly string logPath;
    private readonly MetadataReader reader;
    private readonly ITakenMetadataWriter takenWriter;

    public RepairService(
        string root,
        MetadataReader? reader = null,
        ITakenMetadataWriter? takenWriter = null)
    {
        this.root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root));
        backupRoot = Path.Combine(this.root, MediaRules.BackupDirectory);
        logPath = Path.Combine(this.root, ".photo-repair-repair-log.csv");
        this.reader = reader ?? new MetadataReader();
        this.takenWriter = takenWriter ?? new TakenMetadataWriter();
    }

    public string BackupRoot => backupRoot;
    public string LogPath => logPath;

    public RepairExecutionResult Apply(RepairPlanItem previewedPlan, bool createBackup = true)
    {
        string path = Path.GetFullPath(previewedPlan.Record.Path);
        string? backup = null;
        FileTimes? originalTimes = null;
        RollbackState? rollback = null;
        try
        {
            path = RequireSafeSourcePath(path);
            if (!File.Exists(path)) throw new FileNotFoundException("The selected file no longer exists.", path);

            // Capture the pre-attempt filesystem state before metadata reads can
            // touch Accessed. Taken At success restores these values; every target
            // uses them if a later verification or logging step needs rollback.
            originalTimes = FileTimes.Capture(path);

            // Re-read immediately before writing. If the values shown in the
            // confirmation preview are stale, do not apply an unreviewed change.
            MediaRecord current = reader.ReadFile(path);
            RepairPlanItem currentPlan = RepairPlanner.Plan(current, previewedPlan.Method);
            if (!currentPlan.Applicable ||
                currentPlan.Before != previewedPlan.Before ||
                currentPlan.After != previewedPlan.After)
            {
                throw new InvalidOperationException(
                    "File metadata changed since the preview. Rescan and review the change again.");
            }

            // Do not begin a destructive operation until both the source path and
            // any existing backup path are proven to contain no junction/symlink
            // traversal. Rollback state is private and is retained until the
            // post-write rescan, verification and audit-log append all succeed.
            rollback = RollbackState.Capture(path, currentPlan.Method.Target, originalTimes.Value);
            if (createBackup) backup = BackupFile(path);
            DateTimeOffset value = currentPlan.ProposedValue
                ?? throw new InvalidOperationException("The repair source timestamp is no longer available.");

            switch (currentPlan.Method.Target)
            {
                case "created":
                    File.SetCreationTimeUtc(path, value.UtcDateTime);
                    break;
                case "modified":
                    File.SetLastWriteTimeUtc(path, value.UtcDateTime);
                    break;
                case "taken":
                    takenWriter.WriteTaken(path, value);
                    break;
                default:
                    throw new InvalidOperationException($"Unknown repair target: {currentPlan.Method.Target}");
            }

            // Metadata-only repairs must preserve filesystem timestamps. Restore
            // before rescanning so the refreshed record contains the preserved
            // Created/Modified values, then restore Accessed once more after read.
            if (currentPlan.Method.Target == "taken") originalTimes.Value.Restore(path);
            MediaRecord refreshed = reader.ReadFile(path);
            if (currentPlan.Method.Target == "taken") originalTimes.Value.Restore(path);

            if (TargetDisplay(refreshed, currentPlan.Method.Target) != currentPlan.After)
                throw new IOException("Repair did not produce the value confirmed in the preview.");

            string status = createBackup ? "OK" : "OK (no backup)";
            AppendLog(path, currentPlan.Method.Label, currentPlan.Before, currentPlan.After, backup, status);
            rollback.Commit();
            return new RepairExecutionResult(currentPlan, true, status, backup, refreshed);
        }
        catch (Exception ex)
        {
            if (rollback is not null)
            {
                try
                {
                    // Revalidate the path before rollback as well. Never restore a
                    // snapshot through a path that has meanwhile become a junction.
                    RequireSafeSourcePath(path);
                    rollback.Restore();
                }
                catch (Exception rollbackError)
                {
                    ex = new IOException(
                        $"{ex.Message} Additionally, the pre-repair state could not be restored: {rollbackError.Message}",
                        ex);
                }
            }
            else if (originalTimes is { } preserved && File.Exists(path))
            {
                // No content write was started, but a metadata read may have
                // touched Accessed. Taken At promises complete time preservation.
                if (previewedPlan.Method.Target == "taken")
                {
                    try { preserved.Restore(path); }
                    catch (Exception restoreError)
                    {
                        ex = new IOException(
                            $"{ex.Message} Additionally, filesystem timestamps could not be restored: {restoreError.Message}",
                            ex);
                    }
                }
            }

            string status = createBackup ? $"ERROR: {ex.Message}" : $"ERROR (no backup): {ex.Message}";
            TryAppendFailureLog(path, previewedPlan, backup, status);
            return new RepairExecutionResult(previewedPlan, false, status, backup, null);
        }
        finally
        {
            rollback?.Dispose();
        }
    }

    public IReadOnlyList<RepairExecutionResult> ApplyBatch(
        RepairPreview preview,
        bool createBackup = true)
    {
        var results = new List<RepairExecutionResult>();
        foreach (RepairPlanItem item in preview.Items.Where(item => item.Applicable))
            results.Add(Apply(item, createBackup));
        return results;
    }

    private string BackupFile(string path)
    {
        string safePath = RequireSafeSourcePath(path);
        string relative = Path.GetRelativePath(root, safePath);
        string backup = Path.GetFullPath(Path.Combine(backupRoot, relative));
        RequireInsideDirectory(backupRoot, backup, "Backup path escaped the backup directory.");
        RequireNoReparseTraversal(root, backup, allowMissingTail: true,
            "Backup path traverses a junction or symbolic link.");

        if (File.Exists(backup))
        {
            RequireNoReparseTraversal(root, backup, allowMissingTail: false,
                "Existing backup is a junction or symbolic link.");
            return backup;
        }

        string parent = Path.GetDirectoryName(backup)
            ?? throw new InvalidOperationException("Backup path has no parent directory.");
        Directory.CreateDirectory(parent);
        RequireNoReparseTraversal(root, parent, allowMissingTail: false,
            "Backup directory traverses a junction or symbolic link.");

        var times = FileTimes.Capture(safePath);
        File.Copy(safePath, backup, overwrite: false);
        RequireNoReparseTraversal(root, backup, allowMissingTail: false,
            "Created backup resolved through a junction or symbolic link.");
        times.Restore(backup);
        return backup;
    }

    private string RequireSafeSourcePath(string path)
    {
        RequireInsideDirectory(root, path, "Selected file is outside the scanned folder.");
        RequireNoReparseTraversal(root, path, allowMissingTail: false,
            "Selected file path traverses a junction or symbolic link.");
        return path;
    }

    private static void RequireInsideDirectory(string directory, string candidate, string message)
    {
        string fullDirectory = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
        string fullCandidate = Path.GetFullPath(candidate);
        string relative = Path.GetRelativePath(fullDirectory, fullCandidate);
        if (Path.IsPathRooted(relative) ||
            relative == ".." ||
            relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            relative.StartsWith(".." + Path.AltDirectorySeparatorChar, StringComparison.Ordinal))
        {
            throw new InvalidOperationException(message);
        }
    }

    private static void RequireNoReparseTraversal(
        string trustedRoot,
        string candidate,
        bool allowMissingTail,
        string message)
    {
        string fullRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(trustedRoot));
        string fullCandidate = Path.GetFullPath(candidate);
        RequireInsideDirectory(fullRoot, fullCandidate, message);

        if (!Directory.Exists(fullRoot))
            throw new DirectoryNotFoundException("The scanned folder is no longer available.");
        ThrowIfReparsePoint(fullRoot, message);

        string relative = Path.GetRelativePath(fullRoot, fullCandidate);
        if (relative == ".") return;

        string current = fullRoot;
        string[] components = relative.Split(
            new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar },
            StringSplitOptions.RemoveEmptyEntries);
        foreach (string component in components)
        {
            current = Path.Combine(current, component);
            bool exists = File.Exists(current) || Directory.Exists(current);
            if (!exists)
            {
                if (allowMissingTail) return;
                throw new FileNotFoundException("A repair path component is no longer available.", current);
            }
            ThrowIfReparsePoint(current, message);
        }
    }

    private static void ThrowIfReparsePoint(string path, string message)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidOperationException(message);
    }

    private void TryAppendFailureLog(
        string path,
        RepairPlanItem plan,
        string? backup,
        string status)
    {
        try
        {
            AppendLog(path, plan.Method.Label, plan.Before, plan.After, backup, status);
        }
        catch
        {
            // Preserve the original repair failure. A separate log I/O failure
            // must not hide the reason the repair itself was refused or failed.
        }
    }

    private void AppendLog(
        string path,
        string operation,
        string before,
        string after,
        string? backup,
        string status)
    {
        RequireNoReparseTraversal(root, logPath, allowMissingTail: true,
            "Repair log path traverses a junction or symbolic link.");
        bool exists = File.Exists(logPath);
        if (exists)
            RequireNoReparseTraversal(root, logPath, allowMissingTail: false,
                "Repair log is a junction or symbolic link.");

        using var stream = new FileStream(logPath, FileMode.Append, FileAccess.Write, FileShare.Read);
        using var writer = new StreamWriter(stream, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        if (!exists)
            writer.WriteLine("logged_at,file,operation,before,after,backup,status");
        writer.WriteLine(string.Join(",", new[]
        {
            Csv(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)),
            Csv(path), Csv(operation), Csv(before), Csv(after), Csv(backup ?? ""), Csv(status)
        }));
    }

    private static string TargetDisplay(MediaRecord record, string target) => target switch
    {
        "created" => record.Created,
        "modified" => record.Modified,
        "taken" => string.IsNullOrWhiteSpace(record.Taken) ? "(missing)" : record.Taken,
        _ => throw new InvalidOperationException($"Unknown repair target: {target}")
    };

    private static string Csv(string value) =>
        value.IndexOfAny(new[] { ',', '"', '\r', '\n' }) >= 0
            ? $"\"{value.Replace("\"", "\"\"")}\""
            : value;

    private sealed class RollbackState : IDisposable
    {
        private readonly string path;
        private readonly FileTimes times;
        private readonly FileAttributes attributes;
        private readonly FileStream? snapshot;
        private bool committed;
        private bool restored;

        private RollbackState(
            string path,
            FileTimes times,
            FileAttributes attributes,
            FileStream? snapshot)
        {
            this.path = path;
            this.times = times;
            this.attributes = attributes;
            this.snapshot = snapshot;
        }

        public static RollbackState Capture(string path, string target, FileTimes times)
        {
            FileAttributes attributes = File.GetAttributes(path);
            if (target != "taken")
                return new RollbackState(path, times, attributes, null);

            string directory = Path.GetDirectoryName(path)
                ?? throw new InvalidOperationException("Repair path has no parent directory.");
            string temp = Path.Combine(
                directory,
                $".{Path.GetFileName(path)}.photo-repair-txn-{Guid.NewGuid():N}.tmp");
            var snapshot = new FileStream(temp, new FileStreamOptions
            {
                Mode = FileMode.CreateNew,
                Access = FileAccess.ReadWrite,
                Share = FileShare.None,
                Options = FileOptions.DeleteOnClose | FileOptions.SequentialScan
            });
            try
            {
                using var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                source.CopyTo(snapshot);
                snapshot.Flush(flushToDisk: true);
                snapshot.Position = 0;
                return new RollbackState(path, times, attributes, snapshot);
            }
            catch
            {
                snapshot.Dispose();
                throw;
            }
        }

        public void Commit() => committed = true;

        public void Restore()
        {
            if (committed || restored) return;
            if (snapshot is not null)
            {
                snapshot.Position = 0;
                using var destination = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None);
                snapshot.CopyTo(destination);
                destination.Flush(flushToDisk: true);
            }
            File.SetAttributes(path, attributes);
            times.Restore(path);
            restored = true;
        }

        public void Dispose() => snapshot?.Dispose();
    }

    private readonly record struct FileTimes(DateTime CreationUtc, DateTime ModifiedUtc, DateTime AccessedUtc)
    {
        public static FileTimes Capture(string path) => new(
            File.GetCreationTimeUtc(path),
            File.GetLastWriteTimeUtc(path),
            File.GetLastAccessTimeUtc(path));

        public void Restore(string path)
        {
            File.SetCreationTimeUtc(path, CreationUtc);
            File.SetLastWriteTimeUtc(path, ModifiedUtc);
            File.SetLastAccessTimeUtc(path, AccessedUtc);
        }
    }
}
