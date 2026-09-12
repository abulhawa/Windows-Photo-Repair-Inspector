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
        FileTimes? takenTimes = null;
        try
        {
            path = RequireInsideRoot(path);
            if (!File.Exists(path)) throw new FileNotFoundException("The selected file no longer exists.", path);

            // Capture these before even re-reading metadata. The complete Taken At
            // repair attempt, including backup and post-write rescan, must not alter
            // filesystem Created, Modified, or Accessed timestamps.
            if (previewedPlan.Method.Target == "taken")
                takenTimes = FileTimes.Capture(path);

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

            MediaRecord refreshed = reader.ReadFile(path);
            if (takenTimes is { } preserved) preserved.Restore(path);

            string status = createBackup ? "OK" : "OK (no backup)";
            AppendLog(path, currentPlan.Method.Label, currentPlan.Before, currentPlan.After, backup, status);
            return new RepairExecutionResult(currentPlan, true, status, backup, refreshed);
        }
        catch (Exception ex)
        {
            if (takenTimes is { } preserved)
            {
                try { preserved.Restore(path); }
                catch (Exception restoreError)
                {
                    ex = new IOException(
                        $"{ex.Message} Additionally, filesystem timestamps could not be restored: {restoreError.Message}",
                        ex);
                }
            }
            string status = createBackup ? $"ERROR: {ex.Message}" : $"ERROR (no backup): {ex.Message}";
            TryAppendFailureLog(path, previewedPlan, backup, status);
            return new RepairExecutionResult(previewedPlan, false, status, backup, null);
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
        string safePath = RequireInsideRoot(path);
        string relative = Path.GetRelativePath(root, safePath);
        string backup = Path.GetFullPath(Path.Combine(backupRoot, relative));
        RequireInsideDirectory(backupRoot, backup, "Backup path escaped the backup directory.");

        if (File.Exists(backup)) return backup;

        var times = FileTimes.Capture(safePath);
        Directory.CreateDirectory(Path.GetDirectoryName(backup)!);
        File.Copy(safePath, backup, overwrite: false);
        times.Restore(backup);
        return backup;
    }

    private string RequireInsideRoot(string path)
    {
        RequireInsideDirectory(root, path, "Selected file is outside the scanned folder.");
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
        bool exists = File.Exists(logPath);
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

    private static string Csv(string value) =>
        value.IndexOfAny(new[] { ',', '"', '\r', '\n' }) >= 0
            ? $"\"{value.Replace("\"", "\"\"")}\""
            : value;

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
