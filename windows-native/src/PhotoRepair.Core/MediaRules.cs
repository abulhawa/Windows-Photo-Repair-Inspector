using System.Globalization;

namespace PhotoRepair.Core;

public sealed record RepairMethod(string Label, string Target, string Source);

public static class MediaRules
{
    public const double ToleranceSeconds = 1;
    public const string BackupDirectory = ".photo-repair-backups";
    public static IReadOnlyList<string> ImageExtensions { get; } = Array.AsReadOnly(new[] { ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".webp" });
    public static IReadOnlyList<string> VideoExtensions { get; } = Array.AsReadOnly(new[] { ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp", ".webm" });
    public static IReadOnlyList<string> WritableTakenExtensions { get; } = Array.AsReadOnly(new[] { ".jpg", ".jpeg" });
    public static IReadOnlyList<string> ReviewFilters { get; } = Array.AsReadOnly(new[] { "Missing Taken At", "Taken > Created", "Taken > Modified" });
    // Definitions only. No execution or file-writing API exists in M1/M2.
    public static IReadOnlyList<RepairMethod> RepairMethods { get; } = Array.AsReadOnly(new[] {
        new RepairMethod("Set Taken At from filename", "taken", "filename"),
        new RepairMethod("Set Taken At from Created", "taken", "created"),
        new RepairMethod("Set Created from Taken At", "created", "taken"),
        new RepairMethod("Set Created from filename", "created", "filename"),
        new RepairMethod("Set Modified from Taken At", "modified", "taken"),
        new RepairMethod("Set Modified from filename", "modified", "filename")
    });
    public static string Classify(string path)
    {
        string extension = Path.GetExtension(path).ToLowerInvariant();
        return ImageExtensions.Contains(extension) ? "image" : VideoExtensions.Contains(extension) ? "video" : "other";
    }
    public static IReadOnlyList<string> DetectIssues(MediaRecord record)
    {
        List<string> issues = [];
        if (record.Taken.Length == 0 && record.MediaType == "image" && WritableTakenExtensions.Contains(Path.GetExtension(record.Path).ToLowerInvariant()))
            issues.Add(ReviewFilters[0]);
        if (record.TakenAt is { } taken)
        {
            if ((taken - record.CreatedAt).TotalSeconds > ToleranceSeconds) issues.Add(ReviewFilters[1]);
            if ((taken - record.ModifiedAt).TotalSeconds > ToleranceSeconds) issues.Add(ReviewFilters[2]);
        }
        return issues;
    }
    public static string? ProposeTaken(string created, string filename, string taken) =>
        created.Length < 19 || filename.Length < 19 || taken.Length != 0 || created[..10] != filename[..10]
            ? null : filename[11..] == "00:00:00" ? created : filename;
    public static string FormatSize(long bytes)
    {
        double size = bytes;
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        int unit = 0;
        while (size >= 1024 && unit < units.Length - 1) { size /= 1024; unit++; }
        return size.ToString(unit == 0 ? "0" : "F1", CultureInfo.InvariantCulture) + " " + units[unit];
    }
}
