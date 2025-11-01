using System;
using System.IO;
using System.Linq;
using MetadataExtractor;
using MetadataExtractor.Formats.Exif;

namespace PhotoRepairInspector.Utilities;

public static class MetadataService
{
    public static (DateTime? DateTaken, string? Resolution) ReadMetadata(string path)
    {
        if (!File.Exists(path))
        {
            return (null, null);
        }

        try
        {
            var directories = ImageMetadataReader.ReadMetadata(path);
            var subIfd = directories.OfType<ExifSubIfdDirectory>().FirstOrDefault();
            DateTime? dateTaken = null;
            if (subIfd?.TryGetDateTime(ExifDirectoryBase.TagDateTimeOriginal, out var value) == true)
            {
                dateTaken = value;
            }
            string? resolution = null;
            var width = subIfd?.GetDescription(ExifDirectoryBase.TagExifImageWidth);
            var height = subIfd?.GetDescription(ExifDirectoryBase.TagExifImageHeight);
            if (!string.IsNullOrWhiteSpace(width) && !string.IsNullOrWhiteSpace(height))
            {
                resolution = $"{width} x {height}";
            }
            return (dateTaken, resolution);
        }
        catch
        {
            return (null, null);
        }
    }
}
