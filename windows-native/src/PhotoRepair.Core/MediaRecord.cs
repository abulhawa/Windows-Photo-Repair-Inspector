namespace PhotoRepair.Core;

// Instants carry offsets; filename/EXIF values are parsed as local wall-clock times.
public sealed record MediaRecord(
    string Path, string MediaType, long SizeBytes, DateTimeOffset CreatedAt,
    DateTimeOffset ModifiedAt, string Taken = "", DateTimeOffset? TakenAt = null,
    DateTimeOffset? FilenameAt = null)
{
    public string Name => System.IO.Path.GetFileName(Path);
    public string Location => System.IO.Path.GetDirectoryName(Path) ?? "";
    public string Created => Timestamps.Format(CreatedAt);
    public string Modified => Timestamps.Format(ModifiedAt);
    public string FilenameDate => FilenameAt is { } value ? Timestamps.Format(value) : "";
    public string Size => MediaRules.FormatSize(SizeBytes);
    public IReadOnlyList<string> Issues => MediaRules.DetectIssues(this);
    public string ReviewReason => string.Join("; ", Issues);
    public string? ProposedTaken => MediaRules.ProposeTaken(Created, FilenameDate, Taken);
}
