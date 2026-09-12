using System.Globalization;
using System.IO;
using System.Text;
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

        JpegLayout layout;
        using (var inspect = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            layout = InspectJpeg(inspect);

        if (!layout.HasExif)
        {
            InsertMinimalExif(path, layout.InsertOffset, timestamp);
            return;
        }

        UpdateExistingExifInPlace(path, timestamp);
    }

    private static void UpdateExistingExifInPlace(string path, DateTimeOffset timestamp)
    {
        // Existing EXIF is updated through WIC's in-place metadata writer. No
        // JPEG encoder is used. If WIC cannot update any recognized date tag
        // safely in place, fail closed rather than rebuilding the image.
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

        string value = ExifValue(timestamp);
        bool wrote = false;
        // The Python reference writes 0th DateTime, DateTimeOriginal and
        // DateTimeDigitized. WIC files differ in which hierarchy is exposed, so
        // try the same tags under both JPEG query roots. Existing tags are
        // updated where writable; at least one recognized Taken At tag must save.
        string[] queries =
        [
            "/app1/ifd/{ushort=306}",
            "/app1/ifd/exif/{ushort=36867}",
            "/app1/ifd/exif/{ushort=36868}",
            "/ifd/{ushort=306}",
            "/ifd/exif/{ushort=36867}",
            "/ifd/exif/{ushort=36868}"
        ];
        foreach (string query in queries)
        {
            try
            {
                writer.SetQuery(query, value);
                wrote = true;
            }
            catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or NotSupportedException)
            {
                // Some codecs expose only one of the query roots or cannot add a
                // missing nested tag in-place. Continue so existing writable tags
                // can still be updated without rebuilding metadata.
            }
        }

        if (!wrote)
            throw new InvalidDataException(
                "The JPEG Taken At metadata could not be updated safely in place.");
    }

    private static void InsertMinimalExif(string path, long insertOffset, DateTimeOffset timestamp)
    {
        byte[] segment = BuildMinimalExifSegment(timestamp);
        using var stream = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
        long originalLength = stream.Length;
        if (insertOffset < 2 || insertOffset > originalLength)
            throw new InvalidDataException("JPEG structure is not safe for EXIF insertion.");

        stream.SetLength(checked(originalLength + segment.Length));
        byte[] buffer = new byte[1024 * 1024];
        long readEnd = originalLength;
        while (readEnd > insertOffset)
        {
            int count = (int)Math.Min(buffer.Length, readEnd - insertOffset);
            long readStart = readEnd - count;
            stream.Position = readStart;
            stream.ReadExactly(buffer.AsSpan(0, count));
            stream.Position = readStart + segment.Length;
            stream.Write(buffer, 0, count);
            readEnd = readStart;
        }
        stream.Position = insertOffset;
        stream.Write(segment);
        stream.Flush(flushToDisk: true);
    }

    private static byte[] BuildMinimalExifSegment(DateTimeOffset timestamp)
    {
        const uint ifd0Offset = 8;
        const uint exifIfdOffset = 38; // 8 + (2 + 2*12 + 4)
        const uint dateOffset = 68;    // Exif IFD adds another 30 bytes.
        byte[] date = Encoding.ASCII.GetBytes(ExifValue(timestamp) + "\0");
        if (date.Length != 20) throw new InvalidOperationException("Unexpected EXIF timestamp length.");

        using var payload = new MemoryStream();
        payload.Write(Encoding.ASCII.GetBytes("Exif\0\0"));
        using (var writer = new BinaryWriter(payload, Encoding.ASCII, leaveOpen: true))
        {
            writer.Write((byte)'I'); writer.Write((byte)'I');
            writer.Write((ushort)42);
            writer.Write(ifd0Offset);

            writer.Write((ushort)2);
            WriteEntry(writer, 0x0132, 2, 20, dateOffset);
            WriteEntry(writer, 0x8769, 4, 1, exifIfdOffset);
            writer.Write((uint)0);

            writer.Write((ushort)2);
            WriteEntry(writer, 0x9003, 2, 20, dateOffset);
            WriteEntry(writer, 0x9004, 2, 20, dateOffset);
            writer.Write((uint)0);
            writer.Write(date);
        }

        byte[] body = payload.ToArray();
        int jpegLength = checked(body.Length + 2);
        if (jpegLength > ushort.MaxValue) throw new InvalidOperationException("EXIF block is too large.");
        byte[] segment = new byte[body.Length + 4];
        segment[0] = 0xFF; segment[1] = 0xE1;
        segment[2] = (byte)(jpegLength >> 8);
        segment[3] = (byte)jpegLength;
        Buffer.BlockCopy(body, 0, segment, 4, body.Length);
        return segment;
    }

    private static void WriteEntry(BinaryWriter writer, ushort tag, ushort type, uint count, uint valueOrOffset)
    {
        writer.Write(tag);
        writer.Write(type);
        writer.Write(count);
        writer.Write(valueOrOffset);
    }

    private static string ExifValue(DateTimeOffset timestamp) =>
        timestamp.ToLocalTime().ToString("yyyy:MM:dd HH:mm:ss", CultureInfo.InvariantCulture);

    private static JpegLayout InspectJpeg(FileStream stream)
    {
        if (stream.ReadByte() != 0xFF || stream.ReadByte() != 0xD8)
            throw new InvalidDataException("The selected file is not a valid JPEG stream.");

        long position = 2;
        long insertOffset = 2;
        byte[] signature = new byte[6];
        while (position < stream.Length)
        {
            stream.Position = position;
            if (stream.ReadByte() != 0xFF)
                throw new InvalidDataException("JPEG marker structure is invalid before image data.");

            int marker;
            do { marker = stream.ReadByte(); } while (marker == 0xFF);
            if (marker < 0) throw new EndOfStreamException("Unexpected end of JPEG stream.");
            if (marker is 0xD9 or 0xDA) break;
            if (marker == 0x00)
                throw new InvalidDataException("Unexpected stuffed JPEG marker before image data.");

            if (marker == 0x01 || marker is >= 0xD0 and <= 0xD7)
            {
                position = stream.Position;
                continue;
            }

            int high = stream.ReadByte();
            int low = stream.ReadByte();
            if (high < 0 || low < 0) throw new EndOfStreamException("Unexpected end of JPEG segment.");
            int length = (high << 8) | low;
            if (length < 2) throw new InvalidDataException("JPEG segment has an invalid length.");
            long payloadStart = stream.Position;
            long next = checked(payloadStart + length - 2L);
            if (next > stream.Length) throw new InvalidDataException("JPEG segment extends beyond the file.");

            if (marker == 0xE1 && length >= 8)
            {
                stream.ReadExactly(signature);
                if (signature.AsSpan().SequenceEqual("Exif\0\0"u8))
                    return new JpegLayout(true, insertOffset);
            }

            if (marker == 0xE0 && position == insertOffset)
                insertOffset = next;
            position = next;
        }
        return new JpegLayout(false, insertOffset);
    }

    private readonly record struct JpegLayout(bool HasExif, long InsertOffset);
}
