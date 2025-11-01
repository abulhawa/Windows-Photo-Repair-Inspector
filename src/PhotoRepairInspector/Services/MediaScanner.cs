using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using PhotoRepairInspector.Models;
using PhotoRepairInspector.Utilities;

namespace PhotoRepairInspector.Services;

public sealed class MediaScanner
{
    public IReadOnlyList<MediaFileInfo> Scan(string rootFolder, AppConfig config, Action<string>? progress = null)
    {
        if (string.IsNullOrWhiteSpace(rootFolder) || !Directory.Exists(rootFolder))
        {
            return Array.Empty<MediaFileInfo>();
        }

        var comparison = StringComparer.OrdinalIgnoreCase;
        var supported = new HashSet<string>(config.SupportedExtensions, comparison);
        var files = Directory.EnumerateFiles(rootFolder, "*", SearchOption.AllDirectories)
            .Where(f => supported.Contains(Path.GetExtension(f)))
            .ToList();

        var items = new List<MediaFileInfo>();
        foreach (var file in files)
        {
            progress?.Invoke(file);
            var fileInfo = new FileInfo(file);
            var parsedDate = DateParsingService.TryParse(fileInfo.Name);
            var (dateTaken, resolution) = fileInfo.Extension.IsImageExtension()
                ? MetadataService.ReadMetadata(file)
                : (null, null);

            var source = DetectSource(fileInfo.Name);
            var item = new MediaFileInfo
            {
                FilePath = file,
                FileName = fileInfo.Name,
                DirectoryName = fileInfo.DirectoryName ?? string.Empty,
                Size = fileInfo.Length,
                Created = fileInfo.CreationTime,
                Modified = fileInfo.LastWriteTime,
                ParsedDate = parsedDate,
                ExifDate = dateTaken,
                Resolution = resolution,
                IsImage = fileInfo.Extension.IsImageExtension(),
                IsVideo = fileInfo.Extension.IsVideoExtension(),
                Extension = fileInfo.Extension,
                Source = source,
            };

            ApplyRuleSet(item, config);
            items.Add(item);
        }

        if (config.AutoGroupByParsedDate)
        {
            AnalyzeGroups(items, config);
        }

        return items;
    }

    private static void ApplyRuleSet(MediaFileInfo item, AppConfig config)
    {
        if (item.ParsedDate == null)
        {
            item.ActionReason = "No date in filename";
            item.Notes = "no date in filename";
            item.ProposedAction = MediaActionType.NoChange;
            return;
        }

        var tolerance = TimeSpan.FromDays(Math.Max(0, config.ProblemDateToleranceDays));
        var lower = config.ProblemDate - tolerance;
        var upper = config.ProblemDate + tolerance;
        if (item.Created >= lower && item.Created <= upper && item.Modified >= lower && item.Modified <= upper)
        {
            item.ProposedAction = MediaActionType.FixDateFromFilename;
            item.ActionReason = $"File dates near {config.ProblemDate:dd.MM.yyyy}; filename suggests {item.ParsedDate:dd.MM.yyyy}";
        }

        if (item.IsImage)
        {
            if (item.ExifDate == null && item.ParsedDate != null)
            {
                item.Notes = AppendNote(item.Notes, "EXIF missing");
                if (item.ProposedAction == MediaActionType.NoChange)
                {
                    item.ProposedAction = MediaActionType.WriteExifFromFilename;
                    item.ActionReason ??= "Missing EXIF date";
                }
            }
            else if (item.ExifDate != null && item.ParsedDate != null && item.ExifDate.Value != item.ParsedDate.Value)
            {
                item.Notes = AppendNote(item.Notes, "EXIF date differs");
            }
        }

        if (item.Source == MediaSource.WhatsApp)
        {
            item.Notes = AppendNote(item.Notes, "WhatsApp copy (likely compressed)");
        }
    }

    private static void AnalyzeGroups(List<MediaFileInfo> items, AppConfig config)
    {
        var groups = items
            .Where(x => x.ParsedDate != null)
            .GroupBy(x => x.GroupKey)
            .Where(g => !string.IsNullOrEmpty(g.Key));

        foreach (var group in groups)
        {
            var ordered = group.OrderByDescending(x => x.Size).ToList();
            var primary = ordered.FirstOrDefault();
            if (primary == null)
            {
                continue;
            }

            primary.IsGroupPrimary = true;
            var threshold = primary.Size * config.MinCompressedSizeRatio;
            foreach (var item in ordered.Skip(1))
            {
                if (item.Size < threshold)
                {
                    item.IsCompressedVariant = true;
                    item.Notes = AppendNote(item.Notes, "Smaller/Compressed copy");
                    if (item.ProposedAction == MediaActionType.NoChange)
                    {
                        item.ProposedAction = MediaActionType.DeleteSmallerCompressedCopy;
                        item.ActionReason = "Detected smaller copy in group";
                    }
                }
            }

            foreach (var item in ordered)
            {
                item.Duplicates = ordered;
            }
        }
    }

    private static MediaSource DetectSource(string fileName)
    {
        if (fileName.Contains("-WA", StringComparison.OrdinalIgnoreCase))
        {
            return MediaSource.WhatsApp;
        }

        if (fileName.StartsWith("IMG_", StringComparison.OrdinalIgnoreCase) ||
            fileName.StartsWith("VID_", StringComparison.OrdinalIgnoreCase) ||
            fileName.StartsWith("PXL_", StringComparison.OrdinalIgnoreCase))
        {
            return MediaSource.Camera;
        }

        if (fileName.Contains("GOOGLE", StringComparison.OrdinalIgnoreCase))
        {
            return MediaSource.GooglePhotos;
        }

        return MediaSource.Unknown;
    }

    private static string AppendNote(string? existing, string addition)
    {
        if (string.IsNullOrWhiteSpace(existing))
        {
            return addition;
        }

        if (existing.Contains(addition, StringComparison.OrdinalIgnoreCase))
        {
            return existing;
        }

        return $"{existing}; {addition}";
    }
}

internal static class ExtensionChecks
{
    private static readonly string[] ImageExtensions = { ".jpg", ".jpeg", ".png", ".heic" };
    private static readonly string[] VideoExtensions = { ".mp4", ".mov" };

    public static bool IsImageExtension(this string extension)
        => ImageExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase);

    public static bool IsVideoExtension(this string extension)
        => VideoExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase);
}
