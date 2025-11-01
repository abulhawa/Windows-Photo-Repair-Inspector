using System;
using System.Collections.Generic;
using PhotoRepairInspector.Utilities;

namespace PhotoRepairInspector.Models;

public class MediaFileInfo
{
    public required string FilePath { get; init; }
    public required string FileName { get; init; }
    public required string DirectoryName { get; init; }
    public required long Size { get; init; }
    public required DateTime Created { get; init; }
    public required DateTime Modified { get; init; }
    public DateTime? ParsedDate { get; set; }
    public DateTime? ExifDate { get; set; }
    public bool IsImage { get; init; }
    public bool IsVideo { get; init; }
    public string Extension { get; init; } = string.Empty;
    public string? Resolution { get; set; }
    public MediaSource Source { get; set; } = MediaSource.Unknown;
    public MediaActionType ProposedAction { get; set; } = MediaActionType.NoChange;
    public string? ActionReason { get; set; }
    public string? Notes { get; set; }
    public string GroupKey => ParsedDate?.ToString("yyyyMMdd_HHmmss") ?? string.Empty;
    public bool IsCompressedVariant { get; set; }
    public bool IsGroupPrimary { get; set; }
    public IReadOnlyList<MediaFileInfo> Duplicates { get; set; } = Array.Empty<MediaFileInfo>();

    public string SizeDisplay => FileSizeFormatter.ToDisplay(Size);
}
