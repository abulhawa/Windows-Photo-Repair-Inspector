using System.Globalization;
using System.IO;
using System.Windows.Media.Imaging;
using PhotoRepair.Core;

namespace PhotoRepair.Windows;

public interface ITakenMetadataWriter
{
    void WriteTaken(string path, DateTimeOffset timestamp);
}

public sealed class TakenMetadataWriter : ITakenMetadataWriter
{
    public void WriteTaken(string path, DateTimeOffset timestamp)
    {
        string extension = Path.GetExtension(path).ToLowerInvariant();
        if (!MediaRules.WritableTakenExtensions.Contains(extension))
            throw new InvalidOperationException("Taken At updates are supported only for JPEG files.");

        // Use WIC's in-place metadata writer. This never runs a JPEG encoder and
        // therefore cannot recompress image pixels. If the existing JPEG metadata
        // block cannot be safely opened or has insufficient writable space, fail
        // closed rather than rebuilding/re-encoding the file.
        using var stream = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.Read);
        var decoder = new JpegBitmapDecoder(
            stream,
            BitmapCreateOptions.PreservePixelFormat,
            BitmapCacheOption.OnDemand);
        if (decoder.Frames.Count == 0 || decoder.Frames[0].Metadata is not BitmapMetadata)
            throw new InvalidDataException(
                "Existing JPEG metadata could not be read safely; refusing to overwrite it.");

        InPlaceBitmapMetadataWriter writer;
        try
        {
            writer = decoder.Frames[0].CreateInPlaceBitmapMetadataWriter();
        }
        catch (Exception ex) when (MetadataReader.IsReadFailure(ex))
        {
            throw new InvalidDataException(
                "Existing JPEG metadata could not be opened for a safe in-place update.", ex);
        }

        if (!writer.TrySave())
            throw new InvalidOperationException(
                "The JPEG does not have enough writable metadata space for a safe in-place Taken At update.");

        string value = timestamp.ToLocalTime().ToString(
            "yyyy:MM:dd HH:mm:ss",
            CultureInfo.InvariantCulture);
        try
        {
            // WPF maps DateTaken to the Windows/WIC photo capture metadata. The
            // existing reader resolves DateTimeOriginal/DateTimeDigitized/DateTime.
            writer.DateTaken = value;
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or NotSupportedException)
        {
            throw new InvalidDataException(
                "The JPEG Taken At metadata could not be updated safely in place.", ex);
        }
    }
}
